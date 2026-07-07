"""
Shared runtime utilities for Vercel serverless API handlers.

Provides cached service instances, JSON helpers, health payloads, and swarm
routing/execution for short-lived environments.
"""

from __future__ import annotations

import json
from functools import lru_cache
from http.server import BaseHTTPRequestHandler
from typing import Any

from agents.registry import AgentRegistry, RegisteredAgent
from config import (
    EDGE_REPUTATION_ENABLED,
    get_deployment_info,
    is_serverless,
    load_swarm_config,
    ping_database,
    redact_env_snapshot,
)
from core.resonance_agent import IntentSignal, ResonanceOutcome
from fabric.router import IntentRouter
from fabric.swarm import (
    AgentExecutionResult,
    ConsensusStrategy,
    SwarmCoordinator,
    SwarmResult,
    SwarmStrategy,
)
from reputation.edge_kv import create_edge_kv_client
from reputation.score_layer import ReputationLayer, create_score_manager

SERVICE_VERSION = "0.2.0"


@lru_cache(maxsize=1)
def get_reputation_layer() -> ReputationLayer:
    """Cached reputation layer for warm serverless invocations."""
    return ReputationLayer(create_score_manager())


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length).decode() if length else "{}"
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json") from exc
    if not isinstance(body, dict):
        raise ValueError("expected JSON object")
    return body


def send_json(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body, default=str).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


def verify_bearer(handler: BaseHTTPRequestHandler, expected_key: str) -> bool:
    if not expected_key:
        return True
    auth = handler.headers.get("Authorization", "")
    return auth == f"Bearer {expected_key}"


def build_health_payload(*, deep: bool = False) -> dict[str, Any]:
    """Assemble deployment health response with optional deep checks."""
    layer = get_reputation_layer()
    edge_kv = layer.score_manager.edge_kv or create_edge_kv_client()
    edge_reachable = edge_kv.ping() if edge_kv.enabled else False

    payload: dict[str, Any] = {
        "status": "ok",
        "service": "forge-resonance",
        "version": SERVICE_VERSION,
        "deployment": get_deployment_info(),
        "checks": {
            "database": ping_database() if deep else {
                "configured": redact_env_snapshot()["database_url"],
                "reachable": None,
                "detail": "skipped_use_deep=1",
            },
            "edge_kv": {
                "enabled": EDGE_REPUTATION_ENABLED and edge_kv.enabled,
                "configured": edge_kv.enabled,
                "reachable": edge_reachable if edge_kv.enabled else None,
                "last_check": edge_kv.last_reachable_check,
            },
            "secrets": redact_env_snapshot(),
        },
        "swarm": {
            "serverless": is_serverless(),
            "agent_timeout_s": load_swarm_config().agent_timeout_s,
            "max_parallel": load_swarm_config().max_parallel,
            "consensus_strategy": load_swarm_config().consensus_strategy,
        },
    }

    if deep:
        payload["fabric"] = layer.fabric_health()
        all_ok = (
            payload["checks"]["database"].get("reachable") is not False
            and (
                not payload["checks"]["edge_kv"]["enabled"]
                or payload["checks"]["edge_kv"]["reachable"] is True
            )
        )
        if not all_ok:
            payload["status"] = "degraded"

    return payload


def build_fabric_health_payload(agent_ids: list[str] | None = None) -> dict[str, Any]:
    layer = get_reputation_layer()
    return {
        "status": "ok",
        "service": "forge-resonance",
        "version": SERVICE_VERSION,
        "deployment": get_deployment_info(),
        "fabric": layer.fabric_health(agent_ids),
        "edge_kv": {
            "enabled": EDGE_REPUTATION_ENABLED,
            "reachable": (
                layer.score_manager.edge_kv.ping()
                if layer.score_manager.edge_kv and layer.score_manager.edge_kv.enabled
                else False
            ),
        },
    }


