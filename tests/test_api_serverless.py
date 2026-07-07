"""
Tests for Vercel serverless API runtime helpers.

Run with: python -m pytest tests/test_api_serverless.py -v
"""

from __future__ import annotations

import pytest

from agents.registry import AgentRegistry
from api.runtime import (
    build_health_payload,
    run_swarm_execute,
    run_swarm_route,
    serialize_swarm_result,
)
import config
from core.resonance_agent import IntentSignal, ResonanceOutcome
from fabric.swarm import AgentExecutionResult, SwarmResult, SwarmStrategy
from fabric.router import RoutingAssignment
from reputation.edge_kv import create_edge_kv_client, reset_edge_kv_client as reset_kv


@pytest.fixture
def registry() -> AgentRegistry:
    from agents.registry import RegisteredAgent

    reg = AgentRegistry()
    reg.register(
        RegisteredAgent(
            agent_id="atlas",
            name="atlas-analytics",
            goals=["maximize conversion"],
            specialties=["commercial", "purchase"],
        )
    )
    reg.register(
        RegisteredAgent(
            agent_id="nova",
            name="nova-research",
            goals=["educate buyers"],
            specialties=["research"],
        )
    )
    return reg


class TestHealthPayload:
    def test_build_health_payload_shape(self):
        payload = build_health_payload(deep=False)
        assert payload["status"] == "ok"
        assert payload["service"] == "forge-resonance"
        assert "deployment" in payload
        assert "checks" in payload
        assert "edge_kv" in payload["checks"]
        assert "swarm" in payload
        assert "secrets" in payload["checks"]
        assert isinstance(payload["checks"]["secrets"]["database_url"], bool)


class TestSwarmApiRuntime:
    def test_run_swarm_route(self, registry: AgentRegistry):
        body = {
            "intent": {
                "matched_intent": "purchase_intent",
                "text": "buy analytics",
            },
            "agents": [
                {
                    "agent_id": "atlas",
                    "name": "atlas-analytics",
                    "specialties": ["commercial", "purchase"],
                },
                {
                    "agent_id": "nova",
                    "name": "nova-research",
                    "specialties": ["research"],
                },
            ],
            "strategy": "best_single",
        }
        result = run_swarm_route(body)
        assert result["mode"] == "route"
        assert len(result["assignments"]) == 1
        assert result["assignments"][0]["agent_id"] == "atlas"

    def test_run_swarm_execute_with_ephemeral_agents(self):
        body = {
            "mode": "execute",
            "intent": {"matched_intent": "purchase_intent", "topic": "pricing"},
            "agents": [
                {
                    "agent_id": "atlas",
                    "name": "atlas-analytics",
                    "specialties": ["commercial", "purchase"],
                }
            ],
            "bound_agents": [
                {
                    "agent_id": "atlas",
                    "name": "atlas-analytics",
                    "outcome": "success",
                    "quality": 0.82,
                }
            ],
            "strategy": "best_single",
            "timeout_s": 5,
        }
        result = run_swarm_execute(body)
        assert result["mode"] == "execute"
        assert result["success_count"] == 1
        assert result["best_result"]["agent_id"] == "atlas"

    def test_run_swarm_execute_timeout_isolated(self):
        body = {
            "intent": {"matched_intent": "purchase_intent"},
            "agents": [
                {
                    "agent_id": "atlas",
                    "name": "atlas-analytics",
                    "specialties": ["commercial"],
                }
            ],
            "bound_agents": [
                {
                    "agent_id": "atlas",
                    "delay_s": 0.5,
                    "outcome": "success",
                }
            ],
            "strategy": "best_single",
            "timeout_s": 0.05,
        }
        result = run_swarm_execute(body)
        assert result["failure_count"] == 1
        assert result["agent_results"][0]["failure_kind"] == "timeout"
        assert result["best_result"] is None

    def test_serialize_swarm_result(self):
        routing = RoutingAssignment(
            agent_id="atlas",
            agent_name="atlas-analytics",
            rank=1,
            selection_weight=1.0,
            capability_score=0.8,
            combined_score=0.9,
        )
        agent_result = AgentExecutionResult(
            agent_id="atlas",
            agent_name="atlas-analytics",
            routing=routing,
            outcome=ResonanceOutcome.SUCCESS,
            quality=0.8,
        )
        signal = IntentSignal.from_context({"matched_intent": "purchase_intent"})
        from fabric.swarm import SwarmAssignment

        swarm_result = SwarmResult(
            signal=signal,
            strategy=SwarmStrategy.BEST_SINGLE,
            dispatch=SwarmAssignment(signal=signal, strategy=SwarmStrategy.BEST_SINGLE),
            agent_results=(agent_result,),
            best_result=agent_result,
        )
        data = serialize_swarm_result(swarm_result)
        assert data["strategy"] == "best_single"
        assert data["best_result"]["agent_id"] == "atlas"


class TestServerlessConfig:
    def test_load_swarm_config_caps_on_serverless(self, monkeypatch):
        monkeypatch.setenv("VERCEL", "1")
        monkeypatch.setenv("SWARM_AGENT_TIMEOUT", "120")
        monkeypatch.setenv("SWARM_SERVERLESS_TIMEOUT", "20")
        monkeypatch.setenv("VERCEL_FUNCTION_MAX_DURATION", "30")
        import config

        monkeypatch.setattr(config, "VERCEL", True)
        cfg = config.load_swarm_config()
        assert cfg.agent_timeout_s <= 25.0
        assert cfg.max_parallel <= config.SWARM_SERVERLESS_MAX_PARALLEL


class TestEdgeKvSingleton:
    def test_create_edge_kv_client_reuses_instance(self):
        reset_kv()
        first = create_edge_kv_client()
        second = create_edge_kv_client()
        assert first is second
        reset_kv()
        third = create_edge_kv_client()
        assert third is not first