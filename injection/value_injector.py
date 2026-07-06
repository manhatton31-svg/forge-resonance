"""
Contextual Value Injection System.

Delivers generated resonance payloads into the user's active context at
the precise moment intent is forming — preemptive utility, not interruption.

Supports multiple delivery modes (echo, formatted_message, structured_card,
offer_ready), formatting templates, delivery hooks, and Arcly handoff prep.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from core.resonance_agent import (
    IntentSignal,
    ResonanceOutcome,
    ResonancePayload,
    ValueInjectorProtocol,
)
from integration.offer_framer import OfferFramer
from utils.logging import setup_logging

logger = setup_logging("forge.injection")

PostInjectHook = Callable[["InjectionResult"], None]
OnDeliverCallback = Callable[[ResonancePayload, "InjectionResult"], None]


class DeliveryMode(str, Enum):
    """How resonant value is rendered and delivered."""

    ECHO = "echo"
    FORMATTED_MESSAGE = "formatted_message"
    STRUCTURED_CARD = "structured_card"
    OFFER_READY = "offer_ready"


class FormatStyle(str, Enum):
    """Message formatting density."""

    SIMPLE = "simple"
    RICH = "rich"


@dataclass
class InjectionResult:
    """Structured outcome of a value injection attempt."""

    outcome: ResonanceOutcome
    mode: DeliveryMode
    channel: str
    delivered: bool
    formatted_message: str = ""
    structured_card: dict[str, Any] = field(default_factory=dict)
    offer_package: dict[str, Any] | None = None
    handoff_package: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging, APIs, or episodic storage."""
        return {
            "outcome": self.outcome.value,
            "mode": self.mode.value,
            "channel": self.channel,
            "delivered": self.delivered,
            "formatted_message": self.formatted_message,
            "structured_card": self.structured_card,
            "offer_package": self.offer_package,
            "handoff_package": self.handoff_package,
            "metadata": self.metadata,
        }


