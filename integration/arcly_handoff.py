"""
Arcly AI Closer Integration Layer.

Clean handoff contract between ForgeResonance and the Arcly intelligence
layer for conversion optimization and email follow-up.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
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

_DEFAULT_ARCLY_URL = "http://localhost:8000"


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

    Performs HTTP handoff when configured; logs a dry-run otherwise.
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        *,
        force_dry_run: bool = False,
    ) -> None:
        self._api_url = (api_url or ARCLY_API_URL or _DEFAULT_ARCLY_URL).rstrip("/")
        self._api_key = api_key or ARCLY_API_KEY
        self._timeout = timeout or ARCLY_HANDOFF_TIMEOUT_SECONDS
        self._force_dry_run = force_dry_run

    @property
    def is_live(self) -> bool:
        """True when real HTTP handoff will be attempted."""
        return self._should_send_live()

    def handoff(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
        agent_id: str,
        *,
        handoff_content: dict[str, Any] | None = None,
    ) -> ResonanceOutcome:
        """Send resonance to Arcly for conversion processing."""
        content = handoff_content or self._resolve_handoff_content(payload)
        request = HandoffRequest(
            agent_id=agent_id,
            resonance_id=payload.resonance_id,
            signal_hash=signal.signal_hash,
            content=content,
            quality_estimate=payload.quality_estimate,
            offer_id=payload.offer_id or content.get("offer_id"),
        )

        if not self._should_send_live():
            return self._dry_run(request)

        try:
            response = self._send(request)
            logger.info(
                "Arcly handoff: agent=%s resonance=%s accepted=%s outcome=%s",
                agent_id,
                payload.resonance_id,
                response.accepted,
                response.outcome.value,
            )
            emit_axiom_event(
                "arcly_handoff",
                {
                    "agent_id": agent_id,
                    "resonance_id": payload.resonance_id,
                    "accepted": response.accepted,
                    "outcome": response.outcome.value,
                },
            )
            if response.accepted:
                return response.outcome
            return ResonanceOutcome.PARTIAL
        except Exception as exc:
            logger.error("Arcly handoff failed: %s", exc)
            return ResonanceOutcome.FAILURE

    @staticmethod
    def _resolve_handoff_content(payload: ResonancePayload) -> dict[str, Any]:
        """
        Prefer injector-prepared handoff package over raw payload content.

        ValueInjector attaches ``handoff_package`` after injection; fall back
        to legacy ``content`` when injection prep was skipped.
        """
        prepared = payload.content.get("handoff_package")
        if isinstance(prepared, dict) and prepared:
            return prepared
        return payload.content

    def _should_send_live(self) -> bool:
        """Determine whether to attempt a real HTTP handoff."""
        if self._force_dry_run or not self._api_key:
            return False
        effective_url = (ARCLY_API_URL or self._api_url or "").rstrip("/")
        return bool(effective_url) and effective_url != _DEFAULT_ARCLY_URL

    def _send(self, request: HandoffRequest) -> HandoffResponse:
        """POST handoff to Arcly API."""
        url = f"{self._api_url}/api/v1/resonance/handoff"
        body = json.dumps({
            "agent_id": request.agent_id,
            "resonance_id": request.resonance_id,
            "signal_hash": request.signal_hash,
            "content": request.content,
            "quality_estimate": request.quality_estimate,
            "offer_id": request.offer_id,
        }).encode()

        logger.debug("POST %s (resonance=%s)", url, request.resonance_id)

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
            logger.warning("Arcly unreachable at %s: %s", url, exc)
            return HandoffResponse(accepted=False, message=str(exc))

    def _dry_run(self, request: HandoffRequest) -> ResonanceOutcome:
        """Simulate handoff when Arcly is not configured or unreachable."""
        message = (
            request.content.get("message")
            or request.content.get("value_proposition")
            or "(no message)"
        )
        logger.info(
            "Arcly dry-run handoff: agent=%s resonance=%s quality=%.2f\n"
            "  → %s",
            request.agent_id,
            request.resonance_id,
            request.quality_estimate,
            message[:120],
        )
        print(
            f"\n── Arcly Handoff (dry-run) ──\n"
            f"  agent={request.agent_id}\n"
            f"  resonance={request.resonance_id}\n"
            f"  quality={request.quality_estimate:.2f}\n"
            f"  message={message[:200]}\n"
        )
        if request.quality_estimate >= 0.6:
            return ResonanceOutcome.SUCCESS
        return ResonanceOutcome.PARTIAL