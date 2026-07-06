"""
Contextual Value Injection System.

Delivers generated resonance payloads into the user's active context at
the precise moment intent is forming — preemptive utility, not interruption.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

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

    Routes resonance payloads to the appropriate delivery channel
    (in-app surface, notification, embedded widget) based on context.
    """

    def __init__(self, channels: list[str] | None = None) -> None:
        self._channels = channels or ["inline", "sidebar"]

    def inject(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
    ) -> ResonanceOutcome:
        """
        Inject contextual value into the user's active context.

        Returns outcome tier for score adjustment downstream.
        """
        if not payload.content:
            logger.warning("Empty payload; injection skipped")
            return ResonanceOutcome.FAILURE

        delivery = self._select_channel(signal)
        logger.info(
            "Injecting resonance %s via %s (quality=%.2f)",
            payload.resonance_id,
            delivery,
            payload.quality_estimate,
        )

        if payload.quality_estimate >= 0.7:
            return ResonanceOutcome.SUCCESS
        if payload.quality_estimate >= 0.4:
            return ResonanceOutcome.PARTIAL
        return ResonanceOutcome.FAILURE

    def _select_channel(self, signal: IntentSignal) -> str:
        """Choose delivery channel based on signal context."""
        if signal.confidence > 0.8:
            return "inline"
        return self._channels[0]


class InjectionChannel(ABC):
    """Abstract delivery channel for value injection."""

    @abstractmethod
    def deliver(self, payload: ResonancePayload, context: dict[str, Any]) -> bool:
        """Attempt delivery. Returns True on success."""
        ...