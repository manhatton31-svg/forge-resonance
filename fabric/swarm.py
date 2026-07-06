"""
Swarm Coordinator — multi-agent intent dispatch primitives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from agents.registry import AgentRegistry
from core.resonance_agent import IntentSignal, ResonanceAgent
from fabric.router import IntentRouter, RoutingAssignment
from reputation.score_layer import ReputationLayer
from utils.logging import setup_logging

logger = setup_logging("forge.swarm")


class SwarmStrategy(str, Enum):
    """How to assign an intent across the agent swarm."""

    BEST_SINGLE = "best_single"
    BROADCAST_TOP_N = "broadcast_top_n"


@dataclass
class SwarmAssignment:
    """Outcome of swarm dispatch for one intent."""

    signal: IntentSignal
    strategy: SwarmStrategy
    assignments: list[RoutingAssignment] = field(default_factory=list)
    dispatched_agent_ids: list[str] = field(default_factory=list)

    @property
    def primary_agent_id(self) -> str | None:
        return self.dispatched_agent_ids[0] if self.dispatched_agent_ids else None


AgentHandler = Callable[[ResonanceAgent, IntentSignal], Any]


class SwarmCoordinator:
    """
    Coordinates multi-agent routing and optional intent dispatch.

    Accepts an intent, ranks agents (edge-aware when enabled), and assigns
    to the best single agent or broadcasts to the top N.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        reputation: ReputationLayer | None = None,
        router: IntentRouter | None = None,
        *,
        agents: dict[str, ResonanceAgent] | None = None,
    ) -> None:
        self._registry = registry
        self._reputation = reputation or ReputationLayer()
        self._router = router or IntentRouter(registry, self._reputation)
        self._agents: dict[str, ResonanceAgent] = dict(agents or {})

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    @property
    def router(self) -> IntentRouter:
        return self._router

    def bind_agent(self, agent: ResonanceAgent) -> None:
        """Attach a live agent for dispatch and ensure registry entry."""
        self._agents[agent.agent_id] = agent
        if self._registry.get(agent.agent_id) is None:
            self._registry.register_agent(agent)

    def dispatch(
        self,
        signal: IntentSignal,
        *,
        strategy: SwarmStrategy | str = SwarmStrategy.BEST_SINGLE,
        top_n: int = 3,
        use_edge_data: bool = True,
        submit_intent: bool = True,
    ) -> SwarmAssignment:
        """
        Route ``signal`` and optionally submit to selected agent(s).

        Strategies:
        - ``best_single``: route to top-1 agent
        - ``broadcast_top_n``: route to top N agents (default N=3)
        """
        resolved = (
            strategy
            if isinstance(strategy, SwarmStrategy)
            else SwarmStrategy(str(strategy))
        )

        n = 1 if resolved == SwarmStrategy.BEST_SINGLE else max(1, top_n)
        assignments = self._router.route(
            signal,
            top_n=n,
            use_edge_data=use_edge_data,
        )

        dispatched: list[str] = []
        for assignment in assignments:
            self._registry.increment_load(assignment.agent_id)
            dispatched.append(assignment.agent_id)

            if submit_intent:
                agent = self._agents.get(assignment.agent_id)
                if agent is not None:
                    self._submit_to_agent(agent, signal)
                else:
                    logger.debug(
                        "No live agent bound for %s; routing only",
                        assignment.agent_id,
                    )

        logger.info(
            "Swarm dispatch strategy=%s agents=%s intent=%s",
            resolved.value,
            [a.agent_name for a in assignments],
            assignments[0].intent_label if assignments else "n/a",
        )

        return SwarmAssignment(
            signal=signal,
            strategy=resolved,
            assignments=assignments,
            dispatched_agent_ids=dispatched,
        )

    def release_load(self, agent_id: str, amount: int = 1) -> None:
        """Decrement load after an agent completes a cycle."""
        self._registry.decrement_load(agent_id, amount)

    @staticmethod
    def _submit_to_agent(agent: ResonanceAgent, signal: IntentSignal) -> None:
        text = signal.context_vector.get("text") or signal.context_vector.get(
            "raw_text"
        )
        if text:
            agent.submit_intent(str(text))
        else:
            agent.submit_mock_signal(signal.context_vector, signal.confidence)