"""
Tests for Fabric routing, registry, and swarm coordination.

Run with: python -m pytest tests/test_fabric_routing.py -v
"""

from __future__ import annotations

import pytest

from agents.registry import AgentRegistry, RegisteredAgent
from config import EdgeReputationConfig
from core.resonance_agent import IntentSignal
from core.scoring import InMemoryScoreStore, OutcomeTier, ResonanceScorer
from fabric.capabilities import capability_score_for_agent
from fabric.router import IntentRouter
from core.resonance_agent import ResonanceOutcome
import time

from fabric.swarm import (
    AgentFailureKind,
    ConsensusStrategy,
    SwarmCoordinator,
    SwarmStrategy,
)
from reputation.edge_kv import CloudflareKVClient
from reputation.score_layer import (
    InMemoryOutcomeHistoryStore,
    ResonanceScoreManager,
    ReputationLayer,
)


def _enabled_kv_config() -> EdgeReputationConfig:
    return EdgeReputationConfig(
        enabled=True,
        api_token="test-token",
        account_id="acct-123",
        namespace_id="ns-456",
    )


class MockKVStore:
    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        body: bytes | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, bytes]:
        if method == "GET" and "/values/" in url:
            key = url.rsplit("/values/", 1)[-1]
            return (200, self._data[key]) if key in self._data else (404, b"")
        if method == "PUT" and "/values/" in url:
            key = url.rsplit("/values/", 1)[-1]
            self._data[key] = body or b""
            return 200, b""
        if method == "GET" and url.endswith("/namespaces/ns-456"):
            return 200, b"{}"
        return 404, b""


@pytest.fixture
def registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(
        RegisteredAgent(
            agent_id="atlas",
            name="atlas-analytics",
            goals=["maximize analytics conversion", "compare BI tools"],
            specialties=["commercial", "analytics", "purchase"],
        )
    )
    reg.register(
        RegisteredAgent(
            agent_id="nova",
            name="nova-research",
            goals=["educate buyers during research phase"],
            specialties=["research", "education"],
        )
    )
    reg.register(
        RegisteredAgent(
            agent_id="echo",
            name="echo-support",
            goals=["resolve billing issues quickly"],
            specialties=["support", "billing"],
        )
    )
    return reg


@pytest.fixture
def reputation_layer() -> ReputationLayer:
    manager = ResonanceScoreManager(
        scorer=ResonanceScorer(InMemoryScoreStore()),
        history_store=InMemoryOutcomeHistoryStore(),
    )
    return ReputationLayer(manager)


@pytest.fixture
def router(registry: AgentRegistry, reputation_layer: ReputationLayer) -> IntentRouter:
    return IntentRouter(registry, reputation_layer)


def _purchase_signal() -> IntentSignal:
    return IntentSignal.from_context(
        {
            "matched_intent": "purchase_intent",
            "topic": "analytics pricing",
            "text": "I want to buy analytics software",
        },
        confidence=0.85,
    )


def _research_signal() -> IntentSignal:
    return IntentSignal.from_context(
        {
            "matched_intent": "research_intent",
            "topic": "project management overview",
        },
        confidence=0.8,
    )


class TestAgentRegistry:
    def test_register_and_query_specialty(self, registry: AgentRegistry):
        matches = registry.query_by_specialty("analytics")
        assert len(matches) == 1
        assert matches[0].name == "atlas-analytics"

    def test_list_available_respects_load(self, registry: AgentRegistry):
        registry.increment_load("atlas", 10)
        available = registry.list_available()
        assert all(a.agent_id != "atlas" for a in available)

    def test_capability_score_commercial_agent(self, registry: AgentRegistry):
        atlas = registry.get("atlas")
        assert atlas is not None
        score = capability_score_for_agent(atlas, "purchase_intent")
        assert score > 0.5


