"""
Intent Signal Harvester for ForgeResonance.

Harvests forming or active intent through local-only processing. No raw
signals leave the device. Future integration with Firecrawl enables
opt-in web context enrichment without central data collection.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from config import FIRECRAWL_ENABLED
from core.memory import AgentMemory
from core.resonance_agent import IntentHarvesterProtocol, IntentSignal
from utils.logging import setup_logging

logger = setup_logging("forge.harvesting")

# Working-memory keys used by EmbeddingIntentHarvester
PENDING_INTENT_KEY = "pending_intent_text"
INTENT_EMBEDDING_KEY = "intent_embedding"


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

        Returns None when no signal is detected or user has not opted in.
        """
        if self._opt_in_required and not agent_memory.metadata.get("intent_opt_in"):
            logger.debug(
                "Harvest skipped for '%s': opt-in not granted",
                agent_memory.agent_name,
            )
            return None

        local_context = self._gather_local_context(agent_memory)
        if not local_context:
            return None

        signal = IntentSignal.from_context(local_context, confidence=0.5)
        logger.info(
            "Intent harvested: agent=%s hash=%s confidence=%.2f",
            agent_memory.agent_name,
            signal.signal_hash,
            signal.confidence,
        )
        return signal

    def _gather_local_context(self, agent_memory: AgentMemory) -> dict[str, Any]:
        """Collect anonymized local context vectors."""
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

    Accepts simple text intent, mock signals, or embedding vectors stored
    in agent working memory. Raw text is hashed before leaving the harvest
    boundary — only anonymized context vectors propagate downstream.
    """

    DEFAULT_PATTERNS: dict[str, list[float]] = {
        "purchase_intent": [0.9, 0.1, 0.3, 0.8, 0.2],
        "research_intent": [0.2, 0.9, 0.7, 0.1, 0.4],
        "support_intent": [0.1, 0.3, 0.9, 0.2, 0.8],
    }

    def __init__(
        self,
        intent_patterns: dict[str, list[float]] | None = None,
        similarity_threshold: float = 0.65,
        opt_in_required: bool = False,
    ) -> None:
        super().__init__(opt_in_required=opt_in_required)
        self._patterns = intent_patterns or self.DEFAULT_PATTERNS
        self._threshold = similarity_threshold

    def harvest(self, agent_memory: AgentMemory) -> IntentSignal | None:
        """Harvest intent from text, mock signals, embeddings, or base context."""
        if self._opt_in_required and not agent_memory.metadata.get("intent_opt_in"):
            logger.debug("Embedding harvest skipped: opt-in required")
            return None

        # 1. Pending text intent (queued via queue_intent_text)
        pending = agent_memory.working.get(PENDING_INTENT_KEY)
        if pending and not pending.is_expired():
            signal = self._signal_from_text(str(pending.value))
            logger.info(
                "Harvested text intent: hash=%s topic=%s",
                signal.signal_hash,
                signal.context_vector.get("topic"),
            )
            return signal

        # 2. Mock signal (set via set_mock_signal)
        mock = agent_memory.metadata.get("mock_signal")
        if isinstance(mock, dict) and mock:
            confidence = float(mock.pop("confidence", 0.75))
            signal = IntentSignal.from_context(mock, confidence=confidence)
            logger.info("Harvested mock signal: hash=%s", signal.signal_hash)
            return signal

        # 3. Embedding vector match
        embedding_entry = agent_memory.working.get(INTENT_EMBEDDING_KEY)
        if embedding_entry and not embedding_entry.is_expired():
            match = self.match_intent(embedding_entry.value)
            if match:
                label, score = match
                signal = IntentSignal.from_context(
                    {"matched_intent": label, "source": "embedding"},
                    confidence=score,
                )
                logger.info(
                    "Harvested embedding match: label=%s score=%.2f",
                    label,
                    score,
                )
                return signal

        # 4. Fall back to base local context
        return super().harvest(agent_memory)

    @staticmethod
    def queue_intent_text(agent_memory: AgentMemory, text: str) -> None:
        """Queue a simple text intent for the next harvest cycle."""
        from core.memory import MemoryEntry
        from datetime import datetime, timedelta, timezone
        from config import WORKING_MEMORY_TTL_SECONDS

        agent_memory.working[PENDING_INTENT_KEY] = MemoryEntry(
            key=PENDING_INTENT_KEY,
            value=text.strip(),
            expires_at=datetime.now(timezone.utc) + timedelta(
                seconds=WORKING_MEMORY_TTL_SECONDS
            ),
        )
        agent_memory.metadata["intent_opt_in"] = True
        logger.debug("Queued intent text for '%s'", agent_memory.agent_name)

    @staticmethod
    def set_mock_signal(
        agent_memory: AgentMemory,
        context: dict[str, Any],
        *,
        confidence: float = 0.75,
    ) -> None:
        """Inject a mock intent signal for testing or demos."""
        agent_memory.metadata["mock_signal"] = {**context, "confidence": confidence}
        agent_memory.metadata["intent_opt_in"] = True
        logger.debug("Mock signal set for '%s'", agent_memory.agent_name)

    def _signal_from_text(self, text: str) -> IntentSignal:
        """
        Convert text to an anonymized IntentSignal.

        Uses a local bag-of-chars embedding for pattern matching without
        transmitting the raw text beyond this method's scope.
        """
        embedding = self._text_to_embedding(text)
        match = self.match_intent(embedding)

        context: dict[str, Any] = {
            "source": "text",
            "text_hash": hashlib.sha256(text.encode()).hexdigest()[:12],
            "topic": match[0] if match else "general",
        }
        confidence = match[1] if match else 0.6
        return IntentSignal.from_context(context, confidence=confidence)

    def _text_to_embedding(self, text: str) -> list[float]:
        """Simple deterministic local embedding from character frequencies."""
        text = text.lower()
        dims = len(next(iter(self._patterns.values()), [0.0] * 5))
        vec = [0.0] * dims
        for i, ch in enumerate(text):
            vec[i % dims] += (ord(ch) % 97) / 26.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
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