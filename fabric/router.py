"""
Intent Router — assigns intents to the best-suited agents on the Fabric.

Combines reputation ranking (with edge-aware scores) and capability matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.registry import AgentRegistry, RegisteredAgent
from core.resonance_agent import IntentSignal
from fabric.capabilities import (
    capability_score_for_agent,
    intent_label_from_signal,
)
from reputation.score_layer import AgentReputation, ReputationLayer
from utils.logging import setup_logging

logger = setup_logging("forge.router")

CAPABILITY_WEIGHT = 0.4
REPUTATION_WEIGHT = 0.6
LOAD_PENALTY_FACTOR = 0.5
MIN_CAPABILITY_THRESHOLD = 0.1


@dataclass
class RoutingAssignment:
    """Result of routing an intent to an agent."""

    agent_id: str
    agent_name: str
    rank: int
    selection_weight: float
    capability_score: float
    combined_score: float
    score_source: str = "local"
    intent_label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class IntentRouter:
    """
    Routes ``IntentSignal`` instances to agents using reputation + capability.

    Primary signal: ``ReputationLayer.rank_agents()`` with edge data when enabled.
    Secondary: capability match from agent goals/specialties vs intent label.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        reputation: ReputationLayer | None = None,
        *,
        capability_weight: float = CAPABILITY_WEIGHT,
        reputation_weight: float = REPUTATION_WEIGHT,
        min_capability: float = MIN_CAPABILITY_THRESHOLD,
    ) -> None:
        self._registry = registry
        self._reputation = reputation or ReputationLayer()
        self._capability_weight = capability_weight
        self._reputation_weight = reputation_weight
        self._min_capability = min_capability

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    @property
    def reputation(self) -> ReputationLayer:
        return self._reputation

    def route(
        self,
        signal: IntentSignal,
        *,
        top_n: int = 1,
        use_edge_data: bool = True,
        min_visibility: float = 0.0,
        min_capability: float | None = None,
    ) -> list[RoutingAssignment]:
        """
        Return the top ``top_n`` agents to handle ``signal``.

        Agents are scored by blending reputation selection weight with
        capability match and a load penalty. Edge KV data is used when the
        reputation layer has an enabled edge client and ``use_edge_data=True``.
        """
        intent_label = intent_label_from_signal(signal.context_vector)
        candidates = self._registry.list_available()
        if not candidates:
            logger.warning("No available agents in registry for routing")
            return []

        cap_threshold = (
            min_capability if min_capability is not None else self._min_capability
        )
        candidate_ids = [c.agent_id for c in candidates]
        names = {c.agent_id: c.name for c in candidates}

        ranked = self._reputation.rank_agents(
            candidate_ids,
            agent_names=names,
            min_visibility=min_visibility,
            use_edge_data=use_edge_data,
        )
        rep_by_id = {r.agent_id: r for r in ranked}

        scored: list[tuple[float, RegisteredAgent, AgentReputation, float]] = []
        for agent in candidates:
            rep = rep_by_id.get(agent.agent_id)
            if rep is None:
                continue

            cap_score = capability_score_for_agent(agent, intent_label)
            if cap_score < cap_threshold:
                logger.debug(
                    "Agent %s below capability threshold %.2f for %s",
                    agent.name,
                    cap_threshold,
                    intent_label,
                )
                continue

            combined = self._combined_score(
                rep.selection_weight,
                cap_score,
                agent.load_ratio,
            )
            scored.append((combined, agent, rep, cap_score))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: max(1, top_n)]

        assignments: list[RoutingAssignment] = []
        for position, (combined, agent, rep, cap_score) in enumerate(top, start=1):
            if rep.score_source != "local":
                logger.info(
                    "Routed intent=%s to agent=%s via %s "
                    "(weight=%.3f capability=%.2f combined=%.3f)",
                    intent_label or signal.signal_hash[:8],
                    agent.name,
                    rep.score_source,
                    rep.selection_weight,
                    cap_score,
                    combined,
                )
            else:
                logger.debug(
                    "Routed intent=%s to agent=%s local "
                    "(weight=%.3f capability=%.2f)",
                    intent_label or signal.signal_hash[:8],
                    agent.name,
                    rep.selection_weight,
                    cap_score,
                )

            assignments.append(
                RoutingAssignment(
                    agent_id=agent.agent_id,
                    agent_name=agent.name,
                    rank=position,
                    selection_weight=rep.selection_weight,
                    capability_score=cap_score,
                    combined_score=combined,
                    score_source=rep.score_source,
                    intent_label=intent_label,
                    metadata={
                        "signal_hash": signal.signal_hash,
                        "confidence": signal.confidence,
                        "current_load": agent.current_load,
                    },
                )
            )

        return assignments

    def best_agent(
        self,
        signal: IntentSignal,
        *,
        use_edge_data: bool = True,
    ) -> RoutingAssignment | None:
        """Convenience: return single best agent or ``None``."""
        results = self.route(signal, top_n=1, use_edge_data=use_edge_data)
        return results[0] if results else None

    def _combined_score(
        self,
        selection_weight: float,
        capability_score: float,
        load_ratio: float,
    ) -> float:
        rep_component = selection_weight * self._reputation_weight
        cap_component = capability_score * self._capability_weight
        base = rep_component + cap_component
        load_factor = max(0.1, 1.0 - load_ratio * LOAD_PENALTY_FACTOR)
        return base * load_factor