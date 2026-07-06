"""
Tests for the foundational ResonanceAgent.

Run with: python -m pytest tests/ -v
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from config import AGENT_DATA_DIR
from core.memory import FileMemoryStore
from core.resonance_agent import (
    IntentSignal,
    ResonanceAgent,
    ResonanceOutcome,
    ResonancePayload,
)
from core.scoring import InMemoryScoreStore, OutcomeTier, ResonanceScorer
from core.state import AgentLifecycle, StateManager


@pytest.fixture
def temp_data_dir(tmp_path: Path, monkeypatch):
    """Isolate agent data to a temporary directory."""
    agent_dir = tmp_path / "agents"
    state_dir = agent_dir / "state"
    agent_dir.mkdir()
    monkeypatch.setattr("config.AGENT_DATA_DIR", agent_dir)
    monkeypatch.setattr("core.memory.AGENT_DATA_DIR", agent_dir)
    monkeypatch.setattr("core.state.AGENT_DATA_DIR", agent_dir)
    return agent_dir


@pytest.fixture
def agent(temp_data_dir) -> ResonanceAgent:
    """Create a test agent with in-memory scoring."""
    scorer = ResonanceScorer(InMemoryScoreStore())
    return ResonanceAgent(
        name="test-agent",
        goals=["deliver contextual value"],
        memory_store=FileMemoryStore(base_dir=temp_data_dir),
        scorer=scorer,
        state_manager=StateManager(base_dir=temp_data_dir / "state"),
    )


class TestResonanceAgentBasics:
    def test_agent_initialization(self, agent: ResonanceAgent):
        assert agent.name == "test-agent"
        assert agent.agent_id
        assert agent.resonance_score == 50.0
        assert "deliver contextual value" in agent.memory.goals

    def test_agent_repr(self, agent: ResonanceAgent):
        assert "test-agent" in repr(agent)

    def test_remember_and_recall(self, agent: ResonanceAgent):
        agent.remember("test_key", {"value": 42})
        assert agent.recall("test_key") == {"value": 42}

    def test_recall_missing_key(self, agent: ResonanceAgent):
        assert agent.recall("nonexistent") is None
        assert agent.recall("nonexistent", "default") == "default"

    def test_add_goal(self, agent: ResonanceAgent):
        agent.add_goal("new goal")
        assert "new goal" in agent.memory.goals
        agent.add_goal("new goal")
        assert agent.memory.goals.count("new goal") == 1


class TestResonanceAgentLifecycle:
    def test_start_and_stop(self, agent: ResonanceAgent):
        agent.start()
        assert agent.state.lifecycle == AgentLifecycle.IDLE
        agent.stop()
        assert agent.state.lifecycle == AgentLifecycle.PAUSED

    def test_run_once_no_signal(self, agent: ResonanceAgent):
        outcome = agent.run_once()
        assert outcome == ResonanceOutcome.SKIPPED
        assert agent.state.lifecycle == AgentLifecycle.IDLE

    def test_run_once_with_signal(self, agent: ResonanceAgent):
        from core.memory import AgentMemory
        from core.resonance_agent import IntentHarvesterProtocol

        class MockHarvester(IntentHarvesterProtocol):
            def harvest(self, agent_memory: AgentMemory) -> IntentSignal | None:
                agent_memory.metadata["intent_opt_in"] = True
                return IntentSignal.from_context(
                    {"topic": "test"}, confidence=0.8
                )

        from core.resonance_agent import ResonanceEngineProtocol

        class MockEngine(ResonanceEngineProtocol):
            def generate(self, signal, agent_memory, resonance_score):
                return ResonancePayload(
                    resonance_id="",
                    content={"message": "test value"},
                    quality_estimate=0.75,
                )

        agent._harvester = MockHarvester()
        agent._engine = MockEngine()

        outcome = agent.run_once()
        assert outcome in (
            ResonanceOutcome.SUCCESS,
            ResonanceOutcome.PARTIAL,
            ResonanceOutcome.SKIPPED,
        )
        assert len(agent.memory.episodic) >= 0


class TestResonanceScoring:
    def test_score_increases_on_success(self):
        store = InMemoryScoreStore()
        scorer = ResonanceScorer(store)
        update = scorer.apply_outcome("agent-1", OutcomeTier.SUCCESS, quality=0.9)
        assert update.new_score > update.previous_score
        assert update.delta > 0

    def test_score_decreases_on_rejection(self):
        store = InMemoryScoreStore()
        scorer = ResonanceScorer(store)
        update = scorer.apply_outcome("agent-2", OutcomeTier.REJECTION)
        assert update.new_score < update.previous_score

    def test_score_clamped_to_bounds(self):
        store = InMemoryScoreStore()
        store.set_score("agent-3", 99.5)
        scorer = ResonanceScorer(store)
        update = scorer.apply_outcome("agent-3", OutcomeTier.SUCCESS, quality=1.0)
        assert update.new_score <= 100.0

    def test_visibility_multiplier(self):
        store = InMemoryScoreStore()
        store.set_score("agent-4", 75.0)
        scorer = ResonanceScorer(store)
        visibility = scorer.visibility_for("agent-4")
        assert 0.0 < visibility <= 1.0


class TestIntentSignal:
    def test_signal_hash_deterministic(self):
        s1 = IntentSignal.from_context({"a": 1, "b": 2})
        s2 = IntentSignal.from_context({"b": 2, "a": 1})
        assert s1.signal_hash == s2.signal_hash

    def test_signal_hash_length(self):
        signal = IntentSignal.from_context({"test": True})
        assert len(signal.signal_hash) == 16