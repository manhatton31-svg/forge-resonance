"""
Arcly AI Closer Integration Layer.

Clean handoff contract between ForgeResonance and the Arcly intelligence
layer for conversion optimization and email follow-up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from config import ARCLY_API_KEY, ARCLY_API_URL, ARCLY_HANDOFF_TIMEOUT_SECONDS
from core.resonance_agent import (
    ArclyHandoffProtocol,
    IntentSignal,
    ResonanceOutcome,
    ResonancePayload,
)
from utils.logging import emit_axiom_event, setup_logging

logger = setup_logging("forge.arcly")


@dataclass
class HandoffRequest:
    """Structured payload sent to Arcly for conversion."""

    agent_id: str
    resonance_id: str
    signal_hash: str
    content: dict[str, Any]
    quality_estimate: float
    offer_id: str | None = None


@dataclass
class HandoffResponse:
    """Response from Arcly AI Closer."""

    accepted: bool
    conversion_id: str | None = None
    outcome: ResonanceOutcome = ResonanceOutcome.PARTIAL
    message: str = ""


class ArclyHandoff(ArclyHandoffProtocol):
    """
    Handoff bridge to Arcly AI Closer.

    Transfers qualified resonances for conversion optimization,
    email sequencing, and outcome tracking back into the Fabric.
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self._api_url = (api_url or ARCLY_API_URL).rstrip("/")
        self._api_key = api_key or ARCLY_API_KEY
        self._timeout = timeout or ARCLY_HANDOFF_TIMEOUT_SECONDS

    def handoff(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
        agent_id: str,
    ) -> ResonanceOutcome:
        """Send resonance to Arcly for conversion processing."""
        request = HandoffRequest(
            agent_id=agent_id,
            resonance_id=payload.resonance_id,
            signal_hash=signal.signal_hash,
            content=payload.content,
            quality_estimate=payload.quality_estimate,
            offer_id=payload.offer_id,
        )

        if not self._api_key:
            logger.info("Arcly API key not configured; dry-run handoff")
            return self._dry_run(request)

        try:
            response = self._send(request)
            emit_axiom_event(
                "arcly_handoff",
                {
                    "agent_id": agent_id,
                    "resonance_id": payload.resonance_id,
                    "accepted": response.accepted,
                    "outcome": response.outcome.value,
                },
            )
            return response.outcome
        except Exception as exc:
            logger.error("Arcly handoff failed: %s", exc)
            return ResonanceOutcome.FAILURE

    def _send(self, request: HandoffRequest) -> HandoffResponse:
        """POST handoff to Arcly API."""
        import urllib.error
        import urllib.request

        url = f"{self._api_url}/api/v1/resonance/handoff"
        body = json.dumps({
            "agent_id": request.agent_id,
            "resonance_id": request.resonance_id,
            "signal_hash": request.signal_hash,
            "content": request.content,
            "quality_estimate": request.quality_estimate,
            "offer_id": request.offer_id,
        }).encode()

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode())
                return HandoffResponse(
                    accepted=data.get("accepted", False),
                    conversion_id=data.get("conversion_id"),
                    outcome=ResonanceOutcome(data.get("outcome", "partial")),
                    message=data.get("message", ""),
                )
        except urllib.error.URLError as exc:
            logger.warning("Arcly unreachable: %s", exc)
            return HandoffResponse(accepted=False, message=str(exc))

    def _dry_run(self, request: HandoffRequest) -> ResonanceOutcome:
        """Simulate handoff when Arcly is not configured."""
        logger.debug(
            "Dry-run handoff: agent=%s resonance=%s",
            request.agent_id,
            request.resonance_id,
        )
        if request.quality_estimate >= 0.6:
            return ResonanceOutcome.SUCCESS
        return ResonanceOutcome.PARTIAL