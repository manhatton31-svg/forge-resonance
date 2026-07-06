"""
Arcly AI Closer Integration Layer.

Production-ready handoff contract between ForgeResonance and Arcly for
conversion optimization, offer framing, and two-way reputation feedback.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from config import load_arcly_config
from config import ArclyConfig
from core.resonance_agent import (
    ArclyHandoffProtocol,
    IntentSignal,
    ResonanceOutcome,
    ResonancePayload,
)
from core.scoring import ScoreUpdate
from integration.offer_framer import OfferFramer
from utils.logging import emit_axiom_event, setup_logging

logger = setup_logging("forge.arcly")

OutcomeCallback = Callable[[str, str, ResonanceOutcome, dict[str, Any]], None]


@dataclass
class HandoffRequest:
    """Structured payload sent to Arcly for conversion."""

    agent_id: str
    resonance_id: str
    signal_hash: str
    content: dict[str, Any]
    quality_estimate: float
    offer_id: str | None = None
    agent_stats: dict[str, Any] = field(default_factory=dict)
    offer_bundle: dict[str, Any] = field(default_factory=dict)


@dataclass
class HandoffResponse:
    """Response from Arcly AI Closer."""

    accepted: bool
    conversion_id: str | None = None
    outcome: ResonanceOutcome = ResonanceOutcome.PARTIAL
    message: str = ""
    status_code: int = 0
    attempts: int = 1


@dataclass
class HandoffResult:
    """Rich result from a handoff attempt (live or dry-run)."""

    outcome: ResonanceOutcome
    mode: str
    request: HandoffRequest
    response: HandoffResponse | None = None
    feedback_recorded: bool = False


@dataclass
class OutcomeReport:
    """Result of reporting Arcly feedback back to ForgeResonance."""

    agent_id: str
    resonance_id: str
    outcome: ResonanceOutcome
    score_update: ScoreUpdate | None = None
    recorded: bool = False
    message: str = ""


class ArclyHandoff(ArclyHandoffProtocol):
    """
    Handoff bridge to Arcly AI Closer.

    Supports dry-run and live modes, retries, reputation-enriched context,
    offer bundles, and two-way outcome feedback via ``report_outcome``.
    """

    HANDOFF_PATH = "/api/v1/resonance/handoff"
    FEEDBACK_PATH = "/api/v1/resonance/outcome"

    def __init__(
        self,
        config: ArclyConfig | None = None,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        force_dry_run: bool | None = None,
        quiet: bool = False,
        score_manager: Any | None = None,
        on_outcome: OutcomeCallback | None = None,
    ) -> None:
        base = config or load_arcly_config()
        mode = "dry_run" if force_dry_run else base.mode
        self._config = ArclyConfig(
            api_url=(api_url or base.api_url).rstrip("/"),
            api_key=api_key if api_key is not None else base.api_key,
            timeout_seconds=timeout if timeout is not None else base.timeout_seconds,
            max_retries=base.max_retries,
            retry_delay_seconds=base.retry_delay_seconds,
            mode=mode,
            feedback_enabled=base.feedback_enabled,
        )
        self._quiet = quiet
        self._score_manager = score_manager
        self._on_outcome = on_outcome
        self._last_result: HandoffResult | None = None

    @property
    def config(self) -> ArclyConfig:
        return self._config

    @property
    def is_live(self) -> bool:
        """True when real HTTP handoff will be attempted."""
        return self._config.is_live

    @property
    def mode(self) -> str:
        return self._config.effective_mode

    @property
    def last_result(self) -> HandoffResult | None:
        return self._last_result

    def attach_score_manager(self, manager: Any) -> None:
        """Wire reputation manager for ``report_outcome`` feedback loop."""
        self._score_manager = manager

    def handoff(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
        agent_id: str,
        *,
        handoff_content: dict[str, Any] | None = None,
    ) -> ResonanceOutcome:
        """Protocol entry — handoff without explicit reputation context."""
        result = self.handoff_with_context(
            payload,
            signal,
            agent_id,
            agent_stats={},
            handoff_content=handoff_content,
        )
        return result.outcome

    def handoff_with_context(
        self,
        payload: ResonancePayload,
        signal: IntentSignal,
        agent_id: str,
        agent_stats: dict[str, Any] | None = None,
        *,
        handoff_content: dict[str, Any] | None = None,
    ) -> HandoffResult:
        """
        Send resonance to Arcly with reputation context and offer bundle.

        ``agent_stats`` should include resonance_score, visibility_multiplier,
        success_rate, and trend when available from ``get_reputation_stats()``.
        """
        OfferFramer.frame(payload, signal)
        content = handoff_content or self._resolve_handoff_content(payload)
        offer_bundle = (
            payload.content.get("offer_bundle")
            or OfferFramer.build_offer_bundle(payload, signal)
        )
        if offer_bundle.get("offer_ready"):
            content = {**content, "offer_bundle": offer_bundle, "offer_ready": True}

        stats = dict(agent_stats or {})
        request = HandoffRequest(
            agent_id=agent_id,
            resonance_id=payload.resonance_id,
            signal_hash=signal.signal_hash,
            content=content,
            quality_estimate=payload.quality_estimate,
            offer_id=payload.offer_id or content.get("offer_id"),
            agent_stats=stats,
            offer_bundle=offer_bundle if offer_bundle.get("offer_ready") else {},
        )

        if not self._config.is_live:
            result = self._dry_run(request)
            self._last_result = result
            return result

        try:
            response = self._send_with_retry(request)
            outcome = (
                response.outcome
                if response.accepted
                else ResonanceOutcome.PARTIAL
            )
            result = HandoffResult(
                outcome=outcome,
                mode="live",
                request=request,
                response=response,
            )
            self._log_handoff(agent_id, payload.resonance_id, result)
            self._last_result = result
            return result
        except Exception as exc:
            logger.error(
                "Arcly handoff failed after %d attempts: %s",
                self._config.max_retries + 1,
                exc,
            )
            result = HandoffResult(
                outcome=ResonanceOutcome.FAILURE,
                mode="live",
                request=request,
                response=HandoffResponse(
                    accepted=False,
                    outcome=ResonanceOutcome.FAILURE,
                    message=str(exc),
                ),
            )
            self._last_result = result
            return result

    def report_outcome(
        self,
        agent_id: str,
        resonance_id: str,
        outcome: str | ResonanceOutcome,
        *,
        quality: float | None = None,
        conversion_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        intent_signal_hash: str = "",
    ) -> OutcomeReport:
        """
        Receive Arcly feedback and update the Resonance Score.

        Call from webhooks, ``api/arcly_feedback.py``, or polling when Arcly
        completes conversion processing asynchronously.
        """
        resolved = (
            outcome
            if isinstance(outcome, ResonanceOutcome)
            else ResonanceOutcome(str(outcome))
        )
        meta = dict(metadata or {})
        if conversion_id:
            meta["conversion_id"] = conversion_id
        meta["source"] = "arcly_feedback"

        score_update = self._apply_reputation_feedback(
            agent_id,
            resolved,
            quality=quality,
            resonance_id=resonance_id,
            intent_signal_hash=intent_signal_hash,
            metadata=meta,
        )

        if self._on_outcome:
            try:
                self._on_outcome(agent_id, resonance_id, resolved, meta)
            except Exception as exc:
                logger.error("on_outcome callback failed: %s", exc)

        emit_axiom_event(
            "arcly_outcome_report",
            {
                "agent_id": agent_id,
                "resonance_id": resonance_id,
                "outcome": resolved.value,
                "recorded": score_update is not None,
            },
        )

        return OutcomeReport(
            agent_id=agent_id,
            resonance_id=resonance_id,
            outcome=resolved,
            score_update=score_update,
            recorded=score_update is not None,
            message="Score updated from Arcly feedback"
            if score_update
            else "Outcome logged (no score manager attached)",
        )

    @staticmethod
    def _resolve_handoff_content(payload: ResonancePayload) -> dict[str, Any]:
        prepared = payload.content.get("handoff_package")
        if isinstance(prepared, dict) and prepared:
            return prepared
        return dict(payload.content)

    def _send_with_retry(self, request: HandoffRequest) -> HandoffResponse:
        last_error: Exception | None = None
        attempts = 0
        for attempt in range(self._config.max_retries + 1):
            attempts = attempt + 1
            try:
                response = self._send(request)
                response.attempts = attempts
                if response.accepted or response.status_code < 500:
                    return response
                last_error = RuntimeError(
                    f"Arcly returned status {response.status_code}: {response.message}"
                )
            except urllib.error.URLError as exc:
                last_error = exc
                logger.warning(
                    "Arcly attempt %d/%d failed: %s",
                    attempts,
                    self._config.max_retries + 1,
                    exc,
                )
            if attempt < self._config.max_retries:
                delay = self._config.retry_delay_seconds * (2 ** attempt)
                time.sleep(delay)

        raise last_error or RuntimeError("Arcly handoff failed")

    def _send(self, request: HandoffRequest) -> HandoffResponse:
        """POST handoff to Arcly API."""
        url = f"{self._config.api_url}{self.HANDOFF_PATH}"
        body = json.dumps({
            "agent_id": request.agent_id,
            "resonance_id": request.resonance_id,
            "signal_hash": request.signal_hash,
            "content": request.content,
            "quality_estimate": request.quality_estimate,
            "offer_id": request.offer_id,
            "agent_stats": request.agent_stats,
            "offer_bundle": request.offer_bundle,
        }).encode()

        logger.debug(
            "POST %s (resonance=%s mode=%s)",
            url,
            request.resonance_id,
            self.mode,
        )

        req = urllib.request.Request(
            url,
            data=body,
            headers=self._auth_headers(),
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._config.timeout_seconds) as resp:
                status = resp.status
                data = json.loads(resp.read().decode())
                outcome_str = data.get("outcome", "partial")
                try:
                    outcome = ResonanceOutcome(outcome_str)
                except ValueError:
                    outcome = ResonanceOutcome.PARTIAL
                return HandoffResponse(
                    accepted=data.get("accepted", status < 400),
                    conversion_id=data.get("conversion_id"),
                    outcome=outcome,
                    message=data.get("message", ""),
                    status_code=status,
                )
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode() if exc.fp else ""
            logger.warning("Arcly HTTP %s: %s", exc.code, body_text[:200])
            return HandoffResponse(
                accepted=False,
                message=body_text or str(exc),
                status_code=exc.code,
            )
        except urllib.error.URLError as exc:
            raise exc

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def _dry_run(self, request: HandoffRequest) -> HandoffResult:
        message = (
            request.content.get("message")
            or request.content.get("value_proposition")
            or request.offer_bundle.get("value_prop")
            or "(no message)"
        )
        logger.info(
            "Arcly dry-run [%s]: agent=%s resonance=%s quality=%.2f "
            "score=%s visibility=%s offer=%s\n  → %s",
            self.mode,
            request.agent_id,
            request.resonance_id,
            request.quality_estimate,
            request.agent_stats.get("resonance_score", "n/a"),
            request.agent_stats.get("visibility_multiplier", "n/a"),
            request.offer_id or "none",
            str(message)[:120],
        )
        if not self._quiet:
            stats_line = ""
            if request.agent_stats:
                stats_line = (
                    f"  reputation: score={request.agent_stats.get('resonance_score', 'n/a')} "
                    f"visibility={request.agent_stats.get('visibility_multiplier', 'n/a')}\n"
                )
            print(
                f"\n── Arcly Handoff (dry-run / {self.mode}) ──\n"
                f"  agent={request.agent_id}\n"
                f"  resonance={request.resonance_id}\n"
                f"  quality={request.quality_estimate:.2f}\n"
                f"{stats_line}"
                f"  message={str(message)[:200]}\n"
            )

        outcome = (
            ResonanceOutcome.SUCCESS
            if request.quality_estimate >= 0.6
            else ResonanceOutcome.PARTIAL
        )
        response = HandoffResponse(
            accepted=True,
            outcome=outcome,
            message="dry-run simulated acceptance",
        )
        result = HandoffResult(
            outcome=outcome,
            mode="dry_run",
            request=request,
            response=response,
        )
        return result

    def _log_handoff(
        self,
        agent_id: str,
        resonance_id: str,
        result: HandoffResult,
    ) -> None:
        resp = result.response
        logger.info(
            "Arcly handoff [%s]: agent=%s resonance=%s outcome=%s accepted=%s attempts=%s",
            result.mode,
            agent_id,
            resonance_id,
            result.outcome.value,
            resp.accepted if resp else False,
            resp.attempts if resp else 0,
        )
        emit_axiom_event(
            "arcly_handoff",
            {
                "agent_id": agent_id,
                "resonance_id": resonance_id,
                "mode": result.mode,
                "outcome": result.outcome.value,
                "accepted": resp.accepted if resp else False,
            },
        )

    def _apply_reputation_feedback(
        self,
        agent_id: str,
        outcome: ResonanceOutcome,
        *,
        quality: float | None,
        resonance_id: str,
        intent_signal_hash: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ScoreUpdate | None:
        if not self._config.feedback_enabled or not self._score_manager:
            return None
        return self._score_manager.record_outcome(
            agent_id,
            outcome.value,
            quality=quality or 0.0,
            metadata=metadata,
            resonance_id=resonance_id,
            intent_signal_hash=intent_signal_hash,
        )