class PayloadFormatter:
    """Build human-readable and UI-ready views from ResonancePayload fields."""

    @staticmethod
    def resolve_fields(payload: ResonancePayload) -> dict[str, Any]:
        """Merge structured dataclass fields with content dict fallbacks."""
        content = payload.content or {}
        return {
            "summary": payload.summary or content.get("summary", ""),
            "recommended_action": (
                payload.recommended_action or content.get("recommended_action", "")
            ),
            "value_proposition": (
                payload.value_proposition
                or content.get("value_proposition")
                or content.get("message", "")
            ),
            "confidence": payload.confidence or content.get("confidence", 0.0),
            "resonance_type": (
                payload.resonance_type or content.get("resonance_type", "educational")
            ),
            "quality_estimate": payload.quality_estimate,
            "metadata": {**content.get("metadata", {}), **(payload.metadata or {})},
            "offer_id": payload.offer_id or content.get("offer_id"),
            "resonance_id": payload.resonance_id,
            "topic": content.get("topic", ""),
        }

    @classmethod
    def format_simple(cls, payload: ResonancePayload) -> str:
        """Compact markdown-friendly message."""
        f = cls.resolve_fields(payload)
        lines = [
            f"**{f['resonance_type'].replace('_', ' ').title()}**",
        ]
        if f["summary"]:
            lines.append(f["summary"])
        if f["value_proposition"]:
            lines.append("")
            lines.append(f["value_proposition"])
        if f["recommended_action"]:
            lines.append("")
            lines.append(f"→ **{f['recommended_action']}**")
        metrics = []
        if f["confidence"]:
            metrics.append(f"confidence {f['confidence']:.0%}")
        if f["quality_estimate"]:
            metrics.append(f"quality {f['quality_estimate']:.0%}")
        if metrics:
            lines.append("")
            lines.append(f"({', '.join(metrics)})")
        return "\n".join(lines)

    @classmethod
    def format_rich(cls, payload: ResonancePayload) -> str:
        """Expanded message with labeled sections."""
        f = cls.resolve_fields(payload)
        divider = "─" * 40
        lines = [
            divider,
            "🔮 Resonant Value",
            divider,
        ]
        if f["resonance_type"]:
            lines.append(
                f"Type: {f['resonance_type'].replace('_', ' ').title()}"
            )
        if f["topic"]:
            lines.append(f"Topic: {f['topic']}")
        if f["summary"]:
            lines.append(f"Summary: {f['summary']}")
        if f["value_proposition"]:
            lines.append("")
            lines.append(f["value_proposition"])
        if f["recommended_action"]:
            lines.append("")
            lines.append(f"Next step: {f['recommended_action']}")
        lines.append("")
        lines.append(
            f"Confidence: {f['confidence']:.0%}  |  "
            f"Quality: {f['quality_estimate']:.0%}"
        )
        offer_url = f["metadata"].get("offer_url")
        if offer_url:
            cta = f["metadata"].get("cta_label", "View offer")
            lines.append(f"Offer: {cta} → {offer_url}")
        lines.append(divider)
        return "\n".join(lines)

    @classmethod
    def build_structured_card(cls, payload: ResonancePayload) -> dict[str, Any]:
        """Dict ready for chat widgets, sidebars, or in-app cards."""
        f = cls.resolve_fields(payload)
        meta = f["metadata"]
        quality = f["quality_estimate"]
        quality_tier = (
            "high" if quality >= 0.7 else "medium" if quality >= 0.4 else "low"
        )
        card: dict[str, Any] = {
            "type": "resonance_card",
            "resonance_id": f["resonance_id"],
            "title": f["summary"] or f["value_proposition"][:80],
            "body": f["value_proposition"],
            "summary": f["summary"],
            "resonance_type": f["resonance_type"],
            "badges": [
                f["resonance_type"].replace("_", " "),
                f"quality:{quality_tier}",
            ],
            "metrics": {
                "confidence": round(f["confidence"], 3),
                "quality_estimate": round(quality, 3),
            },
        }
        if f["recommended_action"]:
            card["cta"] = {
                "label": f["recommended_action"],
                "url": meta.get("offer_url"),
            }
        if meta:
            card["metadata"] = meta
        if f["offer_id"]:
            card["offer_id"] = f["offer_id"]
        return card

    @classmethod
    def build_offer_package(cls, payload: ResonancePayload) -> dict[str, Any]:
        """Package offer metadata and links for conversion-ready delivery."""
        f = cls.resolve_fields(payload)
        meta = f["metadata"]
        offer_url = meta.get("offer_url")
        offer_id = f["offer_id"] or meta.get("offer_id")
        has_offer = bool(offer_url or offer_id)
        return {
            "ready_for_conversion": has_offer
            and f["resonance_type"] == "offer_framed",
            "offer_id": offer_id,
            "offer_url": offer_url,
            "cta_label": meta.get("cta_label", "View recommended offer"),
            "resonance_type": f["resonance_type"],
            "message": cls.format_simple(payload),
            "card": cls.build_structured_card(payload),
            "quality_estimate": f["quality_estimate"],
            "confidence": f["confidence"],
        }


