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
from fabric.swarm import SwarmCoordinator, SwarmStrategy
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