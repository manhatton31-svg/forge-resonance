"""
Resonance Matching & Generation Engine.

Matches sensed intent to agent offers and generates hyper-contextual
resonance payloads using Grok models via the xAI API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from config import GROK_MODEL, XAI_API_KEY, XAI_BASE_URL
from core.memory import AgentMemory
from core.resonance_agent import IntentSignal, ResonanceEngineProtocol, ResonancePayload
from utils.logging import setup_logging

logger = setup_logging("forge.generation")


class ResonanceEngine(ResonanceEngineProtocol):
    """
    Grok-native resonance generator.

    Uses agent memory, goals, and Resonance Score to weight generation
    toward high-quality, contextually appropriate value delivery.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = model or GROK_MODEL
        self._api_key = XAI_API_KEY
        self._base_url = XAI_BASE_URL

    def generate(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> ResonancePayload | None:
        """
        Generate a resonance payload for the given intent signal.

        When xAI API key is not configured, returns a structured stub
        payload for development and testing.
        """
        if signal.confidence < 0.3:
            logger.debug("Signal confidence too low; skipping generation")
            return None

        if self._api_key:
            return self._generate_with_grok(signal, agent_memory, resonance_score)

        return self._generate_stub(signal, agent_memory, resonance_score)

    def _generate_stub(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> ResonancePayload:
        """Development stub when Grok API is not configured."""
        return ResonancePayload(
            resonance_id="",
            content={
                "type": "contextual_value",
                "message": f"Resonance for agent '{agent_memory.agent_name}'",
                "context_hash": signal.signal_hash,
                "goals": agent_memory.goals[:3],
            },
            quality_estimate=min(1.0, resonance_score / 100.0),
        )

    def _generate_with_grok(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> ResonancePayload | None:
        """
        Call Grok via xAI API for resonance generation.

        Extension point: implement full prompt engineering with agent goals,
        episodic memory summaries, and offer catalog.
        """
        logger.info(
            "Grok generation requested (model=%s, score=%.2f)",
            self._model,
            resonance_score,
        )
        # Full xAI SDK integration deferred to M3; stub for now
        return self._generate_stub(signal, agent_memory, resonance_score)


class ResonanceMatcher(ABC):
    """Abstract matcher for pairing intent signals to agent offers."""

    @abstractmethod
    def match(
        self,
        signal: IntentSignal,
        offers: list[dict[str, Any]],
        resonance_score: float,
    ) -> dict[str, Any] | None:
        """Return the best-matching offer or None."""
        ...


class ScoreWeightedMatcher(ResonanceMatcher):
    """Simple matcher that weights offers by agent Resonance Score."""

    def match(
        self,
        signal: IntentSignal,
        offers: list[dict[str, Any]],
        resonance_score: float,
    ) -> dict[str, Any] | None:
        if not offers:
            return None
        visibility = resonance_score / 100.0
        scored = sorted(
            offers,
            key=lambda o: o.get("relevance", 0.5) * visibility,
            reverse=True,
        )
        return scored[0] if scored else None