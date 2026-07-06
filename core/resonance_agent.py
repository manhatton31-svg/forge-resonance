"""
Sovereign Resonance Agent — the foundational primitive of ForgeResonance.

Each agent maintains its own memory, goals, and Resonance Score. The main
lifecycle loop senses intent, generates resonance, injects value, and hands
off to Arcly for conversion — all without central orchestration.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TYPE_CHECKING

from config import AGENT_LOOP_INTERVAL_SECONDS, load_config
from core.memory import AgentMemory, EpisodicRecord, MemoryStore, create_memory_store
from core.scoring import OutcomeTier, ResonanceScorer, ScoreUpdate, create_scorer
from core.state import AgentLifecycle, AgentState, StateManager
from utils.logging import emit_axiom_event, setup_logging

if TYPE_CHECKING:
    from harvesting.intent_harvester import EmbeddingIntentHarvester
    from generation.resonance_engine import ResonanceEngine
    from injection.value_injector import ValueInjector
    from integration.arcly_handoff import ArclyHandoff

logger = setup_logging("forge.agent")


class ResonanceOutcome(str, Enum):
    """High-level outcome of a resonance cycle."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    REJECTION = "rejection"
    SKIPPED = "skipped"


OUTCOME_TO_TIER: dict[ResonanceOutcome, OutcomeTier] = {
    ResonanceOutcome.SUCCESS: OutcomeTier.SUCCESS,
    ResonanceOutcome.PARTIAL: OutcomeTier.PARTIAL,
    ResonanceOutcome.FAILURE: OutcomeTier.FAILURE,
    ResonanceOutcome.REJECTION: OutcomeTier.REJECTION,
}


@dataclass
class IntentSignal:
    """
    Privacy-preserving intent representation.

    Raw signals never leave the local harvester; only hashed embeddings
    and anonymized context vectors propagate through the Fabric.
    """

    signal_hash: str
    context_vector: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    source: str = "local"

    @staticmethod
    def from_context(context: dict[str, Any], confidence: float = 0.5) -> IntentSignal:
        canonical = str(sorted(context.items()))
        signal_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        return IntentSignal(
            signal_hash=signal_hash,
            context_vector=context,
            confidence=confidence,
        )


@dataclass
class ResonancePayload:
    """Generated value ready for contextual injection."""

    resonance_id: str
    content: dict[str, Any]
    quality_estimate: float = 0.0
    offer_id: str | None = None


# ---------------------------------------------------------------------------
# Extension point interfaces
# ---------------------------------------------------------------------------


class IntentHarvesterProtocol(ABC):
    @abstractmethod
    def harvest(self, agent_memory: AgentMemory) -> IntentSignal | None:
        """Sense forming or active intent. Returns None if no signal detected."""
        ...


