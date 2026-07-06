"""
Resonance Score engine for ForgeResonance.

The Resonance Score is the reputation primitive of the Fabric. Successful
resonances increase an agent's future visibility; poor performance reduces it.
This module owns score calculation, ledger recording, and hooks for the
future decentralized reputation layer (Cloudflare KV / edge consensus).
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from config import (
    DATABASE_URL,
    RESONANCE_SCORE_DEFAULT,
    RESONANCE_SCORE_MAX,
    RESONANCE_SCORE_MIN,
    SCORE_DELTA_FAILURE,
    SCORE_DELTA_PARTIAL,
    SCORE_DELTA_REJECTION,
    SCORE_DELTA_SUCCESS,
    SQLITE_PATH,
)
from reputation.multiplier import get_visibility_multiplier
from utils.logging import emit_axiom_event, setup_logging

logger = setup_logging("forge.scoring")


class OutcomeTier(str, Enum):
    """Discrete outcome tiers that drive score deltas."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    REJECTION = "rejection"


OUTCOME_DELTAS: dict[OutcomeTier, float] = {
    OutcomeTier.SUCCESS: SCORE_DELTA_SUCCESS,
    OutcomeTier.PARTIAL: SCORE_DELTA_PARTIAL,
    OutcomeTier.FAILURE: SCORE_DELTA_FAILURE,
    OutcomeTier.REJECTION: SCORE_DELTA_REJECTION,
}


@dataclass(frozen=True)
class ScoreUpdate:
    """Immutable record of a single score change."""

    agent_id: str
    previous_score: float
    new_score: float
    delta: float
    reason: str
    outcome: OutcomeTier
    resonance_id: str
    timestamp: datetime

    @property
    def visibility_multiplier(self) -> float:
        """Map score to a visibility multiplier for the reputation layer."""
        return get_visibility_multiplier(self.new_score)