class TestIntentRouter:
    def test_routes_purchase_to_commercial_agent(
        self, router: IntentRouter, reputation_layer: ReputationLayer
    ):
        reputation_layer.score_manager.record_outcome(
            "nova", OutcomeTier.SUCCESS, quality=0.95
        )
        results = router.route(_purchase_signal(), top_n=1)
        assert len(results) == 1
        assert results[0].agent_id == "atlas"
        assert results[0].capability_score > 0.4

    def test_routes_research_to_research_agent(self, router: IntentRouter):
        results = router.route(_research_signal(), top_n=1)
        assert results[0].agent_id == "nova"

    def test_top_n_returns_multiple(self, router: IntentRouter):
        results = router.route(_purchase_signal(), top_n=3)
        assert len(results) == 3
        assert results[0].rank == 1

    def test_edge_kv_boosts_capable_agent(self, registry: AgentRegistry):
        store = MockKVStore()
        kv = CloudflareKVClient(
            config=_enabled_kv_config(),
            request_fn=store.request,
        )
        manager = ResonanceScoreManager(
            scorer=ResonanceScorer(InMemoryScoreStore()),
            history_store=InMemoryOutcomeHistoryStore(),
            edge_kv=kv,
        )
        layer = ReputationLayer(manager)
        layer.score_manager.record_outcome(
            "atlas", OutcomeTier.SUCCESS, quality=0.9
        )
        kv.sync_score("nova", 88.0, 1.76)
        router = IntentRouter(registry, layer)
        results = router.route(_research_signal(), top_n=1, use_edge_data=True)
        assert results[0].agent_id == "nova"
        assert results[0].score_source in ("edge", "edge_fallback", "blended")


class TestSwarmCoordinator:
    def test_best_single_strategy(self, registry: AgentRegistry, reputation_layer: ReputationLayer):
        swarm = SwarmCoordinator(registry, reputation_layer)
        result = swarm.dispatch(
            _purchase_signal(),
            strategy=SwarmStrategy.BEST_SINGLE,
            submit_intent=False,
        )
        assert len(result.assignments) == 1
        assert len(result.dispatched_agent_ids) == 1
        assert registry.get("atlas").current_load == 1

    def test_broadcast_top_three(self, registry: AgentRegistry, reputation_layer: ReputationLayer):
        swarm = SwarmCoordinator(registry, reputation_layer)
        result = swarm.dispatch(
            _purchase_signal(),
            strategy=SwarmStrategy.BROADCAST_TOP_N,
            top_n=3,
            submit_intent=False,
        )
        assert len(result.assignments) == 3
        assert result.strategy == SwarmStrategy.BROADCAST_TOP_N

    def test_release_load(self, registry: AgentRegistry, reputation_layer: ReputationLayer):
        swarm = SwarmCoordinator(registry, reputation_layer)
        swarm.dispatch(_purchase_signal(), submit_intent=False)
        swarm.release_load("atlas")
        assert registry.get("atlas").current_load == 0


