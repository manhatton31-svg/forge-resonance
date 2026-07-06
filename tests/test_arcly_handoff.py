"""
Tests for Arcly handoff, offer framing, and feedback loop.

Run with: python -m pytest tests/test_arcly_handoff.py -v
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from config import ArclyConfig
from core.resonance_agent import IntentSignal, ResonanceOutcome, ResonancePayload
from core.scoring import InMemoryScoreStore, ResonanceScorer
from integration.arcly_handoff import ArclyHandoff, HandoffRequest
from integration.offer_framer import OfferFramer
from reputation.score_layer import (
    InMemoryOutcomeHistoryStore,
    ResonanceScoreManager,
)


@pytest.fixture
def commercial_signal() -> IntentSignal:
    return IntentSignal.from_context(
        {"matched_intent": "purchase_intent", "topic": "enterprise plan"},
        confidence=0.88,
    )


@pytest.fixture
def offer_payload() -> ResonancePayload:
    return ResonancePayload.from_structured(
        resonance_id="res-offer",
        summary="Purchase intent detected",
        recommended_action="Start trial",
        value_proposition="Enterprise analytics plan fits your team.",
        confidence=0.88,
        resonance_type="offer_framed",
        quality_estimate=0.82,
        metadata={"cta_label": "Start trial"},
    )


@pytest.fixture
def score_manager() -> ResonanceScoreManager:
    return ResonanceScoreManager(
        scorer=ResonanceScorer(InMemoryScoreStore()),
        history_store=InMemoryOutcomeHistoryStore(),
    )


class TestOfferFramer:
    def test_detects_commercial_intent(self, commercial_signal: IntentSignal):
        assert OfferFramer.is_commercial_intent(commercial_signal)

    def test_frames_payload_with_bundle(
        self,
        offer_payload: ResonancePayload,
        commercial_signal: IntentSignal,
    ):
        OfferFramer.frame(offer_payload, commercial_signal)
        assert offer_payload.content.get("offer_ready") is True
        bundle = offer_payload.content.get("offer_bundle", {})
        assert bundle.get("offer_id")
        assert bundle.get("offer_url")
        assert bundle.get("cta_text")
        assert bundle.get("value_prop")


class TestArclyHandoffDryRun:
    def test_dry_run_with_context(
        self,
        offer_payload: ResonancePayload,
        commercial_signal: IntentSignal,
    ):
        handoff = ArclyHandoff(
            config=ArclyConfig(mode="dry_run"),
            quiet=True,
        )
        result = handoff.handoff_with_context(
            offer_payload,
            commercial_signal,
            "agent-1",
            {
                "resonance_score": 62.5,
                "visibility_multiplier": 1.2,
                "success_rate": 0.75,
            },
        )
        assert result.mode == "dry_run"
        assert result.outcome in (ResonanceOutcome.SUCCESS, ResonanceOutcome.PARTIAL)
        assert result.request.agent_stats["resonance_score"] == 62.5
        assert result.request.offer_bundle.get("offer_ready")

    def test_handoff_protocol_delegates(
        self,
        offer_payload: ResonancePayload,
        commercial_signal: IntentSignal,
    ):
        handoff = ArclyHandoff(config=ArclyConfig(mode="dry_run"), quiet=True)
        outcome = handoff.handoff(offer_payload, commercial_signal, "agent-1")
        assert outcome in (ResonanceOutcome.SUCCESS, ResonanceOutcome.PARTIAL)


class TestArclyHandoffLive:
    def test_live_handoff_with_mock_response(
        self,
        offer_payload: ResonancePayload,
        commercial_signal: IntentSignal,
    ):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "accepted": True,
            "conversion_id": "conv-123",
            "outcome": "success",
            "message": "Handoff accepted",
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        handoff = ArclyHandoff(
            config=ArclyConfig(
                api_url="https://arcly.example.com",
                api_key="test-key",
                mode="live",
                max_retries=1,
            ),
            quiet=True,
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = handoff.handoff_with_context(
                offer_payload,
                commercial_signal,
                "agent-live",
                {"resonance_score": 70.0},
            )

        assert result.mode == "live"
        assert result.outcome == ResonanceOutcome.SUCCESS
        assert result.response is not None
        assert result.response.conversion_id == "conv-123"

    def test_retry_on_connection_error(
        self,
        offer_payload: ResonancePayload,
        commercial_signal: IntentSignal,
    ):
        import urllib.error

        handoff = ArclyHandoff(
            config=ArclyConfig(
                api_url="https://arcly.example.com",
                api_key="key",
                mode="live",
                max_retries=2,
                retry_delay_seconds=0.01,
            ),
            quiet=True,
        )
        request = HandoffRequest(
            agent_id="a",
            resonance_id="r",
            signal_hash="h",
            content={},
            quality_estimate=0.8,
        )

        call_count = 0

        def flaky_urlopen(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise urllib.error.URLError("connection reset")
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = json.dumps({
                "accepted": True,
                "outcome": "partial",
            }).encode()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            return mock_response

        with patch("urllib.request.urlopen", side_effect=flaky_urlopen):
            with patch("time.sleep"):
                response = handoff._send_with_retry(request)

        assert response.accepted is True
        assert call_count == 3


class TestArclyFeedback:
    def test_report_outcome_updates_reputation(
        self,
        score_manager: ResonanceScoreManager,
    ):
        handoff = ArclyHandoff(
            config=ArclyConfig(mode="dry_run", feedback_enabled=True),
            score_manager=score_manager,
            quiet=True,
        )
        initial = score_manager.get_score("feedback-agent")
        report = handoff.report_outcome(
            "feedback-agent",
            "res-001",
            "success",
            quality=0.9,
            conversion_id="conv-99",
        )
        assert report.recorded is True
        assert report.score_update is not None
        assert score_manager.get_score("feedback-agent") > initial

    def test_report_outcome_without_manager(self):
        handoff = ArclyHandoff(config=ArclyConfig(mode="dry_run"), quiet=True)
        report = handoff.report_outcome("a", "r", "success")
        assert report.recorded is False

    def test_config_auto_mode_defaults_dry_run(self):
        cfg = ArclyConfig(api_url="http://localhost:8000", api_key="", mode="auto")
        assert cfg.effective_mode == "dry_run"
        assert cfg.is_live is False

    def test_config_live_mode(self):
        cfg = ArclyConfig(
            api_url="https://api.arcly.ai",
            api_key="secret",
            mode="auto",
        )
        assert cfg.is_live is True