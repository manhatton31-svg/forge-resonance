"""
Tests for the Reputation / Resonance Score layer.

Run with: python -m pytest tests/test_reputation_layer.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.scoring import InMemoryScoreStore, OutcomeTier, ResonanceScorer, SqliteScoreStore
from reputation.multiplier import get_visibility_multiplier
from reputation.score_layer import (
    InMemoryOutcomeHistoryStore,
    OutcomeRecord,
    ReputationLayer,
    ResonanceScoreManager,
    SqliteOutcomeHistoryStore,
    TrendDirection,
    compute_trend,
    create_score_manager,
)


@pytest.fixture
def memory_manager() -> ResonanceScoreManager:
    scorer = ResonanceScorer(InMemoryScoreStore())
    history = InMemoryOutcomeHistoryStore()
    return ResonanceScoreManager(scorer=scorer, history_store=history)


@pytest.fixture
def sqlite_manager(tmp_path: Path) -> ResonanceScoreManager:
    db = tmp_path / "reputation.db"
    scorer = ResonanceScorer(SqliteScoreStore(str(db)))
    history = SqliteOutcomeHistoryStore(db)
    return ResonanceScoreManager(scorer=scorer, history_store=history)


class TestVisibilityMultiplier:
    def test_floor_at_min_score(self):
        assert get_visibility_multiplier(0.0) == pytest.approx(0.1)

    def test_ceiling_at_max_score(self):
        assert get_visibility_multiplier(100.0) == pytest.approx(2.0)

    def test_midpoint_score(self):
        assert get_visibility_multiplier(50.0) == pytest.approx(1.05)

    def test_clamps_out_of_range(self):
        assert get_visibility_multiplier(150.0) == pytest.approx(2.0)
        assert get_visibility_multiplier(-10.0) == pytest.approx(0.1)

    def test_manager_delegates_visibility(self, memory_manager: ResonanceScoreManager):
        memory_manager.scorer.store.set_score("a1", 75.0)
        assert memory_manager.get_visibility_multiplier("a1") == pytest.approx(
            get_visibility_multiplier(75.0)
        )


class TestRecordOutcome:
    def test_records_success_and_updates_score(
        self, memory_manager: ResonanceScoreManager
    ):
        update = memory_manager.record_outcome(
            "agent-1",
            OutcomeTier.SUCCESS,
            quality=0.9,
            metadata={"resonance_type": "offer_framed", "offer_id": "trial-1"},
            resonance_id="r1",
            intent_signal_hash="abc",
            confidence=0.85,
            resonance_type="offer_framed",
        )
        assert update is not None
        assert update.new_score > 50.0
        assert memory_manager.get_score("agent-1") == update.new_score

    def test_persists_outcome_to_history(
        self, memory_manager: ResonanceScoreManager
    ):
        memory_manager.record_outcome(
            "agent-2",
            "success",
            quality=0.8,
            resonance_id="r2",
            confidence=0.7,
            resonance_type="educational",
        )
        records = memory_manager.history_store.list_for_agent("agent-2")
        assert len(records) == 1
        assert records[0].outcome == "success"
        assert records[0].quality == pytest.approx(0.8)
        assert records[0].confidence == pytest.approx(0.7)
        assert records[0].resonance_type == "educational"

    def test_skipped_outcome_not_recorded(
        self, memory_manager: ResonanceScoreManager
    ):
        result = memory_manager.record_outcome("agent-3", "skipped", quality=0.0)
        assert result is None
        assert memory_manager.get_score("agent-3") == 50.0
        assert not memory_manager.history_store.list_for_agent("agent-3")

    def test_sqlite_persistence(self, sqlite_manager: ResonanceScoreManager):
        sqlite_manager.record_outcome(
            "sqlite-agent",
            OutcomeTier.PARTIAL,
            quality=0.55,
            resonance_id="sq1",
            confidence=0.6,
        )
        score = sqlite_manager.get_score("sqlite-agent")
        assert score > 50.0
        records = sqlite_manager.history_store.list_for_agent("sqlite-agent")
        assert len(records) == 1
        assert records[0].new_score == pytest.approx(score)


class TestAnalytics:
    def _seed_outcomes(self, manager: ResonanceScoreManager, agent_id: str) -> None:
        outcomes = [
            ("success", 0.9),
            ("success", 0.85),
            ("partial", 0.5),
            ("failure", 0.2),
            ("success", 0.95),
            ("success", 0.88),
        ]
        for i, (outcome, quality) in enumerate(outcomes):
            manager.record_outcome(
                agent_id,
                outcome,
                quality=quality,
                resonance_id=f"r{i}",
                confidence=0.8,
            )

    def test_success_rate(self, memory_manager: ResonanceScoreManager):
        self._seed_outcomes(memory_manager, "stats-1")
        rate = memory_manager.get_success_rate("stats-1")
        # success + partial count as positive outcomes (5 of 6)
        assert rate == pytest.approx(5 / 6)

    def test_analytics_snapshot(self, memory_manager: ResonanceScoreManager):
        self._seed_outcomes(memory_manager, "stats-2")
        analytics = memory_manager.get_analytics("stats-2")
        assert analytics.total_resonances == 6
        assert analytics.success_rate == pytest.approx(5 / 6)
        assert analytics.average_quality > 0
        assert 0.1 <= analytics.visibility_multiplier <= 2.0
        assert len(analytics.recent_outcomes) <= 5

    def test_improving_trend(self):
        records = [
            OutcomeRecord("a", "failure", 0.2, datetime.now(timezone.utc)),
            OutcomeRecord("a", "failure", 0.3, datetime.now(timezone.utc)),
            OutcomeRecord("a", "success", 0.9, datetime.now(timezone.utc)),
            OutcomeRecord("a", "success", 0.95, datetime.now(timezone.utc)),
        ]
        trend = compute_trend(records, window=4)
        assert trend.direction == TrendDirection.IMPROVING

    def test_insufficient_data_trend(self, memory_manager: ResonanceScoreManager):
        memory_manager.record_outcome("a", "success", quality=0.8)
        trend = memory_manager.get_trend("a")
        assert trend.direction == TrendDirection.INSUFFICIENT_DATA


class TestReputationLayer:
    def test_get_reputation(self, memory_manager: ResonanceScoreManager):
        layer = ReputationLayer(memory_manager)
        memory_manager.record_outcome(
            "rank-1", "success", quality=0.9, resonance_id="r1"
        )
        rep = layer.get_reputation("rank-1", agent_name="Alpha")
        assert rep.agent_name == "Alpha"
        assert rep.total_resonances == 1
        assert rep.success_rate == pytest.approx(1.0)

    def test_rank_agents_by_score(self, memory_manager: ResonanceScoreManager):
        layer = ReputationLayer(memory_manager)
        memory_manager.record_outcome("high", OutcomeTier.SUCCESS, quality=1.0)
        memory_manager.record_outcome("low", OutcomeTier.FAILURE, quality=0.1)
        ranked = layer.rank_agents(["low", "high"])
        assert ranked[0].agent_id == "high"
        assert ranked[1].agent_id == "low"

    def test_rank_filters_low_visibility(self, memory_manager: ResonanceScoreManager):
        layer = ReputationLayer(memory_manager)
        memory_manager.scorer.store.set_score("hidden", 5.0)
        memory_manager.scorer.store.set_score("visible", 80.0)
        ranked = layer.rank_agents(["hidden", "visible"], min_visibility=0.5)
        assert len(ranked) == 1
        assert ranked[0].agent_id == "visible"

    def test_fabric_health(self, memory_manager: ResonanceScoreManager):
        layer = ReputationLayer(memory_manager)
        health = layer.fabric_health()
        assert health["score_range"] == [0.0, 100.0]
        assert health["visibility_range"] == [0.1, 2.0]


@pytest.fixture
def temp_data_dir(tmp_path: Path, monkeypatch):
    agent_dir = tmp_path / "agents"
    agent_dir.mkdir()
    monkeypatch.setattr("config.AGENT_DATA_DIR", agent_dir)
    monkeypatch.setattr("core.memory.AGENT_DATA_DIR", agent_dir)
    monkeypatch.setattr("core.state.AGENT_DATA_DIR", agent_dir)
    return agent_dir


class TestAgentIntegration:
    def test_agent_get_reputation_stats(self, temp_data_dir):
        from core.memory import FileMemoryStore
        from core.resonance_agent import ResonanceAgent, ResonanceOutcome
        from core.scoring import InMemoryScoreStore, ResonanceScorer
        from core.state import StateManager
        from harvesting.intent_harvester import EmbeddingIntentHarvester
        from generation.resonance_engine import ResonanceEngine
        from injection.value_injector import ValueInjector
        from integration.arcly_handoff import ArclyHandoff

        scorer = ResonanceScorer(InMemoryScoreStore())
        manager = create_score_manager(scorer=scorer)
        agent = ResonanceAgent(
            name="rep-agent",
            goals=["test reputation"],
            memory_store=FileMemoryStore(base_dir=temp_data_dir),
            score_manager=manager,
            state_manager=StateManager(base_dir=temp_data_dir / "state"),
            intent_harvester=EmbeddingIntentHarvester(),
            resonance_engine=ResonanceEngine(),
            value_injector=ValueInjector(echo=False),
            arcly_handoff=ArclyHandoff(force_dry_run=True),
        )
        agent.submit_mock_signal(
            {"topic": "pricing", "matched_intent": "purchase_intent"},
            confidence=0.85,
        )
        outcome = agent.run_once()
        assert outcome in (ResonanceOutcome.SUCCESS, ResonanceOutcome.PARTIAL)

        stats = agent.get_reputation_stats()
        assert stats.total_resonances == 1
        assert stats.success_rate > 0
        assert stats.resonance_score > 50.0
        assert stats.visibility_multiplier > 0.1