"""
Offer framing for commercial intent signals.

Tags payloads as offer-ready and embeds conversion metadata when the
harvested intent indicates purchase or evaluation intent.
"""

from __future__ import annotations

from typing import Any

from core.resonance_agent import IntentSignal, ResonancePayload

COMMERCIAL_INTENT_LABELS: frozenset[str] = frozenset({
    "purchase_intent",
    "evaluation_intent",
})

COMMERCIAL_RESONANCE_TYPES: frozenset[str] = frozenset({
    "offer_framed",
})


class OfferFramer:
    """Prepare resonance payloads for Arcly conversion handoff."""

    @staticmethod
    def is_commercial_intent(signal: IntentSignal) -> bool:
        """True when signal indicates purchase or evaluation intent."""
        cv = signal.context_vector
        matched = str(cv.get("matched_intent", ""))
        topic = str(cv.get("topic", ""))
        if matched in COMMERCIAL_INTENT_LABELS:
            return True
        if topic in COMMERCIAL_INTENT_LABELS:
            return True
        return any(kw in topic for kw in ("purchase", "evaluation", "pricing"))

    @staticmethod
    def should_frame(payload: ResonancePayload, signal: IntentSignal) -> bool:
        """Whether to apply offer framing to this payload."""
        if payload.resonance_type in COMMERCIAL_RESONANCE_TYPES:
            return True
        if payload.content.get("resonance_type") == "offer_framed":
            return True
        return OfferFramer.is_commercial_intent(signal)

    @staticmethod
    def build_offer_bundle(
        payload: ResonancePayload,
        signal: IntentSignal | None = None,
    ) -> dict[str, Any]:
        """
        Build normalized offer metadata for injection and Arcly handoff.

        Fields: offer_id, offer_url, cta_text, value_prop, topic, intent_hash.
        """
        meta = dict(payload.metadata or payload.content.get("metadata") or {})
        topic = (
            payload.content.get("topic")
            or signal.context_vector.get("topic", "") if signal else ""
        )
        slug = str(topic).replace("_intent", "").replace(" ", "-").lower() or "offer"
        offer_id = payload.offer_id or meta.get("offer_id") or f"offer-{slug}"
        offer_url = meta.get("offer_url") or f"/offers/{slug}"
        return {
            "offer_ready": True,
            "offer_id": offer_id,
            "offer_url": offer_url,
            "cta_text": meta.get("cta_label") or meta.get("cta_text", "View recommended offer"),
            "value_prop": payload.value_proposition or payload.content.get("message", ""),
            "summary": payload.summary,
            "recommended_action": payload.recommended_action,
            "topic": topic,
            "intent_hash": signal.signal_hash if signal else None,
            "confidence": payload.confidence,
            "quality_estimate": payload.quality_estimate,
        }

    @classmethod
    def frame(
        cls,
        payload: ResonancePayload,
        signal: IntentSignal,
    ) -> ResonancePayload:
        """
        Tag payload as offer-ready and merge offer metadata when commercial.

        Mutates payload in place and returns it for chaining.
        """
        if not cls.should_frame(payload, signal):
            return payload

        bundle = cls.build_offer_bundle(payload, signal)
        payload.resonance_type = "offer_framed"
        payload.offer_id = bundle["offer_id"]
        payload.metadata = {**payload.metadata, **bundle}

        payload.content["resonance_type"] = "offer_framed"
        payload.content["offer_ready"] = True
        payload.content["offer_bundle"] = bundle
        payload.content["metadata"] = {
            **payload.content.get("metadata", {}),
            "offer_id": bundle["offer_id"],
            "offer_url": bundle["offer_url"],
            "cta_label": bundle["cta_text"],
            "cta_text": bundle["cta_text"],
            "value_prop": bundle["value_prop"],
        }
        if not payload.content.get("offer_id"):
            payload.content["offer_id"] = bundle["offer_id"]

        return payload