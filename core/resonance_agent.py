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
from typing import Any, Callable

from config import AGENT_LOOP_INTERVAL_SECONDS, load_config
from core.memory import AgentMemory, EpisodicRecord, MemoryStore, create_memory_store
from core.scoring import OutcomeTier, ResonanceScorer, ScoreUpdate, create_scorer
from core.state import AgentLifecycle, AgentState, StateManager
from utils.logging import emit_axiom_event, setup_logging

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
# Stub implementations (replaced by real modules in harvesting/, generation/, etc.)
# ---------------------------------------------------------------------------


class _StubHarvester(IntentHarvesterProtocol):
    def harvest(self, agent_memory: AgentMemory) -> IntentSignal | None:
        return None


class _StubEngine(ResonanceEngineProtocol):
    def generate(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> ResonancePayload | None:
        return None


class _StubInjector(ValueInjectorProtocol):
    def inject(self, payload: ResonancePayload, signal: IntentSignal) -> ResonanceOutcome:
        return ResonanceOutcome.SKIPPED


class _StubHandoff(ArclyHandoffProtocol):
    def handoff(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
        agent_id: str,
    ) -> ResonanceOutcome:
        return ResonanceOutcome.SKIPPED


# ---------------------------------------------------------------------------
# ResonanceAgent
# ---------------------------------------------------------------------------


class ResonanceAgent:
    """
    A sovereign, persistent resonance agent.

    Owns its memory, goals, Resonance Score, and lifecycle. The main loop
    is designed for long-running deployment with clean extension points for
    each Fabric layer.
    """

    def __init__(
        self,
        name: str,
        goals: list[str] | None = None,
        *,
        memory_store: MemoryStore | None = None,
        scorer: ResonanceScorer | None = None,
        state_manager: StateManager | None = None,
        harvester: IntentHarvesterProtocol | None = None,
        engine: ResonanceEngineProtocol | None = None,
        injector: ValueInjectorProtocol | None = None,
        handoff: ArclyHandoffProtocol | None = None,
        on_score_update: Callable[[ScoreUpdate], None] | None = None,
    ) -> None:
        load_config().ensure_directories()

        self.name = name
        self._memory_store = memory_store or create_memory_store()
        self._scorer = scorer or create_scorer()
        self._state_manager = state_manager or StateManager()
        self._harvester = harvester or _StubHarvester()
        self._engine = engine or _StubEngine()
        self._injector = injector or _StubInjector()
        self._handoff = handoff or _StubHandoff()
        self._on_score_update = on_score_update

        self._memory = self._memory_store.load(name)
        if goals:
            self._memory.goals = goals
            self._memory_store.save(self._memory)

        self._state = self._state_manager.load(self._memory.agent_id, name)
        self._running = False

        logger.info(
            "Agent '%s' initialized (id=%s, score=%.2f)",
            name,
            self._memory.agent_id,
            self.resonance_score,
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

        try:
            # Phase 1: Sense intent (privacy-preserving, local)
            self._state.transition(AgentLifecycle.SENSING)
            self._state_manager.save(self._state)

            signal = self._harvester.harvest(self._memory)
            if signal is None:
                self._state.transition(AgentLifecycle.IDLE)
                self._state_manager.save(self._state)
                return ResonanceOutcome.SKIPPED

            self._state.last_intent_hash = signal.signal_hash
            self._memory_store.set_working(
                self._memory, "last_signal", signal.context_vector
            )

            # Phase 2: Generate resonance
            self._state.transition(AgentLifecycle.RESONATING)
            self._state.current_resonance_id = resonance_id
            self._state_manager.save(self._state)

            payload = self._engine.generate(
                signal, self._memory, self.resonance_score
            )
            if payload is None:
                outcome = self._finalize(ResonanceOutcome.FAILURE, signal, resonance_id)
                return outcome

            payload.resonance_id = resonance_id

            # Phase 3: Inject contextual value
            self._state.transition(AgentLifecycle.INJECTING)
            self._state_manager.save(self._state)

            inject_outcome = self._injector.inject(payload, signal)

            # Phase 4: Arcly handoff for conversion
            if inject_outcome in (ResonanceOutcome.SUCCESS, ResonanceOutcome.PARTIAL):
                self._state.transition(AgentLifecycle.HANDOFF)
                self._state_manager.save(self._state)
                final_outcome = self._handoff.handoff(payload, signal, self.agent_id)
            else:
                final_outcome = inject_outcome

            return self._finalize(final_outcome, signal, resonance_id, payload)

        except Exception as exc:
            logger.exception("Agent '%s' cycle error: %s", self.name, exc)
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
        while self._running:
            self.run_once()
            iterations += 1
            if max_iterations and iterations >= max_iterations:
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

    # -- Internal ------------------------------------------------------------

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

        self._memory_store.record_episode(
            self._memory,
            EpisodicRecord(
                resonance_id=resonance_id,
                context={
                    "signal_hash": signal.signal_hash,
                    "confidence": signal.confidence,
                    "outcome": outcome.value,
                },
                outcome=outcome.value,
                quality_score=quality,
            ),
        )

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