class ScoreStore(ABC):
    """Abstract persistence for scores and ledger entries."""

    @abstractmethod
    def get_score(self, agent_id: str) -> float:
        ...

    @abstractmethod
    def set_score(self, agent_id: str, score: float) -> None:
        ...

    @abstractmethod
    def append_ledger(self, update: ScoreUpdate) -> None:
        ...

    @abstractmethod
    def record_resonance_event(
        self,
        agent_id: str,
        intent_signal_hash: str,
        quality: float,
        outcome: str,
        score_delta: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ...


class InMemoryScoreStore(ScoreStore):
    """Ephemeral score store for testing and offline agents."""

    def __init__(self) -> None:
        self._scores: dict[str, float] = {}
        self._ledger: list[ScoreUpdate] = []

    def get_score(self, agent_id: str) -> float:
        return self._scores.get(agent_id, RESONANCE_SCORE_DEFAULT)

    def set_score(self, agent_id: str, score: float) -> None:
        self._scores[agent_id] = score

    def append_ledger(self, update: ScoreUpdate) -> None:
        self._ledger.append(update)

    def record_resonance_event(
        self,
        agent_id: str,
        intent_signal_hash: str,
        quality: float,
        outcome: str,
        score_delta: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        logger.debug(
            "Resonance event recorded (in-memory): agent=%s outcome=%s",
            agent_id,
            outcome,
        )


class SqliteScoreStore(ScoreStore):
    """
    SQLite score store — local fallback when Neon is unavailable.

    Uses agent_reputation, reputation_ledger, and reputation_outcomes tables
    in the shared forge_resonance.db file.
    """

    def __init__(self, db_path: str | None = None) -> None:
        import sqlite3
        from pathlib import Path

        self._db_path = Path(db_path or SQLITE_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._sqlite3 = sqlite3
        self._init_schema()

    def _connect(self):
        conn = self._sqlite3.connect(str(self._db_path))
        conn.row_factory = self._sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_reputation (
                    agent_id TEXT PRIMARY KEY,
                    resonance_score REAL NOT NULL DEFAULT 50.0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reputation_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    delta REAL NOT NULL,
                    reason TEXT,
                    previous_score REAL NOT NULL,
                    new_score REAL NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reputation_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    resonance_id TEXT,
                    intent_signal_hash TEXT,
                    outcome TEXT NOT NULL,
                    quality REAL,
                    confidence REAL,
                    resonance_type TEXT,
                    score_delta REAL,
                    new_score REAL,
                    metadata TEXT DEFAULT '{}',
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resonance_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    intent_signal_hash TEXT,
                    resonance_quality REAL,
                    outcome TEXT NOT NULL,
                    score_delta REAL,
                    metadata TEXT DEFAULT '{}',
                    recorded_at TEXT NOT NULL
                );
                """
            )

    def get_score(self, agent_id: str) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT resonance_score FROM agent_reputation WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            if row is None:
                return RESONANCE_SCORE_DEFAULT
            return float(row["resonance_score"])

    def set_score(self, agent_id: str, score: float) -> None:
        clamped = max(RESONANCE_SCORE_MIN, min(RESONANCE_SCORE_MAX, score))
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_reputation (agent_id, resonance_score, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    resonance_score = excluded.resonance_score,
                    updated_at = excluded.updated_at
                """,
                (agent_id, clamped, now),
            )
            conn.commit()

    def append_ledger(self, update: ScoreUpdate) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reputation_ledger
                    (agent_id, delta, reason, previous_score, new_score, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    update.agent_id,
                    update.delta,
                    update.reason,
                    update.previous_score,
                    update.new_score,
                    update.timestamp.isoformat(),
                ),
            )
            conn.commit()

    def record_resonance_event(
        self,
        agent_id: str,
        intent_signal_hash: str,
        quality: float,
        outcome: str,
        score_delta: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO resonance_events
                    (agent_id, intent_signal_hash, resonance_quality, outcome,
                     score_delta, metadata, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    intent_signal_hash,
                    quality,
                    outcome,
                    score_delta,
                    json.dumps(metadata or {}),
                    now,
                ),
            )
            conn.commit()


class NeonScoreStore(ScoreStore):
    """
    Neon Postgres score store.

    Uses tables: agents (resonance_score), reputation_ledger, resonance_events.
    Schema provisioned via Neon MCP on project forge-resonance.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or DATABASE_URL
        if not self._database_url:
            raise ValueError("DATABASE_URL required for NeonScoreStore")

    def _get_connection(self):
        import psycopg2

        return psycopg2.connect(self._database_url)

    def get_score(self, agent_id: str) -> float:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT resonance_score FROM agents WHERE id = %s::uuid",
                    (agent_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return RESONANCE_SCORE_DEFAULT
                return float(row[0])

    def set_score(self, agent_id: str, score: float) -> None:
        clamped = max(RESONANCE_SCORE_MIN, min(RESONANCE_SCORE_MAX, score))
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agents SET resonance_score = %s, updated_at = NOW()
                    WHERE id = %s::uuid
                    """,
                    (clamped, agent_id),
                )
            conn.commit()

    def append_ledger(self, update: ScoreUpdate) -> None:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reputation_ledger
                        (agent_id, delta, reason, previous_score, new_score)
                    VALUES (%s::uuid, %s, %s, %s, %s)
                    """,
                    (
                        update.agent_id,
                        update.delta,
                        update.reason,
                        update.previous_score,
                        update.new_score,
                    ),
                )
            conn.commit()

    def record_resonance_event(
        self,
        agent_id: str,
        intent_signal_hash: str,
        quality: float,
        outcome: str,
        score_delta: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO resonance_events
                        (agent_id, intent_signal_hash, resonance_quality, outcome, score_delta, metadata)
                    VALUES (%s::uuid, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        agent_id,
                        intent_signal_hash,
                        quality,
                        outcome,
                        score_delta,
                        json.dumps(metadata or {}),
                    ),
                )
            conn.commit()


class ResonanceScorer:
    """
    Core scoring engine.

    Applies outcome-tier deltas, clamps to bounds, records ledger entries,
    and emits observability events. Designed for future edge replication
    via Cloudflare KV (see reputation/score_layer.py).
    """

    def __init__(self, store: ScoreStore | None = None) -> None:
        if store is not None:
            self._store = store
        elif DATABASE_URL:
            try:
                self._store = NeonScoreStore()
            except (ValueError, ImportError):
                self._store = InMemoryScoreStore()
        else:
            self._store = InMemoryScoreStore()

    @property
    def store(self) -> ScoreStore:
        return self._store

    def get_score(self, agent_id: str) -> float:
        return self._store.get_score(agent_id)

    def compute_delta(
        self,
        outcome: OutcomeTier,
        quality: float | None = None,
    ) -> float:
        """
        Compute score delta from outcome tier, optionally scaled by quality.

        Quality (0.0–1.0) acts as a multiplier on positive deltas only,
        rewarding high-quality resonances disproportionately.
        """
        base = OUTCOME_DELTAS[outcome]
        if quality is not None and base > 0:
            return base * max(0.0, min(1.0, quality))
        return base

    def apply_outcome(
        self,
        agent_id: str,
        outcome: OutcomeTier,
        *,
        quality: float | None = None,
        reason: str = "",
        resonance_id: str | None = None,
        intent_signal_hash: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ScoreUpdate:
        """Apply an outcome to an agent's Resonance Score and record it."""
        previous = self._store.get_score(agent_id)
        delta = self.compute_delta(outcome, quality)
        new_score = max(
            RESONANCE_SCORE_MIN,
            min(RESONANCE_SCORE_MAX, previous + delta),
        )
        actual_delta = new_score - previous

        self._store.set_score(agent_id, new_score)

        rid = resonance_id or str(uuid.uuid4())[:16]
        update = ScoreUpdate(
            agent_id=agent_id,
            previous_score=previous,
            new_score=new_score,
            delta=actual_delta,
            reason=reason or f"outcome:{outcome.value}",
            outcome=outcome,
            resonance_id=rid,
            timestamp=datetime.now(timezone.utc),
        )
        self._store.append_ledger(update)

        if intent_signal_hash:
            self._store.record_resonance_event(
                agent_id=agent_id,
                intent_signal_hash=intent_signal_hash,
                quality=quality or 0.0,
                outcome=outcome.value,
                score_delta=actual_delta,
                metadata=metadata,
            )

        logger.info(
            "Score update: agent=%s %s→%s (Δ%s) outcome=%s",
            agent_id,
            previous,
            new_score,
            actual_delta,
            outcome.value,
        )
        emit_axiom_event(
            "resonance_score_update",
            {
                "agent_id": agent_id,
                "previous_score": previous,
                "new_score": new_score,
                "delta": actual_delta,
                "outcome": outcome.value,
                "resonance_id": rid,
            },
        )
        return update

    def visibility_for(self, agent_id: str) -> float:
        """Return the visibility multiplier for an agent's current score."""
        return get_visibility_multiplier(self._store.get_score(agent_id))


def create_scorer(use_neon: bool = True) -> ResonanceScorer:
    """Factory for ResonanceScorer: Neon → SQLite → in-memory."""
    if use_neon and DATABASE_URL:
        try:
            from core.memory import neon_is_reachable

            if neon_is_reachable():
                return ResonanceScorer(NeonScoreStore())
        except (ValueError, ImportError) as exc:
            logger.warning("Neon score store unavailable: %s", exc)
    try:
        return ResonanceScorer(SqliteScoreStore())
    except Exception as exc:
        logger.warning("SQLite score store unavailable: %s", exc)
    logger.debug("Using InMemoryScoreStore for scoring")
    return ResonanceScorer(InMemoryScoreStore())