"""
Fabric swarm coordination — route intents and execute resonance cycles.

**Quick start (local):**

    swarm = SwarmCoordinator(registry, reputation_layer)
    swarm.bind_agents([agent_a, agent_b])
    result = swarm.execute(signal, strategy=SwarmStrategy.BEST_SINGLE)

**Serverless:** use ``dispatch()`` / ``IntentRouter.route()`` for routing-only;
full ``execute()`` needs bound ``ResonanceAgent`` instances (local or Workers).

See ``examples/swarm_execute.py`` and ``docs/extending.md``.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Sequence, TYPE_CHECKING

from agents.registry import AgentRegistry
from config import SwarmExecutionConfig, load_swarm_config
from core.resonance_agent import IntentSignal, ResonanceAgent, ResonanceOutcome
from core.scoring import OutcomeTier
from fabric.router import IntentRouter, RoutingAssignment
from reputation.score_layer import ReputationLayer
from utils.logging import emit_axiom_event, setup_logging

if TYPE_CHECKING:
    from reputation.score_layer import ResonanceScoreManager

logger = setup_logging("forge.swarm")


class SwarmStrategy(str, Enum):
    """How to assign an intent across the agent swarm."""

    BEST_SINGLE = "best_single"
    BROADCAST_TOP_N = "broadcast_top_n"


class ConsensusStrategy(str, Enum):
    """How to resolve consensus across broadcast agent outcomes."""

    MAJORITY = "majority"
    QUALITY_WEIGHTED = "quality_weighted"


class AgentFailureKind(str, Enum):
    """Why an agent execution failed."""

    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    UNBOUND = "unbound"


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
    failure_kind: AgentFailureKind | None = None
    skipped: bool = False
    duration_ms: float = 0.0

    @property
    def succeeded(self) -> bool:
        return (
            not self.skipped
            and self.error is None
            and self.failure_kind is None
            and self.outcome is not None
            and self.outcome not in (ResonanceOutcome.FAILURE, ResonanceOutcome.REJECTION)
        )

    @property
    def timed_out(self) -> bool:
        return self.failure_kind == AgentFailureKind.TIMEOUT

    @property
    def failed(self) -> bool:
        return self.failure_kind is not None or self.outcome in (
            ResonanceOutcome.FAILURE,
            ResonanceOutcome.REJECTION,
        )


@dataclass(frozen=True)
class SwarmExecutionMetrics:
    """Observability metrics for a single swarm execution."""

    total_duration_ms: float
    success_rate: float
    average_quality: float
    failure_count: int
    timeout_count: int
    exception_count: int
    unbound_count: int
    agents_executed: int


@dataclass(frozen=True)
class SwarmResult:
    """Aggregated result of swarm execution across one or more agents."""

    signal: IntentSignal
    strategy: SwarmStrategy
    dispatch: SwarmAssignment
    agent_results: tuple[AgentExecutionResult, ...]
    best_result: AgentExecutionResult | None = None
    consensus_outcome: ResonanceOutcome | None = None
    consensus_strategy: ConsensusStrategy = ConsensusStrategy.QUALITY_WEIGHTED
    swarm_quality: float = 0.0
    swarm_confidence: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metrics: SwarmExecutionMetrics | None = None

    @property
    def duration_ms(self) -> float:
        return (self.completed_at - self.started_at).total_seconds() * 1000.0

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.agent_results if r.succeeded)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.agent_results if r.failed or not r.succeeded)


AgentHandler = Callable[[ResonanceAgent, IntentSignal], Any]


class SwarmCoordinator:
    """
    Coordinates multi-agent routing, execution, and result aggregation.

    Accepts an intent, ranks agents (edge-aware when enabled), assigns to the
    best single agent or broadcasts to the top N, and can run full resonance
    cycles via ``execute()`` with configurable timeouts and observability.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        reputation: ReputationLayer | None = None,
        router: IntentRouter | None = None,
        *,
        agents: dict[str, ResonanceAgent] | None = None,
        execution_config: SwarmExecutionConfig | None = None,
    ) -> None:
        self._registry = registry
        self._reputation = reputation or ReputationLayer()
        self._router = router or IntentRouter(registry, self._reputation)
        self._agents: dict[str, ResonanceAgent] = dict(agents or {})
        self._config = execution_config or load_swarm_config()

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

    @property
    def execution_config(self) -> SwarmExecutionConfig:
        return self._config

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
            "swarm_dispatch strategy=%s agents=%s intent=%s signal_hash=%s",
            resolved.value,
            [a.agent_name for a in assignments],
            assignments[0].intent_label if assignments else "n/a",
            signal.signal_hash,
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
        max_parallel: int | None = None,
        consensus_strategy: ConsensusStrategy | str | None = None,
        record_reputation: bool = True,
        apply_swarm_bonus: bool = False,
    ) -> SwarmResult:
        """
        Route, run resonance cycles on selected agent(s), and aggregate outcomes.

        Individual agent failures, timeouts, and exceptions are isolated — the
        swarm continues and returns partial results. Successful ``process_intent``
        calls record reputation via ``run_once()``; other failures are recorded
        manually when ``record_reputation=True``.
        """
        started_at = datetime.now(timezone.utc)
        resolved_strategy = (
            strategy
            if isinstance(strategy, SwarmStrategy)
            else SwarmStrategy(str(strategy))
        )
        resolved_consensus = self._resolve_consensus_strategy(consensus_strategy)
        effective_timeout = self._effective_timeout(timeout_s)
        parallel_limit = max_parallel if max_parallel is not None else self._config.max_parallel

        dispatch = self.dispatch(
            signal,
            strategy=resolved_strategy,
            top_n=top_n,
            use_edge_data=use_edge_data,
            submit_intent=False,
        )

        agent_names = [a.agent_name for a in dispatch.assignments]
        logger.info(
            "swarm_execute_start signal_hash=%s strategy=%s agents=%s "
            "timeout_s=%s max_parallel=%s consensus=%s",
            signal.signal_hash,
            resolved_strategy.value,
            agent_names,
            effective_timeout,
            parallel_limit,
            resolved_consensus.value,
        )
        emit_axiom_event(
            "swarm_execute_start",
            {
                "signal_hash": signal.signal_hash,
                "strategy": resolved_strategy.value,
                "agent_count": len(dispatch.assignments),
                "timeout_s": effective_timeout,
                "consensus_strategy": resolved_consensus.value,
            },
        )

        agent_results = self._run_agents_parallel(
            dispatch.assignments,
            signal,
            timeout_s=effective_timeout,
            max_parallel=parallel_limit,
            record_reputation=record_reputation,
        )

        best = self._select_best(agent_results)
        consensus = self._consensus_outcome(agent_results, resolved_consensus)
        swarm_quality = self._aggregate_quality(agent_results, resolved_strategy)
        swarm_confidence = self._aggregate_confidence(agent_results, resolved_strategy)
        completed_at = datetime.now(timezone.utc)
        metrics = self._build_metrics(agent_results, started_at, completed_at)

        if apply_swarm_bonus and record_reputation:
            self._apply_swarm_reputation_bonus(agent_results, swarm_quality)

        result = SwarmResult(
            signal=signal,
            strategy=resolved_strategy,
            dispatch=dispatch,
            agent_results=tuple(agent_results),
            best_result=best,
            consensus_outcome=consensus,
            consensus_strategy=resolved_consensus,
            swarm_quality=swarm_quality,
            swarm_confidence=swarm_confidence,
            started_at=started_at,
            completed_at=completed_at,
            metrics=metrics,
        )

        self._log_execution_complete(result)
        return result

    def release_load(self, agent_id: str, amount: int = 1) -> None:
        """Decrement load after an agent completes a cycle."""
        self._registry.decrement_load(agent_id, amount)

    def _effective_timeout(self, timeout_s: float | None) -> float | None:
        if timeout_s is not None:
            return timeout_s if timeout_s > 0 else None
        config_timeout = self._config.agent_timeout_s
        return config_timeout if config_timeout > 0 else None

    def _resolve_consensus_strategy(
        self,
        override: ConsensusStrategy | str | None,
    ) -> ConsensusStrategy:
        if override is None:
            return ConsensusStrategy(self._config.consensus_strategy)
        if isinstance(override, ConsensusStrategy):
            return override
        return ConsensusStrategy(str(override))

    def _run_agents_parallel(
        self,
        assignments: Sequence[RoutingAssignment],
        signal: IntentSignal,
        *,
        timeout_s: float | None,
        max_parallel: int,
        record_reputation: bool,
    ) -> list[AgentExecutionResult]:
        if not assignments:
            return []

        if len(assignments) == 1 or max_parallel <= 1:
            results: list[AgentExecutionResult] = []
            for assignment in assignments:
                try:
                    results.append(
                        self._execute_on_agent(
                            assignment,
                            signal,
                            timeout_s=timeout_s,
                            record_reputation=record_reputation,
                        )
                    )
                finally:
                    self.release_load(assignment.agent_id)
            return results

        indexed_results: dict[int, AgentExecutionResult] = {}
        workers = min(max_parallel, len(assignments))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    self._execute_on_agent,
                    assignment,
                    signal,
                    timeout_s=timeout_s,
                    record_reputation=record_reputation,
                ): (index, assignment)
                for index, assignment in enumerate(assignments)
            }
            for future in as_completed(futures):
                index, assignment = futures[future]
                try:
                    indexed_results[index] = future.result()
                except Exception as exc:
                    logger.exception(
                        "swarm_agent_unexpected_error agent=%s error=%s",
                        assignment.agent_name,
                        exc,
                    )
                    if record_reputation:
                        self._record_failure(
                            assignment.agent_id,
                            signal,
                            reason=str(exc),
                        )
                    indexed_results[index] = AgentExecutionResult(
                        agent_id=assignment.agent_id,
                        agent_name=assignment.agent_name,
                        routing=assignment,
                        outcome=ResonanceOutcome.FAILURE,
                        error=str(exc),
                        failure_kind=AgentFailureKind.EXCEPTION,
                        score_after=self.score_manager.get_score(assignment.agent_id),
                    )
                finally:
                    self.release_load(assignment.agent_id)

        return [indexed_results[i] for i in range(len(assignments))]

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
            result = AgentExecutionResult(
                agent_id=routing.agent_id,
                agent_name=routing.agent_name,
                routing=routing,
                outcome=ResonanceOutcome.FAILURE,
                error="agent not bound to coordinator",
                failure_kind=AgentFailureKind.UNBOUND,
                score_after=self.score_manager.get_score(routing.agent_id),
            )
            self._log_agent_result(result)
            return result

        start = time.perf_counter()
        try:
            if timeout_s is not None:
                outcome = self._run_with_timeout(agent, signal, timeout_s)
            else:
                outcome = agent.process_intent(signal)
            duration_ms = (time.perf_counter() - start) * 1000.0
            result = AgentExecutionResult(
                agent_id=routing.agent_id,
                agent_name=routing.agent_name,
                routing=routing,
                outcome=outcome,
                quality=agent.last_quality_estimate(),
                score_after=self.score_manager.get_score(routing.agent_id),
                formatted_message=agent.last_formatted_result(),
                duration_ms=duration_ms,
            )
            self._log_agent_result(result)
            return result
        except TimeoutError:
            duration_ms = (time.perf_counter() - start) * 1000.0
            if record_reputation:
                self._record_failure(
                    routing.agent_id,
                    signal,
                    reason=f"timeout after {timeout_s}s",
                )
            result = AgentExecutionResult(
                agent_id=routing.agent_id,
                agent_name=routing.agent_name,
                routing=routing,
                outcome=ResonanceOutcome.FAILURE,
                error=f"timeout after {timeout_s}s",
                failure_kind=AgentFailureKind.TIMEOUT,
                score_after=self.score_manager.get_score(routing.agent_id),
                duration_ms=duration_ms,
            )
            self._log_agent_result(result)
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            if record_reputation:
                self._record_failure(routing.agent_id, signal, reason=str(exc))
            result = AgentExecutionResult(
                agent_id=routing.agent_id,
                agent_name=routing.agent_name,
                routing=routing,
                outcome=ResonanceOutcome.FAILURE,
                error=str(exc),
                failure_kind=AgentFailureKind.EXCEPTION,
                score_after=self.score_manager.get_score(routing.agent_id),
                duration_ms=duration_ms,
            )
            self._log_agent_result(result)
            return result

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
        logger.warning(
            "swarm_reputation_failure agent_id=%s signal_hash=%s reason=%s",
            agent_id,
            signal.signal_hash,
            reason,
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
    def _agent_rank_score(result: AgentExecutionResult) -> float:
        """Composite ranking for best-result selection."""
        if not result.succeeded:
            return -1.0
        speed_bonus = max(0.0, 1.0 - min(result.duration_ms / 10_000.0, 1.0))
        return (
            result.quality * 0.45
            + result.routing.combined_score * 0.35
            + result.routing.selection_weight * 0.1
            + speed_bonus * 0.1
        )

    @staticmethod
    def _select_best(
        results: Sequence[AgentExecutionResult],
    ) -> AgentExecutionResult | None:
        candidates = [r for r in results if r.succeeded]
        if not candidates:
            return None
        return max(candidates, key=SwarmCoordinator._agent_rank_score)

    @staticmethod
    def _consensus_outcome(
        results: Sequence[AgentExecutionResult],
        strategy: ConsensusStrategy,
    ) -> ResonanceOutcome | None:
        eligible = [r for r in results if r.outcome is not None and not r.skipped]
        if not eligible:
            return None

        if strategy == ConsensusStrategy.MAJORITY:
            counts: dict[ResonanceOutcome, int] = {}
            for result in eligible:
                counts[result.outcome] = counts.get(result.outcome, 0) + 1
            return max(counts, key=lambda outcome: counts[outcome])

        weights: dict[ResonanceOutcome, float] = {}
        for result in eligible:
            if result.succeeded:
                weight = result.quality * result.routing.combined_score
            else:
                weight = 0.05
            weights[result.outcome] = weights.get(result.outcome, 0.0) + weight
        return max(weights, key=lambda outcome: weights[outcome])

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

    @staticmethod
    def _build_metrics(
        results: Sequence[AgentExecutionResult],
        started_at: datetime,
        completed_at: datetime,
    ) -> SwarmExecutionMetrics:
        total_ms = (completed_at - started_at).total_seconds() * 1000.0
        succeeded = [r for r in results if r.succeeded]
        failures = [r for r in results if r.failed or not r.succeeded]
        return SwarmExecutionMetrics(
            total_duration_ms=total_ms,
            success_rate=len(succeeded) / len(results) if results else 0.0,
            average_quality=(
                sum(r.quality for r in succeeded) / len(succeeded) if succeeded else 0.0
            ),
            failure_count=len(failures),
            timeout_count=sum(1 for r in results if r.timed_out),
            exception_count=sum(
                1 for r in results if r.failure_kind == AgentFailureKind.EXCEPTION
            ),
            unbound_count=sum(
                1 for r in results if r.failure_kind == AgentFailureKind.UNBOUND
            ),
            agents_executed=len(results),
        )

    def _log_agent_result(self, result: AgentExecutionResult) -> None:
        logger.info(
            "swarm_agent_result agent=%s outcome=%s quality=%.2f "
            "duration_ms=%.1f failure_kind=%s error=%s",
            result.agent_name,
            result.outcome.value if result.outcome else "none",
            result.quality,
            result.duration_ms,
            result.failure_kind.value if result.failure_kind else "",
            result.error or "",
        )

    def _log_execution_complete(self, result: SwarmResult) -> None:
        metrics = result.metrics
        logger.info(
            "swarm_execute_complete signal_hash=%s strategy=%s "
            "success=%d failure=%d swarm_quality=%.2f confidence=%.2f "
            "consensus=%s duration_ms=%.1f",
            result.signal.signal_hash,
            result.strategy.value,
            result.success_count,
            result.failure_count,
            result.swarm_quality,
            result.swarm_confidence,
            result.consensus_outcome.value if result.consensus_outcome else "none",
            metrics.total_duration_ms if metrics else result.duration_ms,
        )
        if metrics:
            emit_axiom_event(
                "swarm_execute_complete",
                {
                    "signal_hash": result.signal.signal_hash,
                    "strategy": result.strategy.value,
                    "consensus_strategy": result.consensus_strategy.value,
                    "success_count": result.success_count,
                    "failure_count": metrics.failure_count,
                    "timeout_count": metrics.timeout_count,
                    "success_rate": metrics.success_rate,
                    "average_quality": metrics.average_quality,
                    "swarm_quality": result.swarm_quality,
                    "swarm_confidence": result.swarm_confidence,
                    "duration_ms": metrics.total_duration_ms,
                },
            )

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
                logger.info(
                    "swarm_reputation_bonus agent=%s bonus=%s quality=%.2f",
                    result.agent_name,
                    bonus.value,
                    swarm_quality,
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