class TestSwarmExecution:
    def test_execute_unbound_agent_records_failure(
        self, registry: AgentRegistry, reputation_layer: ReputationLayer
    ):
        swarm = SwarmCoordinator(registry, reputation_layer)
        before = reputation_layer.score_manager.get_score("atlas")
        result = swarm.execute(_purchase_signal())
        assert len(result.agent_results) == 1
        agent_result = result.agent_results[0]
        assert agent_result.error == "agent not bound to coordinator"
        assert agent_result.outcome == ResonanceOutcome.FAILURE
        after = reputation_layer.score_manager.get_score("atlas")
        assert after < before
        assert registry.get("atlas").current_load == 0

    def test_execute_best_single_with_demo_agent(self, tmp_path):
        from demo.bootstrap import create_demo_agent, create_demo_stack

        base = tmp_path / "demo"
        manager, reputation = create_demo_stack(data_dir=base)
        registry = AgentRegistry()
        agent = create_demo_agent(
            "atlas-analytics",
            ["maximize analytics conversion"],
            data_dir=base,
            score_manager=manager,
        )
        registry.register(
            RegisteredAgent(
                agent_id=agent.agent_id,
                name=agent.name,
                goals=["maximize analytics conversion"],
                specialties=["commercial", "analytics", "purchase"],
            )
        )
        swarm = SwarmCoordinator(registry, reputation)
        swarm.bind_agent(agent)

        signal = IntentSignal.from_context(
            {
                "matched_intent": "purchase_intent",
                "topic": "analytics pricing",
            },
            confidence=0.85,
        )
        result = swarm.execute(signal)
        assert len(result.agent_results) == 1
        agent_result = result.agent_results[0]
        assert agent_result.outcome in (
            ResonanceOutcome.SUCCESS,
            ResonanceOutcome.PARTIAL,
        )
        assert result.best_result is not None
        assert result.swarm_quality > 0.0
        assert result.swarm_confidence > 0.0
        assert manager.get_score(agent.agent_id) != 50.0

    def test_execute_broadcast_aggregates_consensus(self, tmp_path):
        from demo.bootstrap import create_demo_agent, create_demo_stack

        base = tmp_path / "demo"
        manager, reputation = create_demo_stack(data_dir=base)
        registry = AgentRegistry()
        specs = [
            (
                "atlas-analytics",
                ["maximize analytics conversion"],
                ["commercial", "analytics", "purchase"],
            ),
            (
                "nova-research",
                ["educate buyers during research phase"],
                ["research", "education"],
            ),
            (
                "echo-support",
                ["resolve billing issues quickly"],
                ["support", "billing"],
            ),
        ]
        agents = []
        for name, goals, specialties in specs:
            agent = create_demo_agent(name, goals, data_dir=base, score_manager=manager)
            agents.append(agent)
            registry.register(
                RegisteredAgent(
                    agent_id=agent.agent_id,
                    name=agent.name,
                    goals=goals,
                    specialties=specialties,
                )
            )
        swarm = SwarmCoordinator(registry, reputation)
        swarm.bind_agents(agents)

        result = swarm.execute(
            _purchase_signal(),
            strategy=SwarmStrategy.BROADCAST_TOP_N,
            top_n=3,
        )
        assert len(result.agent_results) == 3
        assert result.consensus_outcome is not None
        assert result.success_count >= 1
        assert all(registry.get(a.agent_id).current_load == 0 for a in agents)

    def test_swarm_bonus_adjusts_reputation(self, registry: AgentRegistry, reputation_layer: ReputationLayer):
        reputation_layer.score_manager.record_outcome(
            "atlas", OutcomeTier.SUCCESS, quality=0.95
        )
        score_before_bonus = reputation_layer.score_manager.get_score("atlas")

        class _StubAgent:
            agent_id = "atlas"
            name = "atlas-analytics"

            def process_intent(self, signal):
                return ResonanceOutcome.SUCCESS

            def last_quality_estimate(self):
                return 0.9

            def last_formatted_result(self):
                return "stub result"

        swarm = SwarmCoordinator(registry, reputation_layer)
        swarm.bind_agent(_StubAgent())  # type: ignore[arg-type]
        result = swarm.execute(
            _purchase_signal(),
            apply_swarm_bonus=True,
        )
        assert result.swarm_quality >= 0.75
        score_after_bonus = reputation_layer.score_manager.get_score("atlas")
        assert score_after_bonus > score_before_bonus


