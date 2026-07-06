"""
Contextual Value Injection System.

Delivers generated resonance payloads into the user's active context at
the precise moment intent is forming — preemptive utility, not interruption.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Callable

from core.resonance_agent import (
    IntentSignal,
    ResonanceOutcome,
    ResonancePayload,
    ValueInjectorProtocol,
)
from utils.logging import setup_logging

logger = setup_logging("forge.injection")


class ValueInjector(ValueInjectorProtocol):
    """
    Default value injector.

    Logs and prints resonant value for now; real channel delivery (in-app,
    notification, widget) will be added in a later milestone.
    """

    def __init__(
        self,
        channels: list[str] | None = None,
        *,
        echo: bool = True,
        on_deliver: Callable[[ResonancePayload, str], None] | None = None,
    ) -> None:
        self._channels = channels or ["inline", "sidebar"]
        self._echo = echo
        self._on_deliver = on_deliver

    def inject(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
    ) -> ResonanceOutcome:
        """Inject contextual value — log/print delivery and return outcome tier."""
        if not payload.content:
            logger.warning(
                "Empty payload for resonance %s; injection failed",
                payload.resonance_id,
            )
            return ResonanceOutcome.FAILURE

        channel = self._select_channel(signal)
        message = payload.content.get("message", json.dumps(payload.content))

        logger.info(
            "INJECT [%s] resonance=%s channel=%s quality=%.2f\n  → %s",
            payload.content.get("type", "value"),
            payload.resonance_id,
            channel,
            payload.quality_estimate,
            message,
        )

        if self._echo:
            print(
                f"\n── ForgeResonance Inject [{channel}] ──\n"
                f"  {message}\n"
                f"  (quality={payload.quality_estimate:.2f}, "
                f"signal={signal.signal_hash})\n"
            )

        if self._on_deliver:
            try:
                self._on_deliver(payload, channel)
            except Exception as exc:
                logger.error("on_deliver callback failed: %s", exc)
                return ResonanceOutcome.FAILURE

        if payload.quality_estimate >= 0.7:
            return ResonanceOutcome.SUCCESS
        if payload.quality_estimate >= 0.4:
            return ResonanceOutcome.PARTIAL
        return ResonanceOutcome.FAILURE

    def _select_channel(self, signal: IntentSignal) -> str:
        """Choose delivery channel based on signal confidence."""
        if signal.confidence > 0.8:
            return "inline"
        return self._channels[0]


class InjectionChannel(ABC):
    """Abstract delivery channel for value injection."""

    @abstractmethod
    def deliver(self, payload: ResonancePayload, context: dict[str, Any]) -> bool:
        """Attempt delivery. Returns True on success."""
        ...