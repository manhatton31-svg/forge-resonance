"""
Tests for the upgraded Intent Harvesting layer.

Run with: python -m pytest tests/test_intent_harvester.py -v
"""

from __future__ import annotations

import pytest

from core.memory import AgentMemory
from core.resonance_agent import IntentSignal
from harvesting.firecrawl_enricher import EnrichmentResult, FirecrawlEnricher
from harvesting.intent_harvester import (
    DEFAULT_INTENT_PATTERNS,
    EmbeddingIntentHarvester,
    PENDING_DETECTED_SIGNAL_KEY,
    RECENT_SIGNALS_KEY,
)


@pytest.fixture
def memory() -> AgentMemory:
    return AgentMemory(agent_id="m1", agent_name="harvest-agent")


@pytest.fixture
def harvester() -> EmbeddingIntentHarvester:
    return EmbeddingIntentHarvester(resonance_threshold=0.3)


class TestDetectIntent:
    def test_detect_purchase_intent(self, harvester: EmbeddingIntentHarvester):
        signal = harvester.detect_intent("I want to buy analytics software for my team")
        assert signal.confidence > 0.0
        assert signal.context_vector["topic"] == "purchase_intent"
        assert "keyword_score" in signal.context_vector
        assert "embedding_score" in signal.context_vector

    def test_detect_research_intent(self, harvester: EmbeddingIntentHarvester):
        signal = harvester.detect_intent("I'm researching how project management tools work")
        assert signal.context_vector["topic"] == "research_intent"
        assert signal.confidence >= 0.35

    def test_detect_comparison_intent(self, harvester: EmbeddingIntentHarvester):
        signal = harvester.detect_intent("Compare Salesforce vs HubSpot for small teams")
        assert signal.context_vector["topic"] == "comparison_intent"

    def test_detect_support_intent(self, harvester: EmbeddingIntentHarvester):
        signal = harvester.detect_intent("I need support with my billing account refund")
        assert signal.context_vector["topic"] == "support_intent"

    def test_empty_text_zero_confidence(self, harvester: EmbeddingIntentHarvester):
        signal = harvester.detect_intent("")
        assert signal.confidence == 0.0

    def test_confidence_in_valid_range(self, harvester: EmbeddingIntentHarvester):
        for text in [
            "buy now",
            "research options",
            "compare plans",
            "fix my broken integration",
            "need a demo",
        ]:
            signal = harvester.detect_intent(text)
            assert 0.0 <= signal.confidence <= 1.0


class TestShouldResonate:
    def test_strong_signal_passes(self, harvester: EmbeddingIntentHarvester):
        signal = harvester.detect_intent("I want to buy enterprise software pricing plan")
        assert harvester.should_resonate(signal)

    def test_weak_signal_rejected(self, harvester: EmbeddingIntentHarvester):
        signal = IntentSignal.from_context({"topic": "x"}, confidence=0.1)
        assert not harvester.should_resonate(signal)

    def test_custom_threshold(self, harvester: EmbeddingIntentHarvester):
        signal = IntentSignal.from_context({"topic": "x"}, confidence=0.5)
        assert harvester.should_resonate(signal, threshold=0.4)
        assert not harvester.should_resonate(signal, threshold=0.6)


class TestIngestion:
    def test_ingest_text(self, harvester: EmbeddingIntentHarvester, memory: AgentMemory):
        signal = harvester.ingest_text(memory, "purchase a new CRM subscription")
        assert signal.confidence > 0.0
        assert PENDING_DETECTED_SIGNAL_KEY in memory.working
        harvested = harvester.harvest(memory)
        assert harvested is not None
        assert harvested.signal_hash == signal.signal_hash

    def test_ingest_from_chat(self, harvester: EmbeddingIntentHarvester, memory: AgentMemory):
        signal = harvester.ingest_from_chat(memory, {
            "text": "Can you compare the top analytics tools?",
            "role": "user",
            "metadata": {"channel": "slack"},
        })
        assert signal.context_vector["source"] == "chat"
        assert signal.context_vector["role"] == "user"
        assert signal.confidence > 0.0

    def test_ingest_from_webhook(self, harvester: EmbeddingIntentHarvester, memory: AgentMemory):
        signal = harvester.ingest_from_webhook(memory, {
            "source": "crm",
            "text": "Customer wants a demo of the platform",
            "url": "https://example.com/pricing",
            "metadata": {"lead_id": "L-42"},
        })
        assert signal.context_vector["source"] == "webhook"
        assert signal.context_vector["webhook_source"] == "crm"
        assert signal.confidence > 0.0

    def test_ingest_empty_chat_returns_zero(self, harvester: EmbeddingIntentHarvester, memory: AgentMemory):
        signal = harvester.ingest_from_chat(memory, {"text": ""})
        assert signal.confidence == 0.0


