"""
Tests for the ValueInjector delivery layer.

Run with: python -m pytest tests/test_value_injector.py -v
"""

from __future__ import annotations

import json

import pytest

from core.resonance_agent import IntentSignal, ResonanceOutcome, ResonancePayload
from injection.value_injector import (
    DeliveryMode,
    FormatStyle,
    PayloadFormatter,
    ValueInjector,
)
from integration.arcly_handoff import ArclyHandoff


@pytest.fixture
def sample_payload() -> ResonancePayload:
    return ResonancePayload.from_structured(
        resonance_id="res-abc123",
        summary="User is comparing analytics platforms for a small team.",
        recommended_action="Build a comparison matrix for analytics platforms",
        value_proposition=(
            "Atlas recommends evaluating analytics platforms on cost, "
            "ease of onboarding, and team fit before committing."
        ),
        confidence=0.82,
        resonance_type="comparative",
        quality_estimate=0.74,
        metadata={
            "resource_type": "comparison_matrix",
            "cta_label": "Open comparison guide",
        },
        extra_content={"topic": "analytics platforms", "generation": "template"},
    )


@pytest.fixture
def offer_payload() -> ResonancePayload:
    return ResonancePayload.from_structured(
        resonance_id="res-offer1",
        summary="Purchase intent for enterprise analytics plan.",
        recommended_action="Review the recommended offer for analytics suite",
        value_proposition="Based on your interest, Atlas recommends the enterprise plan.",
        confidence=0.88,
        resonance_type="offer_framed",
        quality_estimate=0.81,
        offer_id="enterprise-analytics",
        metadata={
            "offer_url": "/offers/enterprise-analytics",
            "cta_label": "View enterprise plan",
            "resource_type": "offer",
        },
    )


@pytest.fixture
def signal() -> IntentSignal:
    return IntentSignal.from_context(
        {"topic": "analytics platforms", "matched_intent": "comparison_intent"},
        confidence=0.85,
    )


class TestPayloadFormatter:
    def test_format_simple_includes_core_fields(self, sample_payload: ResonancePayload):
        text = PayloadFormatter.format_simple(sample_payload)
        assert "Comparative" in text
        assert sample_payload.summary in text
        assert sample_payload.value_proposition in text
        assert sample_payload.recommended_action in text
        assert "82%" in text
        assert "74%" in text

    def test_format_rich_includes_sections(self, sample_payload: ResonancePayload):
        text = PayloadFormatter.format_rich(sample_payload)
        assert "Resonant Value" in text
        assert "Summary:" in text
        assert "Next step:" in text
        assert "Confidence:" in text

    def test_structured_card_shape(self, sample_payload: ResonancePayload):
        card = PayloadFormatter.build_structured_card(sample_payload)
        assert card["type"] == "resonance_card"
        assert card["body"] == sample_payload.value_proposition
        assert card["cta"]["label"] == sample_payload.recommended_action
        assert card["metrics"]["confidence"] == pytest.approx(0.82)
        assert "quality:high" in card["badges"]

    def test_offer_package_marks_conversion_ready(self, offer_payload: ResonancePayload):
        pkg = PayloadFormatter.build_offer_package(offer_payload)
        assert pkg["ready_for_conversion"] is True
        assert pkg["offer_url"] == "/offers/enterprise-analytics"
        assert pkg["card"]["offer_id"] == "enterprise-analytics"


class TestDeliveryModes:
    def test_formatted_message_mode(self, sample_payload: ResonancePayload, signal: IntentSignal):
        injector = ValueInjector(
            delivery_mode=DeliveryMode.FORMATTED_MESSAGE,
            echo=False,
        )
        result = injector.inject_payload(sample_payload, signal=signal)
        assert result.mode == DeliveryMode.FORMATTED_MESSAGE
        assert result.delivered is True
        assert "comparison matrix" in result.formatted_message.lower()
        assert result.outcome == ResonanceOutcome.SUCCESS

    def test_structured_card_mode(self, sample_payload: ResonancePayload, signal: IntentSignal):
        injector = ValueInjector(
            delivery_mode=DeliveryMode.STRUCTURED_CARD,
            echo=False,
        )
        result = injector.inject_payload(sample_payload, signal=signal)
        assert result.structured_card["type"] == "resonance_card"
        assert result.structured_card["summary"] == sample_payload.summary

    def test_offer_ready_mode(self, offer_payload: ResonancePayload, signal: IntentSignal):
        injector = ValueInjector(
            delivery_mode=DeliveryMode.OFFER_READY,
            echo=False,
        )
        result = injector.inject_payload(offer_payload, signal=signal)
        assert result.offer_package is not None
        assert result.offer_package["ready_for_conversion"] is True
        assert offer_payload.content.get("offer_package") is not None

    def test_echo_mode_prints(self, sample_payload: ResonancePayload, signal: IntentSignal, capsys):
        injector = ValueInjector(delivery_mode=DeliveryMode.ECHO)
        injector.inject_payload(sample_payload, signal=signal)
        captured = capsys.readouterr()
        assert "ForgeResonance Inject" in captured.out

    def test_rich_format_style(self, sample_payload: ResonancePayload, signal: IntentSignal):
        injector = ValueInjector(
            format_style=FormatStyle.RICH,
            echo=False,
        )
        result = injector.inject_payload(sample_payload, signal=signal)
        assert "Resonant Value" in result.formatted_message

    def test_empty_payload_fails(self, signal: IntentSignal):
        injector = ValueInjector(echo=False)
        empty = ResonancePayload(resonance_id="x", content={})
        result = injector.inject_payload(empty, signal=signal)
        assert result.outcome == ResonanceOutcome.FAILURE
        assert result.delivered is False

    def test_protocol_inject_returns_outcome(self, sample_payload: ResonancePayload, signal: IntentSignal):
        injector = ValueInjector(echo=False)
        outcome = injector.inject(sample_payload, signal)
        assert outcome == ResonanceOutcome.SUCCESS


