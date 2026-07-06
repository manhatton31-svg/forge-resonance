"""
Tests for the ForgeResonance demo bootstrap layer.

Run with: python -m pytest tests/test_demo.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.resonance_agent import ResonanceOutcome
from demo.bootstrap import (
    MULTI_AGENT_SCENARIOS,
    SINGLE_AGENT_INTENTS,
    create_demo_agent,
    create_demo_stack,
    run_agent_cycles,
    run_multi_agent_ranking_demo,
    run_single_agent_demo,
)
from reputation.score_layer import AgentReputation


@pytest.fixture
def demo_dir(tmp_path: Path, monkeypatch):
    """Isolate demo data and agent paths."""
    data = tmp_path / "demo"
    data.mkdir()
    agent_dir = data / "agents"
    agent_dir.mkdir()
    monkeypatch.setattr("config.AGENT_DATA_DIR", agent_dir)
    monkeypatch.setattr("core.memory.AGENT_DATA_DIR", agent_dir)
    monkeypatch.setattr("core.state.AGENT_DATA_DIR", data / "state")
    return data


class TestDemoBootstrap:
    def test_single_agent_demo_runs_cycles(self, demo_dir: Path):
        result = run_single_agent_demo(
            data_dir=demo_dir,
            intents=list(SINGLE_AGENT_INTENTS[:2]),
            print_fn=lambda _: None,
            verbose=False,
        )
        assert result.agent_name == "atlas-demo"
        assert len(result.cycles) == 2
        assert result.analytics is not None
        assert result.analytics.total_resonances >= 1

    def test_at_least_one_cycle_produces_value(self, demo_dir: Path):
        result = run_single_agent_demo(
            data_dir=demo_dir,
            intents=[SINGLE_AGENT_INTENTS[0]],
            print_fn=lambda _: None,
            verbose=False,
        )
        non_skipped = [c for c in result.cycles if not c.skipped]
        assert non_skipped, "Expected at least one cycle above resonance threshold"
        assert non_skipped[0].formatted_message
        assert non_skipped[0].outcome in ("success", "partial")

    def test_multi_agent_ranking_orders_by_weight(self, demo_dir: Path):
        ranked = run_multi_agent_ranking_demo(
            data_dir=demo_dir,
            print_fn=lambda _: None,
            verbose=False,
        )
        assert len(ranked) == 3
        assert all(isinstance(r, AgentReputation) for r in ranked)
        assert ranked[0].rank == 1
        assert ranked[0].selection_weight >= ranked[-1].selection_weight

    def test_atlas_ranks_first_with_more_cycles(self, demo_dir: Path):
        """Atlas runs 4 intents vs 2 and 1 — should lead the ranking."""
        ranked = run_multi_agent_ranking_demo(
            data_dir=demo_dir,
            print_fn=lambda _: None,
            verbose=False,
        )
        top_name = ranked[0].agent_name
        assert top_name == "atlas-analytics"
        assert len(MULTI_AGENT_SCENARIOS["atlas-analytics"]) > len(
            MULTI_AGENT_SCENARIOS["echo-support"]
        )

    def test_create_demo_agent_wired(self, demo_dir: Path):
        manager, _ = create_demo_stack()
        agent = create_demo_agent(
            "test-agent",
            ["demo goal"],
            data_dir=demo_dir,
            score_manager=manager,
        )
        assert agent.name == "test-agent"
        assert agent.resonance_score == 50.0

    def test_run_agent_cycles_skipped_handled(self, demo_dir: Path):
        manager, _ = create_demo_stack()
        agent = create_demo_agent(
            "skip-test",
            ["goal"],
            data_dir=demo_dir,
            score_manager=manager,
        )
        result = run_agent_cycles(
            agent,
            ["hello"],
            print_fn=lambda _: None,
            verbose=False,
        )
        assert len(result.cycles) == 1
        assert result.cycles[0].outcome == ResonanceOutcome.SKIPPED.value
        assert result.cycles[0].skipped is True