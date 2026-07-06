"""
Intent Signal Harvester for ForgeResonance.

Harvests forming or active intent through local-only processing. Signals are
anonymized before leaving the harvest boundary. Optional Firecrawl enrichment
adds URL context when enabled.

Ingestion entry points:
  - ingest_text(text)
  - ingest_from_chat(message)
  - ingest_from_webhook(payload)
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from config import (
    FIRECRAWL_ENABLED,
    INTENT_MULTI_TURN_LIMIT,
    INTENT_RESONANCE_THRESHOLD,
    INTENT_SIMILARITY_THRESHOLD,
    WORKING_MEMORY_TTL_SECONDS,
)
from core.memory import AgentMemory, MemoryEntry
from core.resonance_agent import IntentHarvesterProtocol, IntentSignal
from harvesting.firecrawl_enricher import EnrichmentResult, FirecrawlEnricher
from utils.logging import setup_logging

logger = setup_logging("forge.harvesting")

# Working-memory keys
PENDING_INTENT_KEY = "pending_intent_text"
INTENT_EMBEDDING_KEY = "intent_embedding"
RECENT_SIGNALS_KEY = "recent_intent_signals"
PENDING_DETECTED_SIGNAL_KEY = "pending_detected_signal"

EMBEDDING_DIMS = 16


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _text_to_embedding(text: str, dims: int = EMBEDDING_DIMS) -> list[float]:
    """
    Deterministic local embedding using token hashing + char distribution.

    Privacy-preserving: computed locally, never sent to remote services.
    """
    text = text.lower()
    vec = [0.0] * dims
    tokens = _tokenize(text)

    for token in tokens:
        bucket = hash(token) % dims
        vec[bucket] += 1.0 + len(token) * 0.1

    for i, ch in enumerate(text):
        vec[(ord(ch) + i) % dims] += (ord(ch) % 97) / 97.0 * 0.05

    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _build_centroid(keywords: tuple[str, ...], examples: tuple[str, ...]) -> tuple[float, ...]:
    """Build a centroid embedding from keywords and example phrases."""
    combined = " ".join(list(keywords) + list(examples))
    return tuple(_text_to_embedding(combined, EMBEDDING_DIMS))


@dataclass(frozen=True)
class IntentPattern:
    """A known intent category with keywords, examples, and a centroid embedding."""

    label: str
    keywords: tuple[str, ...]
    examples: tuple[str, ...]
    centroid: tuple[float, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.centroid:
            object.__setattr__(self, "centroid", _build_centroid(self.keywords, self.examples))


# Rich default patterns with keywords and example phrases
DEFAULT_INTENT_PATTERNS: tuple[IntentPattern, ...] = (
    IntentPattern(
        label="purchase_intent",
        keywords=(
            "buy", "purchase", "order", "pricing", "checkout", "subscribe",
            "trial", "license", "cart", "payment", "cost", "plan",
        ),
        examples=(
            "I want to buy analytics software for my team",
            "What's the pricing for the enterprise plan?",
            "Ready to purchase and need a quote",
        ),
    ),
    IntentPattern(
        label="research_intent",
        keywords=(
            "research", "learn", "explore", "understand", "overview", "guide",
            "tutorial", "how does", "what is", "documentation", "read about",
        ),
        examples=(
            "I'm researching project management tools",
            "Can you help me understand how this works?",
            "Looking for an overview of AI analytics platforms",
        ),
    ),
    IntentPattern(
        label="comparison_intent",
        keywords=(
            "compare", "versus", "vs", "alternative", "better than", "difference",
            "which one", "pros and cons", "evaluate", "benchmark",
        ),
        examples=(
            "Compare HubSpot vs Salesforce for small teams",
            "Which analytics tool is better for startups?",
            "I need pros and cons of the top three options",
        ),
    ),
    IntentPattern(
        label="problem_solving_intent",
        keywords=(
            "problem", "issue", "fix", "solve", "broken", "error", "stuck",
            "help me", "can't", "doesn't work", "troubleshoot", "debug",
        ),
        examples=(
            "I have a problem with my current workflow",
            "My integration is broken and I need to fix it",
            "Stuck trying to solve a data pipeline issue",
        ),
    ),
    IntentPattern(
        label="support_intent",
        keywords=(
            "support", "help", "ticket", "contact", "refund", "billing",
            "account", "cancel", "status", "customer service", "assist",
        ),
        examples=(
            "I need support with my billing account",
            "Open a ticket for a refund request",
            "Contact customer service about my subscription",
        ),
    ),
    IntentPattern(
        label="evaluation_intent",
        keywords=(
            "demo", "trial", "test", "pilot", "proof of concept", "poc",
            "evaluate", "assessment", "review", "sample", "try out",
        ),
        examples=(
            "I'd like a demo before we commit",
            "Can we run a pilot program for 30 days?",
            "Want to evaluate this for our engineering team",
        ),
    ),
)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class IntentMatch:
    """Result of pattern matching against text."""

    label: str
    keyword_score: float
    embedding_score: float
    combined_score: float
    matched_keywords: list[str] = field(default_factory=list)


class IntentHarvester(IntentHarvesterProtocol):
    """
    Privacy-preserving intent harvester base class.

    Processes local signals into anonymized IntentSignal objects.
    """

    def __init__(self, opt_in_required: bool = True) -> None:
        self._opt_in_required = opt_in_required
        self._firecrawl_enabled = FIRECRAWL_ENABLED

    def harvest(self, agent_memory: AgentMemory) -> IntentSignal | None:
        """Sense intent from local context. Returns None if no signal detected."""
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

        return context

    def enable_opt_in(self, agent_memory: AgentMemory) -> None:
        """Record explicit user opt-in for intent harvesting."""
        agent_memory.metadata["intent_opt_in"] = True
        logger.info("Intent opt-in enabled for agent '%s'", agent_memory.agent_name)


class EmbeddingIntentHarvester(IntentHarvester):
    """
    Production-ready embedding harvester with multi-turn context, ingestion
    APIs, Firecrawl enrichment, and confidence-gated resonance decisions.
    """

    def __init__(
        self,
        patterns: tuple[IntentPattern, ...] | None = None,
        similarity_threshold: float | None = None,
        resonance_threshold: float | None = None,
        opt_in_required: bool = False,
        firecrawl_enricher: FirecrawlEnricher | None = None,
        multi_turn_limit: int | None = None,
    ) -> None:
        super().__init__(opt_in_required=opt_in_required)
        self._patterns = patterns or DEFAULT_INTENT_PATTERNS
        self._threshold = similarity_threshold or INTENT_SIMILARITY_THRESHOLD
        self._resonance_threshold = resonance_threshold or INTENT_RESONANCE_THRESHOLD
        self._multi_turn_limit = multi_turn_limit or INTENT_MULTI_TURN_LIMIT
        self._enricher = firecrawl_enricher or FirecrawlEnricher()

    # ------------------------------------------------------------------
    # Public API — detection & gating
    # ------------------------------------------------------------------

    def detect_intent(
        self,
        text: str,
        agent_memory: AgentMemory | None = None,
    ) -> IntentSignal:
        """
        Analyze text and return a structured IntentSignal with confidence.

        Combines keyword matching, embedding similarity, multi-turn context,
        and optional Firecrawl URL enrichment.
        """
        text = text.strip()
        if not text:
            return IntentSignal.from_context(
                {"topic": "empty", "source": "text"},
                confidence=0.0,
            )

        match = self._match_text(text)
        confidence = self._compute_confidence(match, text, agent_memory)

        context: dict[str, Any] = {
            "source": "text",
            "topic": match.label,
            "text_hash": hashlib.sha256(text.encode()).hexdigest()[:12],
            "keyword_score": round(match.keyword_score, 3),
            "embedding_score": round(match.embedding_score, 3),
            "matched_keywords": match.matched_keywords[:5],
        }

        if agent_memory:
            self._apply_multi_turn_context(context, match.label, agent_memory)

        if self._firecrawl_enabled or self._enricher.is_available:
            enrichment = self._enricher.enrich(text)
            confidence = self._merge_enrichment(context, enrichment, confidence)

        signal = IntentSignal.from_context(context, confidence=confidence)
        logger.info(
            "detect_intent: topic=%s confidence=%.2f keywords=%s",
            match.label,
            confidence,
            match.matched_keywords[:3],
        )
        return signal

    def should_resonate(
        self,
        signal: IntentSignal,
        threshold: float | None = None,
    ) -> bool:
        """
        Decide whether a signal is strong enough to proceed to resonance.

        Configurable via INTENT_RESONANCE_THRESHOLD or per-call override.
        """
        cutoff = threshold if threshold is not None else self._resonance_threshold
        return signal.confidence >= cutoff

    # ------------------------------------------------------------------
    # Ingestion entry points
    # ------------------------------------------------------------------

    def ingest_text(self, agent_memory: AgentMemory, text: str) -> IntentSignal:
        """Ingest raw text intent and queue for the next harvest cycle."""
        signal = self.detect_intent(text, agent_memory)
        self._queue_detected_signal(agent_memory, signal, raw_text=text)
        agent_memory.metadata["intent_opt_in"] = True
        logger.debug("ingest_text: queued signal hash=%s", signal.signal_hash)
        return signal

    def ingest_from_chat(
        self,
        agent_memory: AgentMemory,
        message: dict[str, Any],
    ) -> IntentSignal:
        """
        Ingest intent from a chat message.

        Expected shape: ``{"text": "...", "role": "user", "metadata": {...}}``
        """
        text = str(message.get("text", "")).strip()
        role = message.get("role", "user")
        meta = message.get("metadata") or {}

        if not text:
            return IntentSignal.from_context({"source": "chat", "topic": "empty"}, confidence=0.0)

        prefix = f"[{role}] " if role else ""
        signal = self.detect_intent(f"{prefix}{text}", agent_memory)
        signal.context_vector["source"] = "chat"
        signal.context_vector["role"] = role
        if meta:
            signal.context_vector["chat_meta"] = {
                k: v for k, v in meta.items() if k not in ("text", "raw_pii")
            }

        self._queue_detected_signal(agent_memory, signal, raw_text=text)
        agent_memory.metadata["intent_opt_in"] = True
        logger.debug("ingest_from_chat: role=%s hash=%s", role, signal.signal_hash)
        return signal

    def ingest_from_webhook(
        self,
        agent_memory: AgentMemory,
        payload: dict[str, Any],
    ) -> IntentSignal:
        """
        Ingest intent from a webhook payload.

        Expected shape::
            {
                "source": "crm|form|api",
                "text": "...",
                "url": "https://...",
                "metadata": {...}
            }
        """
        text = str(payload.get("text", "")).strip()
        source = payload.get("source", "webhook")
        url = payload.get("url", "")
        meta = payload.get("metadata") or {}

        combined = text
        if url:
            combined = f"{text} {url}".strip()

        if not combined:
            return IntentSignal.from_context(
                {"source": "webhook", "topic": "empty"},
                confidence=0.0,
            )

        signal = self.detect_intent(combined, agent_memory)
        signal.context_vector["source"] = "webhook"
        signal.context_vector["webhook_source"] = source
        if meta:
            signal.context_vector["webhook_meta"] = meta

        self._queue_detected_signal(agent_memory, signal, raw_text=combined)
        agent_memory.metadata["intent_opt_in"] = True
        logger.debug(
            "ingest_from_webhook: source=%s hash=%s",
            source,
            signal.signal_hash,
        )
        return signal

    # ------------------------------------------------------------------
    # Harvest cycle
    # ------------------------------------------------------------------

    def harvest(self, agent_memory: AgentMemory) -> IntentSignal | None:
        """Harvest intent from queued signals, embeddings, or mock data."""
        if self._opt_in_required and not agent_memory.metadata.get("intent_opt_in"):
            logger.debug("Embedding harvest skipped: opt-in required")
            return None

        # 1. Pre-detected signal (from ingest_* methods)
        pending_signal = agent_memory.working.get(PENDING_DETECTED_SIGNAL_KEY)
        if pending_signal and not pending_signal.is_expired():
            data = pending_signal.value
            if isinstance(data, dict):
                signal = IntentSignal.from_context(
                    data.get("context", {}),
                    confidence=float(data.get("confidence", 0.5)),
                )
                self._record_signal(agent_memory, signal)
                logger.info("Harvested pre-detected signal: hash=%s", signal.signal_hash)
                return signal

        # 2. Legacy pending text (queue_intent_text)
        pending = agent_memory.working.get(PENDING_INTENT_KEY)
        if pending and not pending.is_expired():
            signal = self.detect_intent(str(pending.value), agent_memory)
            self._record_signal(agent_memory, signal)
            return signal

        # 3. Mock signal
        mock = agent_memory.metadata.get("mock_signal")
        if isinstance(mock, dict) and mock:
            mock_copy = dict(mock)
            confidence = float(mock_copy.pop("confidence", 0.75))
            signal = IntentSignal.from_context(mock_copy, confidence=confidence)
            self._record_signal(agent_memory, signal)
            return signal

        # 4. Raw embedding vector
        embedding_entry = agent_memory.working.get(INTENT_EMBEDDING_KEY)
        if embedding_entry and not embedding_entry.is_expired():
            match = self._match_embedding(embedding_entry.value)
            if match:
                signal = IntentSignal.from_context(
                    {
                        "matched_intent": match.label,
                        "source": "embedding",
                        "embedding_score": round(match.embedding_score, 3),
                    },
                    confidence=match.combined_score,
                )
                self._record_signal(agent_memory, signal)
                return signal

        return super().harvest(agent_memory)

    # ------------------------------------------------------------------
    # Static helpers (backward compatible)
    # ------------------------------------------------------------------

    @staticmethod
    def queue_intent_text(agent_memory: AgentMemory, text: str) -> None:
        """Queue raw text for the next harvest cycle (legacy API)."""
        agent_memory.working[PENDING_INTENT_KEY] = MemoryEntry(
            key=PENDING_INTENT_KEY,
            value=text.strip(),
            expires_at=datetime.now(timezone.utc) + timedelta(
                seconds=WORKING_MEMORY_TTL_SECONDS
            ),
        )
        agent_memory.metadata["intent_opt_in"] = True

    @staticmethod
    def set_mock_signal(
        agent_memory: AgentMemory,
        context: dict[str, Any],
        *,
        confidence: float = 0.75,
    ) -> None:
        """Inject a mock intent signal for testing."""
        agent_memory.metadata["mock_signal"] = {**context, "confidence": confidence}
        agent_memory.metadata["intent_opt_in"] = True

    def match_intent(self, embedding: list[float]) -> tuple[str, float] | None:
        """Match an embedding against known patterns (public API)."""
        result = self._match_embedding(embedding)
        if result and result.combined_score >= self._threshold:
            return result.label, result.combined_score
        return None

    # ------------------------------------------------------------------
    # Internal — matching & confidence
    # ------------------------------------------------------------------

    def _match_text(self, text: str) -> IntentMatch:
        """Score text against all intent patterns."""
        tokens = set(_tokenize(text))
        embedding = _text_to_embedding(text, EMBEDDING_DIMS)
        return self._score_patterns(tokens, embedding, text)

    def _match_embedding(self, embedding: list[float]) -> IntentMatch | None:
        """Score a pre-computed embedding."""
        if not isinstance(embedding, list):
            return None
        return self._score_patterns(set(), embedding, "")

    def _score_patterns(
        self,
        tokens: set[str],
        embedding: list[float],
        raw_text: str,
    ) -> IntentMatch:
        best = IntentMatch("general", 0.0, 0.0, 0.0)

        for pattern in self._patterns:
            matched_kw = [
                kw for kw in pattern.keywords
                if kw in tokens or (raw_text and kw in raw_text.lower())
            ]
            keyword_score = len(matched_kw) / max(len(pattern.keywords), 1)
            if len(matched_kw) >= 2:
                keyword_score = min(1.0, keyword_score + 0.25)

            centroid = list(pattern.centroid)
            embedding_score = _cosine_similarity(embedding, centroid)

            # Embedding-only path (no text tokens): trust cosine similarity directly
            if not tokens and not raw_text:
                combined = embedding_score
            else:
                combined = keyword_score * 0.5 + embedding_score * 0.5
                if keyword_score > 0.15 and embedding_score > 0.4:
                    combined = min(1.0, combined + 0.12)

            if combined > best.combined_score:
                best = IntentMatch(
                    label=pattern.label,
                    keyword_score=keyword_score,
                    embedding_score=embedding_score,
                    combined_score=combined,
                    matched_keywords=matched_kw,
                )

        return best

    def _compute_confidence(
        self,
        match: IntentMatch,
        text: str,
        agent_memory: AgentMemory | None,
    ) -> float:
        """Map match scores to a 0.0–1.0 confidence value."""
        base = match.combined_score

        # Length signal — very short text is less confident
        word_count = len(_tokenize(text))
        if word_count < 3:
            base *= 0.7
        elif word_count > 8:
            base = min(1.0, base + 0.05)

        # Multi-turn boost
        if agent_memory:
            recent = self._get_recent_signals(agent_memory)
            same_topic = sum(
                1 for s in recent if s.get("topic") == match.label
            )
            if same_topic > 0:
                base = min(1.0, base + 0.08 * min(same_topic, 2))

        # General intent gets a floor but not a ceiling
        if match.label == "general":
            base = max(0.35, min(0.55, base))

        return round(max(0.0, min(1.0, base)), 3)

    def _apply_multi_turn_context(
        self,
        context: dict[str, Any],
        topic: str,
        agent_memory: AgentMemory,
    ) -> None:
        """Annotate context with multi-turn disambiguation data."""
        recent = self._get_recent_signals(agent_memory)
        if not recent:
            return

        prior_topics = [s.get("topic") for s in recent if s.get("topic")]
        context["prior_topics"] = prior_topics[-3:]
        context["turn_count"] = len(recent) + 1

        if prior_topics and prior_topics[-1] == topic:
            context["topic_continuity"] = True

    def _merge_enrichment(
        self,
        context: dict[str, Any],
        enrichment: EnrichmentResult,
        confidence: float,
    ) -> float:
        """Merge Firecrawl enrichment into context; return adjusted confidence."""
        context["firecrawl_status"] = enrichment.status
        if enrichment.urls_found:
            context["urls_found"] = len(enrichment.urls_found)

        if enrichment.summaries:
            context["url_summaries"] = {
                hashlib.sha256(url.encode()).hexdigest()[:8]: summary
                for url, summary in enrichment.summaries.items()
            }
            return min(1.0, confidence + 0.05)

        return confidence

    # ------------------------------------------------------------------
    # Internal — memory helpers
    # ------------------------------------------------------------------

    def _queue_detected_signal(
        self,
        agent_memory: AgentMemory,
        signal: IntentSignal,
        *,
        raw_text: str = "",
    ) -> None:
        """Store a detected signal for the next harvest cycle."""
        agent_memory.working[PENDING_DETECTED_SIGNAL_KEY] = MemoryEntry(
            key=PENDING_DETECTED_SIGNAL_KEY,
            value={
                "context": signal.context_vector,
                "confidence": signal.confidence,
                "signal_hash": signal.signal_hash,
            },
            expires_at=datetime.now(timezone.utc) + timedelta(
                seconds=WORKING_MEMORY_TTL_SECONDS
            ),
        )
        if raw_text:
            agent_memory.working[PENDING_INTENT_KEY] = MemoryEntry(
                key=PENDING_INTENT_KEY,
                value=raw_text,
                expires_at=datetime.now(timezone.utc) + timedelta(
                    seconds=WORKING_MEMORY_TTL_SECONDS
                ),
            )

    def _record_signal(self, agent_memory: AgentMemory, signal: IntentSignal) -> None:
        """Append signal to multi-turn short-term memory."""
        entry = agent_memory.working.get(RECENT_SIGNALS_KEY)
        recent: list[dict[str, Any]] = []
        if entry and not entry.is_expired() and isinstance(entry.value, list):
            recent = list(entry.value)

        recent.append({
            "hash": signal.signal_hash,
            "topic": signal.context_vector.get("topic", "unknown"),
            "confidence": signal.confidence,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        recent = recent[-self._multi_turn_limit :]

        agent_memory.working[RECENT_SIGNALS_KEY] = MemoryEntry(
            key=RECENT_SIGNALS_KEY,
            value=recent,
            expires_at=datetime.now(timezone.utc) + timedelta(
                seconds=WORKING_MEMORY_TTL_SECONDS
            ),
        )

    def _get_recent_signals(self, agent_memory: AgentMemory) -> list[dict[str, Any]]:
        entry = agent_memory.working.get(RECENT_SIGNALS_KEY)
        if entry and not entry.is_expired() and isinstance(entry.value, list):
            return entry.value
        return []