class ValueInjector(ValueInjectorProtocol):
    """
    Multi-mode value injector for ForgeResonance.

    Formats structured ResonancePayload fields into deliverable output,
    supports hooks for downstream systems, and prepares enriched packages
    for Arcly handoff.
    """

    def __init__(
        self,
        channels: list[str] | None = None,
        *,
        delivery_mode: DeliveryMode | str = DeliveryMode.FORMATTED_MESSAGE,
        format_style: FormatStyle | str = FormatStyle.SIMPLE,
        echo: bool = False,
        prepare_handoff: bool = True,
        on_deliver: OnDeliverCallback | None = None,
        post_inject_hooks: list[PostInjectHook] | None = None,
    ) -> None:
        self._channels = channels or ["inline", "sidebar"]
        self._delivery_mode = DeliveryMode(delivery_mode)
        self._format_style = FormatStyle(format_style)
        self._echo = echo or self._delivery_mode == DeliveryMode.ECHO
        self._prepare_handoff = prepare_handoff
        self._on_deliver = on_deliver
        self._post_inject_hooks: list[PostInjectHook] = list(post_inject_hooks or [])
        self._last_result: InjectionResult | None = None

    @property
    def last_result(self) -> InjectionResult | None:
        """Most recent injection result (for handoff and observability)."""
        return self._last_result

    @property
    def delivery_mode(self) -> DeliveryMode:
        return self._delivery_mode

    def add_post_inject_hook(self, hook: PostInjectHook) -> None:
        """Register a hook invoked after each successful injection pipeline."""
        self._post_inject_hooks.append(hook)

    def inject(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
    ) -> ResonanceOutcome:
        """Protocol entry point — delegates to ``inject_payload``."""
        result = self.inject_payload(payload, signal=signal)
        return result.outcome

    def inject_payload(
        self,
        payload: ResonancePayload,
        *,
        signal: IntentSignal | None = None,
        channel: str | None = None,
        mode: DeliveryMode | str | None = None,
    ) -> InjectionResult:
        """
        Primary injection API returning a structured ``InjectionResult``.

        Formats the payload per delivery mode, optionally echoes to stdout,
        fires hooks, and attaches a handoff package to the payload.
        """
        if signal is not None:
            OfferFramer.frame(payload, signal)

        if not payload.content and not payload.value_proposition:
            logger.warning(
                "Empty payload for resonance %s; injection failed",
                payload.resonance_id,
            )
            result = InjectionResult(
                outcome=ResonanceOutcome.FAILURE,
                mode=self._delivery_mode,
                channel=channel or self._channels[0],
                delivered=False,
            )
            self._last_result = result
            return result

        active_mode = DeliveryMode(mode) if mode else self._delivery_mode
        active_channel = channel or (
            self._select_channel(signal) if signal else self._channels[0]
        )

        formatted = self._format_message(payload)
        card = PayloadFormatter.build_structured_card(payload)
        offer_pkg = None
        if active_mode == DeliveryMode.OFFER_READY or payload.content.get("offer_ready"):
            offer_pkg = PayloadFormatter.build_offer_package(payload)
            if signal:
                offer_pkg = {**OfferFramer.build_offer_bundle(payload, signal), **offer_pkg}

        delivery_body = self._resolve_delivery_body(
            active_mode, formatted, card, offer_pkg, payload
        )

        logger.info(
            "INJECT [%s] mode=%s resonance=%s channel=%s quality=%.2f "
            "confidence=%.2f\n  → %s",
            payload.content.get("type", "value"),
            active_mode.value,
            payload.resonance_id,
            active_channel,
            payload.quality_estimate,
            payload.confidence,
            delivery_body[:200],
        )

        delivered = True
        if self._echo or active_mode == DeliveryMode.ECHO:
            self._echo_delivery(active_channel, delivery_body, payload, signal)

        handoff_package = {}
        if self._prepare_handoff:
            handoff_package = self.prepare_for_handoff(
                payload, signal=signal, formatted_message=formatted, card=card
            )
            payload.content["handoff_package"] = handoff_package
        payload.content["injection"] = {
            "mode": active_mode.value,
            "channel": active_channel,
            "formatted_message": formatted,
            "structured_card": card,
        }
        if offer_pkg:
            payload.content["offer_package"] = offer_pkg

        outcome = self._outcome_from_quality(payload.quality_estimate)

        result = InjectionResult(
            outcome=outcome,
            mode=active_mode,
            channel=active_channel,
            delivered=delivered,
            formatted_message=formatted,
            structured_card=card,
            offer_package=offer_pkg,
            handoff_package=handoff_package,
            metadata={
                "resonance_id": payload.resonance_id,
                "resonance_type": payload.resonance_type,
                "quality_estimate": payload.quality_estimate,
                "confidence": payload.confidence,
            },
        )
        self._last_result = result

        if self._on_deliver:
            try:
                self._on_deliver(payload, result)
            except Exception as exc:
                logger.error("on_deliver callback failed: %s", exc)
                result.outcome = ResonanceOutcome.FAILURE
                result.delivered = False

        for hook in self._post_inject_hooks:
            try:
                hook(result)
            except Exception as exc:
                logger.error("post_inject hook failed: %s", exc)

        return result

    def prepare_for_handoff(
        self,
        payload: ResonancePayload,
        *,
        signal: IntentSignal | None = None,
        formatted_message: str | None = None,
        card: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Build an enriched package for ``ArclyHandoff``.

        Merges structured payload fields, injection formatting, signal context,
        and offer metadata into a single handoff-ready dict.
        """
        formatted = formatted_message or self._format_message(payload)
        structured_card = card or PayloadFormatter.build_structured_card(payload)
        fields = PayloadFormatter.resolve_fields(payload)

        package: dict[str, Any] = {
            "resonance_id": payload.resonance_id,
            "message": formatted,
            "summary": fields["summary"],
            "recommended_action": fields["recommended_action"],
            "value_proposition": fields["value_proposition"],
            "resonance_type": fields["resonance_type"],
            "confidence": fields["confidence"],
            "quality_estimate": fields["quality_estimate"],
            "structured_card": structured_card,
            "metadata": fields["metadata"],
            "offer_id": fields["offer_id"],
            "generation": payload.content.get("generation"),
            "topic": fields["topic"],
        }

        if fields["metadata"].get("offer_url"):
            package["offer_url"] = fields["metadata"]["offer_url"]
            package["cta_label"] = fields["metadata"].get(
                "cta_label", "View recommended offer"
            )

        if signal and OfferFramer.should_frame(payload, signal):
            package["offer_bundle"] = OfferFramer.build_offer_bundle(payload, signal)
            package["offer_ready"] = True

        if signal:
            package["signal"] = {
                "hash": signal.signal_hash,
                "confidence": signal.confidence,
                "context": signal.context_vector,
            }

        # Preserve original content for audit without losing injection enrichments
        package["source_content"] = dict(payload.content)
        return package

    def _format_message(self, payload: ResonancePayload) -> str:
        if self._format_style == FormatStyle.RICH:
            return PayloadFormatter.format_rich(payload)
        return PayloadFormatter.format_simple(payload)

    @staticmethod
    def _resolve_delivery_body(
        mode: DeliveryMode,
        formatted: str,
        card: dict[str, Any],
        offer_pkg: dict[str, Any] | None,
        payload: ResonancePayload,
    ) -> str:
        if mode == DeliveryMode.STRUCTURED_CARD:
            return json.dumps(card, indent=2)
        if mode == DeliveryMode.OFFER_READY and offer_pkg:
            return json.dumps(offer_pkg, indent=2)
        if mode == DeliveryMode.ECHO:
            return payload.content.get("message", formatted)
        return formatted

    def _echo_delivery(
        self,
        channel: str,
        body: str,
        payload: ResonancePayload,
        signal: IntentSignal | None,
    ) -> None:
        signal_hash = signal.signal_hash if signal else "n/a"
        print(
            f"\n── ForgeResonance Inject [{channel}] ──\n"
            f"{body}\n"
            f"  (quality={payload.quality_estimate:.2f}, "
            f"confidence={payload.confidence:.2f}, "
            f"signal={signal_hash})\n"
        )

    def _select_channel(self, signal: IntentSignal) -> str:
        """Choose delivery channel based on signal confidence."""
        if signal.confidence > 0.8:
            return "inline"
        if payload_type := signal.context_vector.get("source"):
            if payload_type == "webhook":
                return "webhook"
            if payload_type == "chat":
                return "chat"
        return self._channels[0]

    @staticmethod
    def _outcome_from_quality(quality: float) -> ResonanceOutcome:
        if quality >= 0.7:
            return ResonanceOutcome.SUCCESS
        if quality >= 0.4:
            return ResonanceOutcome.PARTIAL
        return ResonanceOutcome.FAILURE


class InjectionChannel(ABC):
    """Abstract delivery channel for value injection (email, chat, web, etc.)."""

    @abstractmethod
    def deliver(
        self,
        payload: ResonancePayload,
        result: InjectionResult,
        context: dict[str, Any],
    ) -> bool:
        """Attempt delivery. Returns True on success."""
        ...