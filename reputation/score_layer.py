"""
Decentralized Reputation / Resonance Score Layer.

Aggregates agent scores, outcome history, and visibility weighting across the
Fabric. Persists to Neon Postgres when available, with SQLite fallback for
local sovereignty. Designed for future replication to Cloudflare KV at the edge.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from config import CF_REPUTATION_KV_NAMESPACE, DATABASE_URL, SQLITE_PATH
from core.scoring import (
    InMemoryScoreStore,
    OutcomeTier,
    ResonanceScorer,
    ScoreUpdate,
    SqliteScoreStore,
    create_scorer,
)
from reputation.multiplier import get_visibility_multiplier
from utils.logging import setup_logging

logger = setup_logging("forge.reputation")

SUCCESS_OUTCOMES = frozenset({"success", "partial"})


class TrendDirection(str, Enum):
    """Recent performance trajectory for an agent."""

    IMPROVING = "improving"
    DECLINING = "declining"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class OutcomeRecord:
    """Single recorded resonance outcome for analytics and audit."""

    agent_id: str
    outcome: str
    quality: float
    recorded_at: datetime
    resonance_id: str = ""
    intent_signal_hash: str = ""
    confidence: float = 0.0
    resonance_type: str = ""
    score_delta: float = 0.0
    new_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrendSnapshot:
    """Success-rate and quality trend over a sliding window."""

    direction: TrendDirection
    window_size: int
    recent_success_rate: float = 0.0
    prior_success_rate: float = 0.0
    recent_avg_quality: float = 0.0
    prior_avg_quality: float = 0.0


@dataclass
class AgentAnalytics:
    """Aggregate reputation analytics for an agent."""

    agent_id: str
    resonance_score: float
    visibility_multiplier: float
    total_resonances: int
    success_rate: float
    average_quality: float
    trend: TrendSnapshot
    recent_outcomes: list[OutcomeRecord] = field(default_factory=list)


@dataclass
class AgentReputation:
    """Public reputation snapshot for an agent on the Fabric."""

    agent_id: str
    agent_name: str
    resonance_score: float
    visibility_multiplier: float
    total_resonances: int = 0
    success_rate: float = 0.0
    average_quality: float = 0.0
    trend_direction: str = TrendDirection.INSUFFICIENT_DATA.value


class OutcomeHistoryStore(ABC):
    """Persistence for per-outcome records used in analytics."""

    @abstractmethod
    def record(self, record: OutcomeRecord) -> None:
        ...

    @abstractmethod
    def list_for_agent(self, agent_id: str, *, limit: int = 100) -> list[OutcomeRecord]:
        ...


class InMemoryOutcomeHistoryStore(OutcomeHistoryStore):
    """Ephemeral outcome history for tests."""

    def __init__(self) -> None:
        self._records: list[OutcomeRecord] = []

    def record(self, record: OutcomeRecord) -> None:
        self._records.append(record)

    def list_for_agent(self, agent_id: str, *, limit: int = 100) -> list[OutcomeRecord]:
        matches = [r for r in self._records if r.agent_id == agent_id]
        return matches[-limit:]


class SqliteOutcomeHistoryStore(OutcomeHistoryStore):
    """SQLite-backed outcome history (shared forge_resonance.db)."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path or SQLITE_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        SqliteScoreStore(str(self._db_path))  # ensure schema exists

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, record: OutcomeRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reputation_outcomes
                    (agent_id, resonance_id, intent_signal_hash, outcome, quality,
                     confidence, resonance_type, score_delta, new_score, metadata,
                     recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.agent_id,
                    record.resonance_id,
                    record.intent_signal_hash,
                    record.outcome,
                    record.quality,
                    record.confidence,
                    record.resonance_type,
                    record.score_delta,
                    record.new_score,
                    json.dumps(record.metadata),
                    record.recorded_at.isoformat(),
                ),
            )
            conn.commit()

    def list_for_agent(self, agent_id: str, *, limit: int = 100) -> list[OutcomeRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reputation_outcomes
                WHERE agent_id = ?
                ORDER BY recorded_at ASC
                LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        return [_row_to_outcome(row) for row in rows]


class NeonOutcomeHistoryStore(OutcomeHistoryStore):
    """Read/write outcome history via Neon resonance_events table."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or DATABASE_URL
        if not self._database_url:
            raise ValueError("DATABASE_URL required for NeonOutcomeHistoryStore")

    def _get_connection(self):
        import psycopg2

        return psycopg2.connect(self._database_url)

    def record(self, record: OutcomeRecord) -> None:
        # Written alongside score updates via ResonanceScorer.record_resonance_event.
        # This store is primarily for analytics reads; no-op on write to avoid dupes.
        logger.debug(
            "Neon outcome recorded via scorer event stream: agent=%s outcome=%s",
            record.agent_id,
            record.outcome,
        )

    def list_for_agent(self, agent_id: str, *, limit: int = 100) -> list[OutcomeRecord]:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT intent_signal_hash, resonance_quality, outcome,
                           score_delta, metadata, created_at
                    FROM resonance_events
                    WHERE agent_id = %s::uuid
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (agent_id, limit),
                )
                rows = cur.fetchall()
        records: list[OutcomeRecord] = []
        for row in rows:
            meta = row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}")
            records.append(
                OutcomeRecord(
                    agent_id=agent_id,
                    outcome=str(row[2]),
                    quality=float(row[1] or 0.0),
                    recorded_at=row[5],
                    intent_signal_hash=str(row[0] or ""),
                    confidence=float(meta.get("confidence", 0.0)),
                    resonance_type=str(meta.get("resonance_type", "")),
                    score_delta=float(row[3] or 0.0),
                    metadata=meta,
                )
            )
        return records


def _row_to_outcome(row: sqlite3.Row) -> OutcomeRecord:
    return OutcomeRecord(
        agent_id=row["agent_id"],
        outcome=row["outcome"],
        quality=float(row["quality"] or 0.0),
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        resonance_id=row["resonance_id"] or "",
        intent_signal_hash=row["intent_signal_hash"] or "",
        confidence=float(row["confidence"] or 0.0),
        resonance_type=row["resonance_type"] or "",
        score_delta=float(row["score_delta"] or 0.0),
        new_score=float(row["new_score"] or 0.0),
        metadata=json.loads(row["metadata"] or "{}"),
    )


def create_outcome_history_store() -> OutcomeHistoryStore:
    """Factory: Neon when reachable, else SQLite, else in-memory."""
    if DATABASE_URL:
        try:
            from core.memory import neon_is_reachable

            if neon_is_reachable():
                return NeonOutcomeHistoryStore()
        except (ValueError, ImportError) as exc:
            logger.warning("Neon outcome store unavailable: %s", exc)
    try:
        return SqliteOutcomeHistoryStore()
    except Exception as exc:
        logger.warning("SQLite outcome store unavailable: %s", exc)
    return InMemoryOutcomeHistoryStore()


def compute_success_rate(records: list[OutcomeRecord]) -> float:
    if not records:
        return 0.0
    successes = sum(1 for r in records if r.outcome in SUCCESS_OUTCOMES)
    return successes / len(records)


def compute_average_quality(records: list[OutcomeRecord]) -> float:
    if not records:
        return 0.0
    return sum(r.quality for r in records) / len(records)


def compute_trend(
    records: list[OutcomeRecord],
    *,
    window: int = 10,
) -> TrendSnapshot:
    """Compare recent half vs prior half of the window for trend direction."""
    if len(records) < 4:
        return TrendSnapshot(
            direction=TrendDirection.INSUFFICIENT_DATA,
            window_size=len(records),
        )

    windowed = records[-window:]
    mid = len(windowed) // 2
    prior = windowed[:mid]
    recent = windowed[mid:]

    prior_sr = compute_success_rate(prior)
    recent_sr = compute_success_rate(recent)
    prior_aq = compute_average_quality(prior)
    recent_aq = compute_average_quality(recent)

    sr_delta = recent_sr - prior_sr
    aq_delta = recent_aq - prior_aq
    combined = sr_delta * 0.6 + aq_delta * 0.4

    if combined > 0.05:
        direction = TrendDirection.IMPROVING
    elif combined < -0.05:
        direction = TrendDirection.DECLINING
    else:
        direction = TrendDirection.STABLE

    return TrendSnapshot(
        direction=direction,
        window_size=len(windowed),
        recent_success_rate=recent_sr,
        prior_success_rate=prior_sr,
        recent_avg_quality=recent_aq,
        prior_avg_quality=prior_aq,
    )


class ResonanceScoreManager:
    """
    Central manager for Resonance Score, outcome recording, and analytics.

    Wraps ``ResonanceScorer`` and an ``OutcomeHistoryStore``, providing a
    single API for the reflect step and future distribution flywheel.
    """

    def __init__(
        self,
        scorer: ResonanceScorer | None = None,
        history_store: OutcomeHistoryStore | None = None,
    ) -> None:
        self._scorer = scorer or create_scorer()
        self._history = history_store or create_outcome_history_store()

    @property
    def scorer(self) -> ResonanceScorer:
        return self._scorer

    @property
    def history_store(self) -> OutcomeHistoryStore:
        return self._history

    def get_score(self, agent_id: str) -> float:
        return self._scorer.get_score(agent_id)

    def get_visibility_multiplier(
        self,
        agent_id: str | None = None,
        *,
        score: float | None = None,
    ) -> float:
        """Return visibility weight (0.1 – 2.0) for score-based distribution."""
        resolved = score if score is not None else self.get_score(agent_id or "")
        return get_visibility_multiplier(resolved)

    def record_outcome(
        self,
        agent_id: str,
        outcome: str | OutcomeTier,
        *,
        quality: float = 0.0,
        metadata: dict[str, Any] | None = None,
        resonance_id: str = "",
        intent_signal_hash: str = "",
        confidence: float = 0.0,
        resonance_type: str = "",
    ) -> ScoreUpdate | None:
        """
        Record a resonance outcome, update score, and persist analytics.

        Returns ``ScoreUpdate`` when the outcome maps to a score tier; ``None``
        for skipped or unmapped outcomes.
        """
        tier = self._resolve_tier(outcome)
        if tier is None:
            logger.debug("Outcome '%s' not scored; skipping record", outcome)
            return None

        meta = dict(metadata or {})
        if confidence:
            meta.setdefault("confidence", confidence)
        if resonance_type:
            meta.setdefault("resonance_type", resonance_type)

        update = self._scorer.apply_outcome(
            agent_id,
            tier,
            quality=quality,
            reason=f"resonance_cycle:{tier.value}",
            resonance_id=resonance_id,
            intent_signal_hash=intent_signal_hash,
            metadata=meta,
        )

        record = OutcomeRecord(
            agent_id=agent_id,
            outcome=tier.value,
            quality=quality,
            recorded_at=update.timestamp,
            resonance_id=resonance_id or update.resonance_id,
            intent_signal_hash=intent_signal_hash,
            confidence=confidence or float(meta.get("confidence", 0.0)),
            resonance_type=resonance_type or str(meta.get("resonance_type", "")),
            score_delta=update.delta,
            new_score=update.new_score,
            metadata=meta,
        )
        self._history.record(record)
        return update

    def get_success_rate(self, agent_id: str, *, window: int = 50) -> float:
        records = self._history.list_for_agent(agent_id, limit=window)
        return compute_success_rate(records)

    def get_trend(self, agent_id: str, *, window: int = 10) -> TrendSnapshot:
        records = self._history.list_for_agent(agent_id, limit=window)
        return compute_trend(records, window=window)

    def get_analytics(self, agent_id: str, *, window: int = 50) -> AgentAnalytics:
        """Full analytics snapshot for an agent."""
        records = self._history.list_for_agent(agent_id, limit=window)
        score = self.get_score(agent_id)
        return AgentAnalytics(
            agent_id=agent_id,
            resonance_score=score,
            visibility_multiplier=self.get_visibility_multiplier(score=score),
            total_resonances=len(records),
            success_rate=compute_success_rate(records),
            average_quality=compute_average_quality(records),
            trend=compute_trend(records, window=min(10, window)),
            recent_outcomes=records[-5:],
        )

    @staticmethod
    def _resolve_tier(outcome: str | OutcomeTier) -> OutcomeTier | None:
        if isinstance(outcome, OutcomeTier):
            return outcome
        try:
            return OutcomeTier(str(outcome))
        except ValueError:
            return None


def create_score_manager(
    scorer: ResonanceScorer | None = None,
    history_store: OutcomeHistoryStore | None = None,
) -> ResonanceScoreManager:
    """Factory for ResonanceScoreManager with Neon → SQLite → in-memory chain."""
    resolved_scorer = scorer or create_scorer()
    if history_store is None and isinstance(resolved_scorer.store, InMemoryScoreStore):
        history_store = InMemoryOutcomeHistoryStore()
    return ResonanceScoreManager(
        scorer=resolved_scorer,
        history_store=history_store or create_outcome_history_store(),
    )


class ReputationLayer:
    """
    Fabric-wide reputation aggregation.

    Delegates to ``ResonanceScoreManager`` for scores, analytics, and ranking.
    Designed for replication to Cloudflare KV for decentralized edge lookups.
    """

    def __init__(self, manager: ResonanceScoreManager | None = None) -> None:
        self._manager = manager or create_score_manager()
        self._cf_kv_namespace = CF_REPUTATION_KV_NAMESPACE

    @property
    def score_manager(self) -> ResonanceScoreManager:
        return self._manager

    def get_reputation(self, agent_id: str, agent_name: str = "") -> AgentReputation:
        """Fetch current reputation snapshot for an agent."""
        analytics = self._manager.get_analytics(agent_id)
        return AgentReputation(
            agent_id=agent_id,
            agent_name=agent_name,
            resonance_score=analytics.resonance_score,
            visibility_multiplier=analytics.visibility_multiplier,
            total_resonances=analytics.total_resonances,
            success_rate=analytics.success_rate,
            average_quality=analytics.average_quality,
            trend_direction=analytics.trend.direction.value,
        )

    def rank_agents(
        self,
        agent_ids: list[str],
        *,
        min_visibility: float = 0.0,
    ) -> list[AgentReputation]:
        """
        Rank agents by Resonance Score for matching prioritization.

        Agents below ``min_visibility`` are excluded from active matching.
        """
        reputations = [self.get_reputation(aid) for aid in agent_ids]
        eligible = [
            r for r in reputations if r.visibility_multiplier >= min_visibility
        ]
        return sorted(eligible, key=lambda r: r.resonance_score, reverse=True)

    def sync_to_edge(self, update: ScoreUpdate) -> None:
        """
        Push score update to Cloudflare KV for edge reputation cache.

        Requires CF_REPUTATION_KV_NAMESPACE binding in production.
        """
        if not self._cf_kv_namespace:
            logger.debug("Cloudflare KV not configured; edge sync skipped")
            return
        logger.info(
            "Edge sync queued: agent=%s score=%.2f visibility=%.2f",
            update.agent_id,
            update.new_score,
            get_visibility_multiplier(update.new_score),
        )

    def fabric_health(self) -> dict[str, Any]:
        """Return aggregate Fabric health metrics."""
        store_type = type(self._manager.scorer.store).__name__
        history_type = type(self._manager.history_store).__name__
        return {
            "storage": "neon" if "Neon" in store_type else "sqlite" if "Sqlite" in store_type else "local",
            "score_store": store_type,
            "history_store": history_type,
            "edge_sync": bool(self._cf_kv_namespace),
            "score_range": [0.0, 100.0],
            "visibility_range": [0.1, 2.0],
        }