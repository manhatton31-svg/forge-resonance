"""
Swarm Coordinator — multi-agent intent routing, execution, and aggregation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence, TYPE_CHECKING

from agents.registry import AgentRegistry
from core.resonance_agent import IntentSignal, ResonanceAgent, ResonanceOutcome
from core.scoring import OutcomeTier
from fabric.router import IntentRouter, RoutingAssignment
from reputation.score_layer import ReputationLayer
from utils.logging import setup_logging

if TYPE_CHECKING:
    from reputation.score_layer import ResonanceScoreManager

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


@dataclass(frozen=True)
class AgentExecutionResult:
    """Outcome of executing an intent on a single swarm participant."""

    agent_id: str
    agent_name: str
    routing: RoutingAssignment
    outcome: ResonanceOutcome | None = None
    quality: float = 0.0
    score_after: float = 0.0
    formatted_message: str = ""
    error: str | None = None
    skipped: bool = False
    duration_ms: float = 0.0

    @property
    def succeeded(self) -> bool:
        return (
            not self.skipped
            and self.error is None
            and self.outcome is not None
            and self.outcome not in (ResonanceOutcome.FAILURE, ResonanceOutcome.REJECTION)
        )


@dataclass(frozen=True)
class SwarmResult:
    """Aggregated result of swarm execution across one or more agents."""

    signal: IntentSignal
    strategy: SwarmStrategy
    dispatch: SwarmAssignment
    agent_results: tuple[AgentExecutionResult, ...]
    best_result: AgentExecutionResult | None = None
    consensus_outcome: ResonanceOutcome | None = None
    swarm_quality: float = 0.0
    swarm_confidence: float = 0.0

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.agent_results if r.succeeded)

    @property
    def failure_count(self) -> int:
        return len(self.agent_results) - self.success_count


AgentHandler = Callable[[ResonanceAgent, IntentSignal], Any]


class SwarmCoordinator:
    """
    Coordinates multi-agent routing, execution, and result aggregation.

    Accepts an intent, ranks agents (edge-aware when enabled), assigns to the
    best single agent or broadcasts to the top N, and can run full resonance
    cycles via ``execute()``.
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

    @property
    def reputation(self) -> ReputationLayer:
        return self._reputation

    @property
    def score_manager(self) -> ResonanceScoreManager:
        return self._reputation.score_manager

    def bind_agent(
        self,
        agent: ResonanceAgent,
        *,
        specialties: list[str] | None = None,
    ) -> None:
        """Attach a live agent for dispatch/execution and ensure registry entry."""
        self._agents[agent.agent_id] = agent
        if self._registry.get(agent.agent_id) is None:
            self._registry.register_agent(agent, specialties=specialties)

    def bind_agents(
        self,
        agents: Sequence[ResonanceAgent],
        *,
        specialties_map: dict[str, list[str]] | None = None,
    ) -> None:
        """Bind multiple live agents at once."""
        specs = specialties_map or {}
        for agent in agents:
            self.bind_agent(agent, specialties=specs.get(agent.agent_id))

    def get_agent(self, agent_id: str) -> ResonanceAgent | None:
        return self._agents.get(agent_id)

    def list_bound_agents(self) -> list[str]:
        return list(self._agents.keys())

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

    def execute(
        self,
        signal: IntentSignal,
        *,
        strategy: SwarmStrategy | str = SwarmStrategy.BEST_SINGLE,
        top_n: int = 3,
        use_edge_data: bool = True,
        timeout_s: float | None = None,
        record_reputation: bool = True,
        apply_swarm_bonus: bool = False,
    ) -> SwarmResult:
        """
        Route, run resonance cycles on selected agent(s), and aggregate outcomes.

        Successful ``process_intent`` calls record reputation via the agent's
        ``run_once()`` path. Unbound agents, timeouts, and exceptions are
        recorded manually when ``record_reputation=True``.
        """
        dispatch = self.dispatch(
            signal,
            strategy=strategy,
            top_n=top_n,
            use_edge_data=use_edge_data,
            submit_intent=False,
        )

        agent_results: list[AgentExecutionResult] = []
        for assignment in dispatch.assignments:
            try:
                result = self._execute_on_agent(
                    assignment,
                    signal,
                    timeout_s=timeout_s,
                    record_reputation=record_reputation,
                )
            finally:
                self.release_load(assignment.agent_id)
            agent_results.append(result)

        best = self._select_best(agent_results)
        consensus = self._consensus_outcome(agent_results)
        resolved = dispatch.strategy
        swarm_quality = self._aggregate_quality(agent_results, resolved)
        swarm_confidence = self._aggregate_confidence(agent_results, resolved)

        if apply_swarm_bonus and record_reputation:
            self._apply_swarm_reputation_bonus(agent_results, swarm_quality)

        return SwarmResult(
            signal=signal,
            strategy=resolved,
            dispatch=dispatch,
            agent_results=tuple(agent_results),
            best_result=best,
            consensus_outcome=consensus,
            swarm_quality=swarm_quality,
            swarm_confidence=swarm_confidence,
        )

    def release_load(self, agent_id: str, amount: int = 1) -> None:
        """Decrement load after an agent completes a cycle."""
        self._registry.decrement_load(agent_id, amount)

    def _execute_on_agent(
        self,
        routing: RoutingAssignment,
        signal: IntentSignal,
        *,
        timeout_s: float | None,
        record_reputation: bool,
    ) -> AgentExecutionResult:
        agent = self._agents.get(routing.agent_id)
        if agent is None:
            if record_reputation:
                self._record_failure(
                    routing.agent_id,
                    signal,
                    reason="agent not bound to coordinator",
                )
            return AgentExecutionResult(
                agent_id=routing.agent_id,
                agent_name=routing.agent_name,
                routing=routing,
                outcome=ResonanceOutcome.FAILURE,
                error="agent not bound to coordinator",
                score_after=self.score_manager.get_score(routing.agent_id),
            )

        start = time.perf_counter()
        try:
            if timeout_s is not None:
                outcome = self._run_with_timeout(agent, signal, timeout_s)
            else:
                outcome = agent.process_intent(signal)
            duration_ms = (time.perf_counter() - start) * 1000.0
            return AgentExecutionResult(
                agent_id=routing.agent_id,
                agent_name=routing.agent_name,
                routing=routing,
                outcome=outcome,
                quality=agent.last_quality_estimate(),
                score_after=self.score_manager.get_score(routing.agent_id),
                formatted_message=agent.last_formatted_result(),
                duration_ms=duration_ms,
            )
        except TimeoutError:
            duration_ms = (time.perf_counter() - start) * 1000.0
            if record_reputation:
                self._record_failure(
                    routing.agent_id,
                    signal,
                    reason=f"timeout after {timeout_s}s",
                )
            return AgentExecutionResult(
                agent_id=routing.agent_id,
                agent_name=routing.agent_name,
                routing=routing,
                outcome=ResonanceOutcome.FAILURE,
                error=f"timeout after {timeout_s}s",
                score_after=self.score_manager.get_score(routing.agent_id),
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            if record_reputation:
                self._record_failure(routing.agent_id, signal, reason=str(exc))
            return AgentExecutionResult(
                agent_id=routing.agent_id,
                agent_name=routing.agent_name,
                routing=routing,
                outcome=ResonanceOutcome.FAILURE,
                error=str(exc),
                score_after=self.score_manager.get_score(routing.agent_id),
                duration_ms=duration_ms,
            )

    def _record_failure(
        self,
        agent_id: str,
        signal: IntentSignal,
        *,
        reason: str,
    ) -> None:
        self.score_manager.record_outcome(
            agent_id,
            OutcomeTier.FAILURE,
            metadata={"swarm_error": reason},
            intent_signal_hash=signal.signal_hash,
            confidence=signal.confidence,
        )

    @staticmethod
    def _run_with_timeout(
        agent: ResonanceAgent,
        signal: IntentSignal,
        timeout_s: float,
    ) -> ResonanceOutcome:
        """Run ``process_intent`` with a wall-clock timeout (best-effort)."""
        import threading

        result: list[ResonanceOutcome] = []
        error: list[BaseException] = []

        def _run() -> None:
            try:
                result.append(agent.process_intent(signal))
            except BaseException as exc:
                error.append(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout_s)
        if thread.is_alive():
            raise TimeoutError(f"agent {agent.agent_id} exceeded {timeout_s}s")
        if error:
            raise error[0]
        if not result:
            raise RuntimeError("agent produced no outcome")
        return result[0]

    @staticmethod
    def _select_best(
        results: Sequence[AgentExecutionResult],
    ) -> AgentExecutionResult | None:
        candidates = [r for r in results if r.succeeded]
        if not candidates:
            candidates = [r for r in results if not r.skipped]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda r: (r.quality, r.routing.combined_score, -r.duration_ms),
        )

    @staticmethod
    def _consensus_outcome(
        results: Sequence[AgentExecutionResult],
    ) -> ResonanceOutcome | None:
        outcomes = [
            r.outcome for r in results if r.outcome is not None and not r.skipped
        ]
        if not outcomes:
            return None
        counts: dict[ResonanceOutcome, int] = {}
        for outcome in outcomes:
            counts[outcome] = counts.get(outcome, 0) + 1
        return max(counts, key=lambda o: counts[o])

    @staticmethod
    def _aggregate_quality(
        results: Sequence[AgentExecutionResult],
        strategy: SwarmStrategy,
    ) -> float:
        succeeded = [r for r in results if r.succeeded]
        if not succeeded:
            return 0.0
        if strategy == SwarmStrategy.BEST_SINGLE:
            return max(succeeded, key=lambda r: r.quality).quality
        return sum(r.quality for r in succeeded) / len(succeeded)

    @staticmethod
    def _aggregate_confidence(
        results: Sequence[AgentExecutionResult],
        strategy: SwarmStrategy,
    ) -> float:
        if not results:
            return 0.0
        if strategy == SwarmStrategy.BEST_SINGLE:
            r = results[0]
            base = r.routing.combined_score
            if r.succeeded:
                return min(1.0, base * 0.6 + r.quality * 0.4)
            return base * 0.3
        success_rate = sum(1 for r in results if r.succeeded) / len(results)
        avg_routing = sum(r.routing.combined_score for r in results) / len(results)
        success_qualities = [r.quality for r in results if r.succeeded]
        avg_quality = (
            sum(success_qualities) / len(success_qualities) if success_qualities else 0.0
        )
        return min(1.0, avg_routing * 0.4 + success_rate * 0.35 + avg_quality * 0.25)

    def _apply_swarm_reputation_bonus(
        self,
        results: Sequence[AgentExecutionResult],
        swarm_quality: float,
    ) -> None:
        """Optional swarm-level reputation nudge for high/low collective quality."""
        if swarm_quality >= 0.75:
            bonus = OutcomeTier.SUCCESS
        elif swarm_quality < 0.35:
            bonus = OutcomeTier.FAILURE
        else:
            return
        for result in results:
            if result.succeeded:
                self.score_manager.record_outcome(
                    result.agent_id,
                    bonus,
                    quality=swarm_quality,
                    metadata={"swarm_bonus": True},
                )

    @staticmethod
    def _submit_to_agent(agent: ResonanceAgent, signal: IntentSignal) -> None:
        text = signal.context_vector.get("text") or signal.context_vector.get(
            "raw_text"
        )
        if text:
            agent.submit_intent(str(text))
        else:
            agent.submit_mock_signal(signal.context_vector, signal.confidence)