class ResonanceEngineProtocol(ABC):
    @abstractmethod
    def generate(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> ResonancePayload | None:
        """Match intent to offer and generate contextual resonance."""
        ...


class ValueInjectorProtocol(ABC):
    @abstractmethod
    def inject(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
    ) -> ResonanceOutcome:
        """Deliver value into the user's context at the moment of intent."""
        ...


class ArclyHandoffProtocol(ABC):
    @abstractmethod
    def handoff(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
        agent_id: str,
    ) -> ResonanceOutcome:
        """Transfer qualified resonance to Arcly AI Closer for conversion."""
        ...


# ---------------------------------------------------------------------------
# Minimal stubs (used only when wire_components=False)
# ---------------------------------------------------------------------------


class _NoOpHarvester(IntentHarvesterProtocol):
    def harvest(self, agent_memory: AgentMemory) -> IntentSignal | None:
        return None


class _NoOpEngine(ResonanceEngineProtocol):
    def generate(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> ResonancePayload | None:
        return None


class _NoOpInjector(ValueInjectorProtocol):
    def inject(self, payload: ResonancePayload, signal: IntentSignal) -> ResonanceOutcome:
        return ResonanceOutcome.SKIPPED


class _NoOpHandoff(ArclyHandoffProtocol):
    def handoff(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
        agent_id: str,
    ) -> ResonanceOutcome:
        return ResonanceOutcome.SKIPPED


def _default_components(
    *,
    echo_injection: bool = False,
) -> tuple[
    IntentHarvesterProtocol,
    ResonanceEngineProtocol,
    ValueInjectorProtocol,
    ArclyHandoffProtocol,
]:
    """Instantiate real Fabric layer components with lazy imports."""
    from harvesting.intent_harvester import EmbeddingIntentHarvester
    from generation.resonance_engine import ResonanceEngine
    from injection.value_injector import ValueInjector
    from integration.arcly_handoff import ArclyHandoff

    return (
        EmbeddingIntentHarvester(),
        ResonanceEngine(),
        ValueInjector(echo=echo_injection),
        ArclyHandoff(),
    )


# ---------------------------------------------------------------------------
# ResonanceAgent
# ---------------------------------------------------------------------------


class ResonanceAgent:
    """
    A sovereign, persistent resonance agent.

    Owns its memory, goals, Resonance Score, and lifecycle. By default the
    agent wires real harvesting, generation, injection, and Arcly handoff
    modules. Pass wire_components=False to use no-op stubs.
    """

    def __init__(
        self,
        name: str,
        goals: list[str] | None = None,
        *,
        memory_store: MemoryStore | None = None,
        scorer: ResonanceScorer | None = None,
        state_manager: StateManager | None = None,
        intent_harvester: IntentHarvesterProtocol | None = None,
        resonance_engine: ResonanceEngineProtocol | None = None,
        value_injector: ValueInjectorProtocol | None = None,
        arcly_handoff: ArclyHandoffProtocol | None = None,
        # Backward-compatible aliases
        harvester: IntentHarvesterProtocol | None = None,
        engine: ResonanceEngineProtocol | None = None,
        injector: ValueInjectorProtocol | None = None,
        handoff: ArclyHandoffProtocol | None = None,
        wire_components: bool = True,
        echo_injection: bool = False,
        on_score_update: Callable[[ScoreUpdate], None] | None = None,
    ) -> None:
        load_config().ensure_directories()

        self.name = name
        self._memory_store = memory_store or create_memory_store()
        self._scorer = scorer or create_scorer()
        self._state_manager = state_manager or StateManager()
        self._on_score_update = on_score_update

        # Resolve explicit overrides (new names take precedence over aliases)
        h = intent_harvester or harvester
        e = resonance_engine or engine
        i = value_injector or injector
        a = arcly_handoff or handoff

        if h is None or e is None or i is None or a is None:
            if wire_components:
                default_h, default_e, default_i, default_a = _default_components(
                    echo_injection=echo_injection
                )
                self._harvester = h or default_h
                self._engine = e or default_e
                self._injector = i or default_i
                self._handoff = a or default_a
            else:
                self._harvester = h or _NoOpHarvester()
                self._engine = e or _NoOpEngine()
                self._injector = i or _NoOpInjector()
                self._handoff = a or _NoOpHandoff()
        else:
            self._harvester = h
            self._engine = e
            self._injector = i
            self._handoff = a

        self._memory = self._memory_store.load(name)
        if goals:
            self._memory.goals = goals
            self._memory_store.save(self._memory)

        self._state = self._state_manager.load(self._memory.agent_id, name)
        self._running = False

        logger.info(
            "Agent '%s' initialized (id=%s, score=%.2f, wired=%s)",
            name,
            self._memory.agent_id,
            self.resonance_score,
            wire_components,
        )

    # -- Properties ----------------------------------------------------------

    @property
    def agent_id(self) -> str:
        return self._memory.agent_id

    @property
    def memory(self) -> AgentMemory:
        return self._memory

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def intent_harvester(self) -> IntentHarvesterProtocol:
        return self._harvester

    @property
    def resonance_engine(self) -> ResonanceEngineProtocol:
        return self._engine

    @property
    def value_injector(self) -> ValueInjectorProtocol:
        return self._injector

    @property
    def arcly_handoff(self) -> ArclyHandoffProtocol:
        return self._handoff

    @property
    def resonance_score(self) -> float:
        return self._scorer.get_score(self.agent_id)

    @property
    def visibility(self) -> float:
        return self._scorer.visibility_for(self.agent_id)

    # -- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Mark agent as running and transition to idle."""
        self._running = True
        self._state.transition(AgentLifecycle.IDLE)
        self._state_manager.save(self._state)
        logger.info("Agent '%s' started", self.name)

    def stop(self) -> None:
        """Gracefully stop the agent loop."""
        self._running = False
        self._state.transition(AgentLifecycle.PAUSED)
        self._state_manager.save(self._state)
        logger.info("Agent '%s' stopped", self.name)

    def run_once(self) -> ResonanceOutcome:
        """Execute a single resonance cycle. Returns the cycle outcome."""
        self._state.loop_count += 1
        resonance_id = str(uuid.uuid4())[:16]
        logger.debug(
            "Cycle #%d start: agent=%s resonance_id=%s",
            self._state.loop_count,
            self.name,
            resonance_id,
        )

        try:
            # Phase 1: Harvest intent (privacy-preserving, local)
            self._state.transition(AgentLifecycle.SENSING)
            self._state_manager.save(self._state)

            signal = self._harvester.harvest(self._memory)
            if signal is None:
                logger.debug("Cycle #%d: no intent signal", self._state.loop_count)
                self._state.transition(AgentLifecycle.IDLE)
                self._state_manager.save(self._state)
                return ResonanceOutcome.SKIPPED

            logger.info(
                "Cycle #%d: intent sensed hash=%s confidence=%.2f",
                self._state.loop_count,
                signal.signal_hash,
                signal.confidence,
            )
            self._state.last_intent_hash = signal.signal_hash
            self._memory_store.set_working(
                self._memory, "last_signal", signal.context_vector
            )
            # Consume one-shot pending intent / mock signal
            self._clear_consumed_intent()

            # Phase 2: Generate resonance
            self._state.transition(AgentLifecycle.RESONATING)
            self._state.current_resonance_id = resonance_id
            self._state_manager.save(self._state)

            payload = self._engine.generate(
                signal, self._memory, self.resonance_score
            )
            if payload is None:
                logger.warning(
                    "Cycle #%d: generation failed for hash=%s",
                    self._state.loop_count,
                    signal.signal_hash,
                )
                return self._finalize(ResonanceOutcome.FAILURE, signal, resonance_id)

            payload.resonance_id = resonance_id
            logger.info(
                "Cycle #%d: resonance generated quality=%.2f",
                self._state.loop_count,
                payload.quality_estimate,
            )

            # Phase 3: Inject contextual value
            self._state.transition(AgentLifecycle.INJECTING)
            self._state_manager.save(self._state)

            inject_outcome = self._injector.inject(payload, signal)
            logger.info(
                "Cycle #%d: injection outcome=%s",
                self._state.loop_count,
                inject_outcome.value,
            )

            # Phase 4: Arcly handoff for conversion
            if inject_outcome in (ResonanceOutcome.SUCCESS, ResonanceOutcome.PARTIAL):
                self._state.transition(AgentLifecycle.HANDOFF)
                self._state_manager.save(self._state)
                final_outcome = self._handoff.handoff(payload, signal, self.agent_id)
                logger.info(
                    "Cycle #%d: Arcly handoff outcome=%s",
                    self._state.loop_count,
                    final_outcome.value,
                )
            else:
                final_outcome = inject_outcome

            return self._finalize(final_outcome, signal, resonance_id, payload)

        except Exception as exc:
            logger.exception(
                "Agent '%s' cycle #%d error: %s",
                self.name,
                self._state.loop_count,
                exc,
            )
            self._state.last_error = str(exc)
            self._state.transition(AgentLifecycle.ERROR)
            self._state_manager.save(self._state)
            return ResonanceOutcome.FAILURE

    def run_loop(self, max_iterations: int | None = None) -> None:
        """
        Run the main resonance loop until stopped or max_iterations reached.

        Designed for persistent deployment; interval controlled by config.
        """
        self.start()
        iterations = 0
        logger.info(
            "Agent '%s' entering resonance loop (max_iterations=%s)",
            self.name,
            max_iterations,
        )
        while self._running:
            outcome = self.run_once()
            iterations += 1
            logger.debug(
                "Loop iteration %d complete: outcome=%s score=%.2f",
                iterations,
                outcome.value,
                self.resonance_score,
            )
            if max_iterations and iterations >= max_iterations:
                logger.info("Agent '%s' reached max_iterations=%d", self.name, max_iterations)
                break
            time.sleep(AGENT_LOOP_INTERVAL_SECONDS)
        self.stop()

    # -- Memory & scoring helpers --------------------------------------------

    def remember(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Store a working-memory entry."""
        self._memory_store.set_working(self._memory, key, value, ttl_seconds)

    def recall(self, key: str, default: Any = None) -> Any:
        """Retrieve a working-memory entry."""
        entry = self._memory.working.get(key)
        if entry is None or entry.is_expired():
            return default
        return entry.value

    def add_goal(self, goal: str) -> None:
        """Append a sovereign goal and persist."""
        if goal not in self._memory.goals:
            self._memory.goals.append(goal)
            self._memory_store.save(self._memory)

    def submit_intent(self, text: str) -> None:
        """Queue a text intent for the next harvest cycle."""
        from harvesting.intent_harvester import EmbeddingIntentHarvester

        EmbeddingIntentHarvester.queue_intent_text(self._memory, text)
        self._memory_store.save(self._memory)

    def submit_mock_signal(
        self, context: dict[str, Any], *, confidence: float = 0.75
    ) -> None:
        """Inject a mock intent signal for testing or demos."""
        from harvesting.intent_harvester import EmbeddingIntentHarvester

        EmbeddingIntentHarvester.set_mock_signal(
            self._memory, context, confidence=confidence
        )
        self._memory_store.save(self._memory)

    # -- Internal ------------------------------------------------------------

    def _clear_consumed_intent(self) -> None:
        """Remove one-shot intent sources after harvest."""
        from harvesting.intent_harvester import PENDING_INTENT_KEY

        self._memory.working.pop(PENDING_INTENT_KEY, None)
        self._memory.metadata.pop("mock_signal", None)

    def _finalize(
        self,
        outcome: ResonanceOutcome,
        signal: IntentSignal,
        resonance_id: str,
        payload: ResonancePayload | None = None,
    ) -> ResonanceOutcome:
        """Record episodic memory, update score, and reset state."""
        self._state.transition(AgentLifecycle.REFLECTING)

        quality = payload.quality_estimate if payload else 0.0
        tier = OUTCOME_TO_TIER.get(outcome)

        if tier is not None:
            update = self._scorer.apply_outcome(
                self.agent_id,
                tier,
                quality=quality,
                reason=f"resonance_cycle:{outcome.value}",
                resonance_id=resonance_id,
                intent_signal_hash=signal.signal_hash,
                metadata={"agent_name": self.name, "confidence": signal.confidence},
            )
            self._state.resonance_score = update.new_score
            if self._on_score_update:
                self._on_score_update(update)
            logger.info(
                "Score updated: %s → %s (Δ%s)",
                update.previous_score,
                update.new_score,
                update.delta,
            )

        self._memory_store.record_episode(
            self._memory,
            EpisodicRecord(
                resonance_id=resonance_id,
                context={
                    "signal_hash": signal.signal_hash,
                    "confidence": signal.confidence,
                    "outcome": outcome.value,
                    "message": (payload.content.get("message") if payload else None),
                },
                outcome=outcome.value,
                quality_score=quality,
            ),
        )
        self._memory_store.save(self._memory)

        emit_axiom_event(
            "resonance_cycle_complete",
            {
                "agent_id": self.agent_id,
                "agent_name": self.name,
                "resonance_id": resonance_id,
                "outcome": outcome.value,
                "score": self.resonance_score,
            },
        )

        self._state.current_resonance_id = None
        self._state.transition(AgentLifecycle.IDLE)
        self._state_manager.save(self._state)
        return outcome

    def __repr__(self) -> str:
        return (
            f"ResonanceAgent(name={self.name!r}, id={self.agent_id!r}, "
            f"score={self.resonance_score:.2f}, phase={self._state.lifecycle.value})"
        )