def _parse_intent(body: dict[str, Any]) -> IntentSignal:
    intent = body.get("intent") or body.get("signal") or {}
    if not isinstance(intent, dict):
        raise ValueError("intent must be an object")
    confidence = float(intent.get("confidence", body.get("confidence", 0.75)))
    return IntentSignal.from_context(intent, confidence=confidence)


def _populate_registry(registry: AgentRegistry, agents: list[dict[str, Any]]) -> None:
    for entry in agents:
        registry.register(
            RegisteredAgent(
                agent_id=str(entry["agent_id"]),
                name=str(entry.get("name") or entry["agent_id"]),
                goals=list(entry.get("goals") or []),
                specialties=list(entry.get("specialties") or []),
            )
        )


def _serialize_agent_result(result: AgentExecutionResult) -> dict[str, Any]:
    return {
        "agent_id": result.agent_id,
        "agent_name": result.agent_name,
        "outcome": result.outcome.value if result.outcome else None,
        "quality": result.quality,
        "score_after": result.score_after,
        "formatted_message": result.formatted_message,
        "error": result.error,
        "failure_kind": result.failure_kind.value if result.failure_kind else None,
        "duration_ms": result.duration_ms,
        "succeeded": result.succeeded,
        "routing": {
            "rank": result.routing.rank,
            "combined_score": result.routing.combined_score,
            "capability_score": result.routing.capability_score,
            "selection_weight": result.routing.selection_weight,
            "score_source": result.routing.score_source,
        },
    }


def serialize_swarm_result(result: SwarmResult) -> dict[str, Any]:
    metrics = result.metrics
    return {
        "strategy": result.strategy.value,
        "consensus_strategy": result.consensus_strategy.value,
        "consensus_outcome": (
            result.consensus_outcome.value if result.consensus_outcome else None
        ),
        "swarm_quality": result.swarm_quality,
        "swarm_confidence": result.swarm_confidence,
        "success_count": result.success_count,
        "failure_count": result.failure_count,
        "started_at": result.started_at.isoformat(),
        "completed_at": result.completed_at.isoformat(),
        "duration_ms": result.duration_ms,
        "metrics": (
            {
                "total_duration_ms": metrics.total_duration_ms,
                "success_rate": metrics.success_rate,
                "average_quality": metrics.average_quality,
                "failure_count": metrics.failure_count,
                "timeout_count": metrics.timeout_count,
                "exception_count": metrics.exception_count,
                "unbound_count": metrics.unbound_count,
                "agents_executed": metrics.agents_executed,
            }
            if metrics
            else None
        ),
        "best_result": (
            _serialize_agent_result(result.best_result)
            if result.best_result
            else None
        ),
        "agent_results": [
            _serialize_agent_result(r) for r in result.agent_results
        ],
        "assignments": [
            {
                "agent_id": a.agent_id,
                "agent_name": a.agent_name,
                "rank": a.rank,
                "combined_score": a.combined_score,
                "capability_score": a.capability_score,
                "intent_label": a.intent_label,
            }
            for a in result.dispatch.assignments
        ],
    }


def run_swarm_route(body: dict[str, Any]) -> dict[str, Any]:
    """Route an intent to agents (no resonance cycle execution)."""
    signal = _parse_intent(body)
    agents = body.get("agents") or []
    if not agents:
        raise ValueError("agents array required for routing")

    registry = AgentRegistry()
    _populate_registry(registry, agents)
    layer = get_reputation_layer()
    router = IntentRouter(registry, layer)

    strategy_raw = str(body.get("strategy", SwarmStrategy.BEST_SINGLE.value))
    strategy = SwarmStrategy(strategy_raw)
    top_n = int(body.get("top_n", 3))

    n = 1 if strategy == SwarmStrategy.BEST_SINGLE else max(1, top_n)
    assignments = router.route(signal, top_n=n)

    return {
        "mode": "route",
        "signal_hash": signal.signal_hash,
        "strategy": strategy.value,
        "assignments": [
            {
                "agent_id": a.agent_id,
                "agent_name": a.agent_name,
                "rank": a.rank,
                "combined_score": a.combined_score,
                "capability_score": a.capability_score,
                "selection_weight": a.selection_weight,
                "score_source": a.score_source,
                "intent_label": a.intent_label,
            }
            for a in assignments
        ],
    }