class TestHooksAndHandoff:
    def test_on_deliver_callback(self, sample_payload: ResonancePayload, signal: IntentSignal):
        delivered: list = []

        def on_deliver(payload: ResonancePayload, result) -> None:
            delivered.append((payload.resonance_id, result.mode))

        injector = ValueInjector(echo=False, on_deliver=on_deliver)
        injector.inject_payload(sample_payload, signal=signal)
        assert delivered == [("res-abc123", DeliveryMode.FORMATTED_MESSAGE)]

    def test_post_inject_hook(self, sample_payload: ResonancePayload, signal: IntentSignal):
        hook_results: list = []

        injector = ValueInjector(echo=False)
        injector.add_post_inject_hook(lambda r: hook_results.append(r.outcome))
        injector.inject_payload(sample_payload, signal=signal)
        assert hook_results == [ResonanceOutcome.SUCCESS]

    def test_prepare_for_handoff_enriches_package(
        self, sample_payload: ResonancePayload, signal: IntentSignal
    ):
        injector = ValueInjector(echo=False, prepare_handoff=True)
        result = injector.inject_payload(sample_payload, signal=signal)
        assert result.handoff_package
        assert result.handoff_package["summary"] == sample_payload.summary
        assert result.handoff_package["signal"]["hash"] == signal.signal_hash
        assert "structured_card" in result.handoff_package
        assert sample_payload.content.get("handoff_package") == result.handoff_package

    def test_arcly_uses_handoff_package(
        self, offer_payload: ResonancePayload, signal: IntentSignal
    ):
        injector = ValueInjector(echo=False, prepare_handoff=True)
        injector.inject_payload(offer_payload, signal=signal)
        handoff = ArclyHandoff(force_dry_run=True)
        content = handoff._resolve_handoff_content(offer_payload)
        assert content["offer_url"] == "/offers/enterprise-analytics"
        assert content["resonance_type"] == "offer_framed"
        assert "structured_card" in content

    def test_last_result_tracked(self, sample_payload: ResonancePayload, signal: IntentSignal):
        injector = ValueInjector(echo=False)
        assert injector.last_result is None
        injector.inject_payload(sample_payload, signal=signal)
        assert injector.last_result is not None
        assert injector.last_result.formatted_message

    def test_injection_metadata_on_payload(
        self, sample_payload: ResonancePayload, signal: IntentSignal
    ):
        injector = ValueInjector(
            delivery_mode=DeliveryMode.STRUCTURED_CARD,
            echo=False,
        )
        injector.inject_payload(sample_payload, signal=signal)
        injection_meta = sample_payload.content.get("injection", {})
        assert injection_meta["mode"] == "structured_card"
        assert injection_meta["structured_card"]["type"] == "resonance_card"


class TestChannelSelection:
    def test_high_confidence_inline_channel(self, sample_payload: ResonancePayload):
        injector = ValueInjector(echo=False)
        high_signal = IntentSignal.from_context({"source": "text"}, confidence=0.9)
        result = injector.inject_payload(sample_payload, signal=high_signal)
        assert result.channel == "inline"

    def test_chat_source_uses_chat_channel(self, sample_payload: ResonancePayload):
        injector = ValueInjector(echo=False)
        chat_signal = IntentSignal.from_context(
            {"source": "chat"}, confidence=0.6
        )
        result = injector.inject_payload(sample_payload, signal=chat_signal)
        assert result.channel == "chat"

    def test_partial_quality_outcome(self, sample_payload: ResonancePayload, signal: IntentSignal):
        sample_payload.quality_estimate = 0.55
        injector = ValueInjector(echo=False)
        result = injector.inject_payload(sample_payload, signal=signal)
        assert result.outcome == ResonanceOutcome.PARTIAL

    def test_injection_result_serializes(self, sample_payload: ResonancePayload, signal: IntentSignal):
        injector = ValueInjector(echo=False)
        result = injector.inject_payload(sample_payload, signal=signal)
        data = result.to_dict()
        parsed = json.loads(json.dumps(data))
        assert parsed["outcome"] == "success"
        assert parsed["mode"] == "formatted_message"