class TestSwarmReliability:
    def test_agent_timeout_isolated(
        self, registry: AgentRegistry, reputation_layer: ReputationLayer
    ):
        class _SlowAgent:
            agent_id = "atlas"
            name = "atlas-analytics"

            def process_intent(self, signal):
                time.sleep(0.3)
                return ResonanceOutcome.SUCCESS

            def last_quality_estimate(self):
                return 0.8

            def last_formatted_result(self):
                return "slow"

        swarm = SwarmCoordinator(registry, reputation_layer)
        swarm.bind_agent(_SlowAgent())  # type: ignore[arg-type]
        result = swarm.execute(_purchase_signal(), timeout_s=0.05)

        agent_result = result.agent_results[0]
        assert agent_result.timed_out
        assert agent_result.failure_kind == AgentFailureKind.TIMEOUT
        assert result.metrics is not None
        assert result.metrics.timeout_count == 1
        assert result.best_result is None
        assert registry.get("atlas").current_load == 0

    def test_partial_failure_does_not_crash_swarm(
        self, registry: AgentRegistry, reputation_layer: ReputationLayer
    ):
        class _GoodAgent:
            agent_id = "atlas"
            name = "atlas-analytics"

            def process_intent(self, signal):
                return ResonanceOutcome.SUCCESS

            def last_quality_estimate(self):
                return 0.85

            def last_formatted_result(self):
                return "ok"

        class _BadAgent:
            agent_id = "nova"
            name = "nova-research"

            def process_intent(self, signal):
                raise RuntimeError("agent crashed")

            def last_quality_estimate(self):
                return 0.0

            def last_formatted_result(self):
                return ""

        swarm = SwarmCoordinator(registry, reputation_layer)
        swarm.bind_agent(_GoodAgent())  # type: ignore[arg-type]
        swarm.bind_agent(_BadAgent())  # type: ignore[arg-type]

        result = swarm.execute(
            _purchase_signal(),
            strategy=SwarmStrategy.BROADCAST_TOP_N,
            top_n=2,
        )
        assert len(result.agent_results) == 2
        assert result.success_count == 1
        assert result.metrics is not None
        assert result.metrics.exception_count == 1
        assert result.best_result is not None
        assert result.best_result.agent_id == "atlas"

    def test_quality_weighted_consensus_prefers_high_quality(
        self, registry: AgentRegistry, reputation_layer: ReputationLayer
    ):
        class _OutcomeAgent:
            def __init__(
                self,
                agent_id: str,
                name: str,
                outcome: ResonanceOutcome,
                quality: float,
            ) -> None:
                self.agent_id = agent_id
                self.name = name
                self._outcome = outcome
                self._quality = quality

            def process_intent(self, signal):
                return self._outcome

            def last_quality_estimate(self):
                return self._quality

            def last_formatted_result(self):
                return self._outcome.value

        swarm = SwarmCoordinator(registry, reputation_layer)
        swarm.bind_agent(
            _OutcomeAgent("atlas", "atlas-analytics", ResonanceOutcome.SUCCESS, 0.1)
        )  # type: ignore[arg-type]
        swarm.bind_agent(
            _OutcomeAgent("nova", "nova-research", ResonanceOutcome.SUCCESS, 0.1)
        )  # type: ignore[arg-type]
        swarm.bind_agent(
            _OutcomeAgent("echo", "echo-support", ResonanceOutcome.PARTIAL, 0.95)
        )  # type: ignore[arg-type]

        majority = swarm.execute(
            _purchase_signal(),
            strategy=SwarmStrategy.BROADCAST_TOP_N,
            top_n=3,
            consensus_strategy=ConsensusStrategy.MAJORITY,
        )
        weighted = swarm.execute(
            _purchase_signal(),
            strategy=SwarmStrategy.BROADCAST_TOP_N,
            top_n=3,
            consensus_strategy=ConsensusStrategy.QUALITY_WEIGHTED,
        )

        assert majority.consensus_outcome == ResonanceOutcome.SUCCESS
        assert weighted.consensus_outcome == ResonanceOutcome.PARTIAL

    def test_execution_metadata_populated(
        self, registry: AgentRegistry, reputation_layer: ReputationLayer
    ):
        class _StubAgent:
            agent_id = "atlas"
            name = "atlas-analytics"

            def process_intent(self, signal):
                return ResonanceOutcome.SUCCESS

            def last_quality_estimate(self):
                return 0.7

            def last_formatted_result(self):
                return "done"

        swarm = SwarmCoordinator(registry, reputation_layer)
        swarm.bind_agent(_StubAgent())  # type: ignore[arg-type]
        result = swarm.execute(_purchase_signal())

        assert result.started_at <= result.completed_at
        assert result.metrics is not None
        assert result.metrics.agents_executed == 1
        assert result.metrics.success_rate == 1.0
        assert result.consensus_strategy == ConsensusStrategy.QUALITY_WEIGHTED