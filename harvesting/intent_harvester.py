"""
Intent Signal Harvester for ForgeResonance.

Harvests forming or active intent through local-only processing. No raw
signals leave the device. Future integration with Firecrawl enables
opt-in web context enrichment without central data collection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from config import FIRECRAWL_ENABLED
from core.memory import AgentMemory
from core.resonance_agent import IntentHarvesterProtocol, IntentSignal
from utils.logging import setup_logging

logger = setup_logging("forge.harvesting")


class IntentHarvester(IntentHarvesterProtocol):
    """
    Privacy-preserving intent harvester.

    Processes local signals (browser activity embeddings, app context,
    explicit opt-in declarations) into anonymized IntentSignal objects.
    Raw data never persists beyond the local processing boundary.
    """

    def __init__(self, opt_in_required: bool = True) -> None:
        self._opt_in_required = opt_in_required
        self._firecrawl_enabled = FIRECRAWL_ENABLED

    def harvest(self, agent_memory: AgentMemory) -> IntentSignal | None:
        """
        Sense intent from local context.

        Extension point: plug in embedding models, local NLP, or
        zero-knowledge intent proofs. Returns None when no signal
        is detected or user has not opted in.
        """
        if self._opt_in_required and not agent_memory.metadata.get("intent_opt_in"):
            return None

        local_context = self._gather_local_context(agent_memory)
        if not local_context:
            return None

        signal = IntentSignal.from_context(local_context, confidence=0.5)
        logger.debug(
            "Intent harvested: hash=%s confidence=%.2f",
            signal.signal_hash,
            signal.confidence,
        )
        return signal

    def _gather_local_context(self, agent_memory: AgentMemory) -> dict[str, Any]:
        """
        Collect anonymized local context vectors.

        Override in subclasses for device-specific signal sources.
        Firecrawl enrichment hook available when FIRECRAWL_ENABLED=true.
        """
        context: dict[str, Any] = {}

        last_signal = agent_memory.working.get("last_signal")
        if last_signal and not last_signal.is_expired():
            context["prior_signal"] = True

        if self._firecrawl_enabled:
            context["firecrawl_enrichment"] = "pending"

        return context

    def enable_opt_in(self, agent_memory: AgentMemory) -> None:
        """Record explicit user opt-in for intent harvesting."""
        agent_memory.metadata["intent_opt_in"] = True
        logger.info("Intent opt-in enabled for agent '%s'", agent_memory.agent_name)


class EmbeddingIntentHarvester(IntentHarvester):
    """
    Embedding-based harvester using local vector similarity.

    Compares current context embeddings against known intent patterns
    without transmitting raw text to any remote service.
    """

    def __init__(
        self,
        intent_patterns: dict[str, list[float]] | None = None,
        similarity_threshold: float = 0.7,
    ) -> None:
        super().__init__()
        self._patterns = intent_patterns or {}
        self._threshold = similarity_threshold

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def match_intent(self, embedding: list[float]) -> tuple[str, float] | None:
        """Match an embedding against known intent patterns."""
        best_label, best_score = "", 0.0
        for label, pattern in self._patterns.items():
            score = self._cosine_similarity(embedding, pattern)
            if score > best_score:
                best_label, best_score = label, score
        if best_score >= self._threshold:
            return best_label, best_score
        return None