def run_swarm_execute(body: dict[str, Any]) -> dict[str, Any]:
    """
    Execute swarm routing + optional in-memory agent cycles.

    Serverless-safe: caps timeouts via ``load_swarm_config()`` and expects
    agent specs in the request body (no local file-backed agents).
    """
    signal = _parse_intent(body)
    agents_spec = body.get("agents") or []
    if not agents_spec:
        raise ValueError("agents array required for execute")

    registry = AgentRegistry()
    _populate_registry(registry, agents_spec)
    layer = get_reputation_layer()
    swarm = SwarmCoordinator(registry, layer, execution_config=load_swarm_config())

    bound = body.get("bound_agents") or []
    if bound:
        _bind_ephemeral_agents(swarm, bound)

    strategy_raw = str(body.get("strategy", SwarmStrategy.BEST_SINGLE.value))
    strategy = SwarmStrategy(strategy_raw)
    top_n = int(body.get("top_n", 2 if is_serverless() else 3))
    consensus_raw = body.get("consensus_strategy")
    consensus = (
        ConsensusStrategy(str(consensus_raw)) if consensus_raw else None
    )

    if is_serverless() and strategy == SwarmStrategy.BROADCAST_TOP_N:
        top_n = min(top_n, load_swarm_config().max_parallel)

    timeout_s = body.get("timeout_s")
    if timeout_s is not None:
        timeout_s = float(timeout_s)

    result = swarm.execute(
        signal,
        strategy=strategy,
        top_n=top_n,
        timeout_s=timeout_s,
        consensus_strategy=consensus,
        record_reputation=bool(body.get("record_reputation", True)),
        apply_swarm_bonus=bool(body.get("apply_swarm_bonus", False)),
    )

    payload = serialize_swarm_result(result)
    payload["mode"] = "execute"
    payload["signal_hash"] = signal.signal_hash
    if not bound and result.failure_count == len(result.agent_results):
        payload["warning"] = (
            "No bound_agents provided; routing ran but agents were unbound. "
            "Pass bound_agents with agent_id/name for in-memory execution, "
            "or use mode=route for routing-only on serverless."
        )
    return payload


def _bind_ephemeral_agents(
    swarm: SwarmCoordinator,
    bound: list[dict[str, Any]],
) -> None:
    """Attach lightweight in-memory agents for serverless execute."""
    for spec in bound:
        agent = _EphemeralAgent(
            agent_id=str(spec["agent_id"]),
            name=str(spec.get("name") or spec["agent_id"]),
            outcome=str(spec.get("outcome", ResonanceOutcome.SUCCESS.value)),
            quality=float(spec.get("quality", 0.75)),
            message=str(spec.get("message", "serverless resonance")),
            delay_s=float(spec.get("delay_s", 0.0)),
        )
        swarm.bind_agent(agent)  # type: ignore[arg-type]


class _EphemeralAgent:
    """Minimal stand-in agent for serverless swarm execute tests and demos."""

    def __init__(
        self,
        *,
        agent_id: str,
        name: str,
        outcome: str,
        quality: float,
        message: str,
        delay_s: float = 0.0,
    ) -> None:
        self.agent_id = agent_id
        self.name = name
        self._outcome = outcome
        self._quality = quality
        self._message = message
        self._delay_s = delay_s
        self.goals: list[str] = []

    def process_intent(self, signal: IntentSignal) -> ResonanceOutcome:
        import time

        if self._delay_s > 0:
            time.sleep(self._delay_s)
        try:
            return ResonanceOutcome(self._outcome)
        except ValueError:
            return ResonanceOutcome.FAILURE

    def last_quality_estimate(self) -> float:
        return self._quality

    def last_formatted_result(self) -> str:
        return self._message