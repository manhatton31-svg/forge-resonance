"""
Tests for Cloudflare KV edge reputation client and score layer integration.

Run with: python -m pytest tests/test_edge_kv.py -v
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from config import EdgeReputationConfig
from core.scoring import InMemoryScoreStore, OutcomeTier, ResonanceScorer
from reputation.edge_kv import CloudflareKVClient, EdgeReputationRecord
from reputation.score_layer import (
    InMemoryOutcomeHistoryStore,
    ResonanceScoreManager,
    ReputationLayer,
)


def _enabled_config() -> EdgeReputationConfig:
    return EdgeReputationConfig(
        enabled=True,
        api_token="test-token",
        account_id="acct-123",
        namespace_id="ns-456",
        key_prefix="reputation:",
        timeout_seconds=5.0,
    )


class MockKVStore:
    """In-memory KV backing for tests."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self.put_calls: list[tuple[str, bytes]] = []
        self.fail_next = False

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, bytes]:
        if self.fail_next:
            self.fail_next = False
            raise TimeoutError("simulated KV timeout")

        if method == "GET" and "/values/" in url:
            key = url.rsplit("/values/", 1)[-1]
            if key not in self._data:
                return 404, b""
            return 200, self._data[key]

        if method == "PUT" and "/values/" in url:
            key = url.rsplit("/values/", 1)[-1]
            assert body is not None
            self._data[key] = body
            self.put_calls.append((key, body))
            return 200, b""

        if method == "GET" and url.endswith("/namespaces/ns-456"):
            return 200, b'{"success":true}'

        return 404, b""


@pytest.fixture
def mock_store() -> MockKVStore:
    return MockKVStore()


@pytest.fixture
def kv_client(mock_store: MockKVStore) -> CloudflareKVClient:
    return CloudflareKVClient(
        config=_enabled_config(),
        request_fn=mock_store.request,
    )


class TestCloudflareKVClient:
    def test_disabled_when_not_configured(self):
        client = CloudflareKVClient(
            config=EdgeReputationConfig(enabled=False),
        )
        assert not client.enabled
        assert client.get_score("agent-1") is None
        assert client.sync_score("agent-1", 55.0, 1.1) is False

    def test_sync_and_get_score(self, kv_client: CloudflareKVClient, mock_store: MockKVStore):
        assert kv_client.sync_score("agent-a", 62.5, 1.25, metadata={"source": "test"})
        assert len(mock_store.put_calls) == 1
        score = kv_client.get_score("agent-a")
        assert score == pytest.approx(62.5)

    def test_set_score_derives_visibility(self, kv_client: CloudflareKVClient):
        assert kv_client.set_score("agent-b", 50.0, metadata={"k": "v"})
        record = kv_client.get_record("agent-b")
        assert record is not None
        assert record.visibility_multiplier == pytest.approx(1.05)

    def test_get_visibility_multiplier(self, kv_client: CloudflareKVClient):
        kv_client.sync_score("agent-c", 80.0, 1.6)
        assert kv_client.get_visibility_multiplier("agent-c") == pytest.approx(1.6)

    def test_missing_key_returns_none(self, kv_client: CloudflareKVClient):
        assert kv_client.get_score("unknown") is None

    def test_sync_failure_returns_false(
        self, kv_client: CloudflareKVClient, mock_store: MockKVStore
    ):
        mock_store.fail_next = True
        assert kv_client.sync_score("agent-d", 50.0, 1.05) is False

    def test_ping_when_reachable(self, kv_client: CloudflareKVClient):
        assert kv_client.ping() is True

    def test_record_round_trip_json(self):
        raw = EdgeReputationRecord(
            agent_id="x",
            score=70.0,
            visibility_multiplier=1.4,
            synced_at="2026-07-06T00:00:00+00:00",
            metadata={"m": 1},
        ).to_json()
        parsed = EdgeReputationRecord.from_json(raw, agent_id="x")
        assert parsed is not None
        assert parsed.score == pytest.approx(70.0)