class TestMultiTurnContext:
    def test_recent_signals_recorded(self, harvester: EmbeddingIntentHarvester, memory: AgentMemory):
        harvester.ingest_text(memory, "I want to buy software")
        harvester.harvest(memory)

        harvester.ingest_text(memory, "What's the pricing for the enterprise plan?")
        signal = harvester.detect_intent(
            "What's the pricing for the enterprise plan?",
            memory,
        )
        assert "prior_topics" in signal.context_vector or signal.confidence > 0.3

    def test_multi_turn_boosts_confidence(
        self, harvester: EmbeddingIntentHarvester, memory: AgentMemory
    ):
        harvester.ingest_text(memory, "purchase analytics tool")
        harvested = harvester.harvest(memory)
        assert harvested is not None

        # Record is in recent signals
        entry = memory.working.get(RECENT_SIGNALS_KEY)
        assert entry is not None

        signal_solo = harvester.detect_intent("purchase analytics tool")
        signal_multi = harvester.detect_intent("purchase analytics tool", memory)
        assert signal_multi.confidence >= signal_solo.confidence


class TestFirecrawlEnrichment:
    def test_extract_urls(self):
        text = "Check https://example.com/pricing and http://test.org/docs"
        urls = FirecrawlEnricher.extract_urls(text)
        assert len(urls) == 2

    def test_enrichment_disabled_graceful(self):
        enricher = FirecrawlEnricher(enabled=False)
        result = enricher.enrich("See https://example.com for details")
        assert result.status in ("disabled", "not_configured", "no_urls")

    def test_enrichment_with_mock_scrape_fn(self, harvester: EmbeddingIntentHarvester):
        def mock_scrape(url: str) -> dict:
            return {"markdown": "Pricing starts at $49 per month for teams."}

        enricher = FirecrawlEnricher(
            enabled=True,
            api_key="test-key",
            scrape_fn=mock_scrape,
        )
        h = EmbeddingIntentHarvester(
            firecrawl_enricher=enricher,
            resonance_threshold=0.3,
        )
        signal = h.detect_intent("Compare plans at https://example.com/pricing")
        assert signal.context_vector.get("firecrawl_status") == "enriched"
        assert "url_summaries" in signal.context_vector

    def test_enrichment_failure_fallback(self):
        def failing_scrape(url: str) -> dict:
            raise ConnectionError("network down")

        enricher = FirecrawlEnricher(
            enabled=True,
            api_key="test-key",
            scrape_fn=failing_scrape,
        )
        result = enricher.enrich("Visit https://example.com")
        assert result.status == "failed"
        assert result.urls_found == ["https://example.com"]


class TestPatternMatching:
    def test_all_default_patterns_have_keywords(self):
        for pattern in DEFAULT_INTENT_PATTERNS:
            assert len(pattern.keywords) >= 5
            assert len(pattern.examples) >= 2
            assert len(pattern.centroid) == 16

    def test_match_intent_embedding(self, harvester: EmbeddingIntentHarvester):
        from harvesting.intent_harvester import _text_to_embedding, EMBEDDING_DIMS

        emb = _text_to_embedding("buy purchase pricing checkout", EMBEDDING_DIMS)
        match = harvester.match_intent(emb)
        assert match is not None
        assert match[0] in {p.label for p in DEFAULT_INTENT_PATTERNS}