class TestScoreManagerEdgeIntegration:
    @pytest.fixture
    def manager(self, kv_client: CloudflareKVClient) -> ResonanceScoreManager:
        scorer = ResonanceScorer(InMemoryScoreStore())
        history = InMemoryOutcomeHistoryStore()
        return ResonanceScoreManager(
            scorer=scorer,
            history_store=history,
            edge_kv=kv_client,
        )

    def test_record_outcome_syncs_to_kv(
        self, manager: ResonanceScoreManager, kv_client: CloudflareKVClient
    ):
        manager.record_outcome(
            "edge-agent",
            OutcomeTier.SUCCESS,
            quality=0.9,
            resonance_id="r1",
        )
        edge_score = kv_client.get_score("edge-agent")
        assert edge_score is not None
        assert edge_score == pytest.approx(manager.get_score("edge-agent"))

    def test_resolve_score_uses_kv_when_local_cold(
        self, manager: ResonanceScoreManager, kv_client: CloudflareKVClient
    ):
        kv_client.sync_score("cold-agent", 72.0, 1.44)
        assert manager.get_score("cold-agent") == pytest.approx(50.0)
        assert manager.resolve_score("cold-agent") == pytest.approx(72.0)

    def test_resolve_score_prefers_local_when_warm(
        self, manager: ResonanceScoreManager, kv_client: CloudflareKVClient
    ):
        kv_client.sync_score("warm-agent", 90.0, 1.8)
        manager.record_outcome("warm-agent", OutcomeTier.FAILURE, quality=0.1)
        local = manager.get_score("warm-agent")
        assert local < 50.0
        assert manager.resolve_score("warm-agent") == pytest.approx(local)

    def test_edge_disabled_no_sync(self, mock_store: MockKVStore):
        disabled = CloudflareKVClient(
            config=EdgeReputationConfig(enabled=False),
            request_fn=mock_store.request,
        )
        manager = ResonanceScoreManager(
            scorer=ResonanceScorer(InMemoryScoreStore()),
            history_store=InMemoryOutcomeHistoryStore(),
            edge_kv=disabled,
        )
        manager.record_outcome("no-edge", OutcomeTier.SUCCESS, quality=0.8)
        assert not mock_store.put_calls

    def test_get_score_from_edge(self, manager: ResonanceScoreManager, kv_client: CloudflareKVClient):
        kv_client.set_score("remote", 65.0)
        assert manager.get_score_from_edge("remote") == pytest.approx(65.0)

    def test_get_visibility_from_edge(
        self, manager: ResonanceScoreManager, kv_client: CloudflareKVClient
    ):
        kv_client.sync_score("vis-agent", 50.0, 1.05)
        assert manager.get_visibility_from_edge("vis-agent") == pytest.approx(1.05)


class TestReputationLayerEdge:
    def test_sync_to_edge(self, kv_client: CloudflareKVClient):
        scorer = ResonanceScorer(InMemoryScoreStore())
        manager = ResonanceScoreManager(
            scorer=scorer,
            history_store=InMemoryOutcomeHistoryStore(),
            edge_kv=kv_client,
        )
        layer = ReputationLayer(manager)
        update = manager.record_outcome("layer-agent", OutcomeTier.SUCCESS, quality=0.9)
        assert update is not None
        assert layer.sync_to_edge(update) is True
        assert kv_client.get_score("layer-agent") == pytest.approx(update.new_score)

    def test_fabric_health_reports_edge(self, kv_client: CloudflareKVClient):
        manager = ResonanceScoreManager(
            scorer=ResonanceScorer(InMemoryScoreStore()),
            history_store=InMemoryOutcomeHistoryStore(),
            edge_kv=kv_client,
        )
        layer = ReputationLayer(manager)
        health = layer.fabric_health()
        assert health["edge_sync"] is True
        assert health["edge_reputation_enabled"] is True
        assert health["edge_reachable"] is True