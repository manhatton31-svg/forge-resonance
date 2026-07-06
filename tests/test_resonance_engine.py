"""
Tests for the ResonanceEngine generation layer.

Run with: python -m pytest tests/test_resonance_engine.py -v
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.memory import AgentMemory, EpisodicRecord
from core.resonance_agent import IntentSignal, ResonancePayload
from generation.resonance_engine import (
    ResonanceEngine,
    ResonanceType,
)


@pytest.fixture
def agent_memory() -> AgentMemory:
    return AgentMemory(
        agent_id="agent-gen-1",
        agent_name="Atlas",
        goals=["help teams adopt analytics", "reduce evaluation friction"],
        episodic=[
            EpisodicRecord(
                resonance_id="ep-1",
                context={
                    "topic": "analytics",
                    "matched_intent": "research_intent",
                    "message": "Prior overview delivered",
                },
                outcome="success",
                quality_score=0.82,
            ),
            EpisodicRecord(
                resonance_id="ep-2",
                context={
                    "topic": "pricing",
                    "matched_intent": "comparison_intent",
                    "message": "Comparison matrix shared",
                },
                outcome="partial",
                quality_score=0.55,
            ),
        ],
    )


def _signal(
    *,
    matched_intent: str = "research_intent",
    topic: str = "analytics platforms",
    confidence: float = 0.78,
) -> IntentSignal:
    return IntentSignal.from_context(
        {"matched_intent": matched_intent, "topic": topic},
        confidence=confidence,
    )


@pytest.fixture
def engine() -> ResonanceEngine:
    """Engine without API key — forces template path."""
    return ResonanceEngine(api_key="")


class TestResonancePayloadStructure:
    def test_from_structured_populates_content(self):
        payload = ResonancePayload.from_structured(
            summary="User wants analytics overview",
            recommended_action="Read the overview",
            value_proposition="Here is a tailored analytics overview.",
            confidence=0.8,
            resonance_type="educational",
            quality_estimate=0.75,
            metadata={"offer_url": "/offers/analytics"},
        )
        assert payload.summary == "User wants analytics overview"
        assert payload.recommended_action == "Read the overview"
        assert payload.value_proposition.startswith("Here is")
        assert payload.resonance_type == "educational"
        assert payload.metadata["offer_url"] == "/offers/analytics"
        assert payload.content["message"] == payload.value_proposition
        assert payload.content["resonance_type"] == "educational"


class TestTemplateGeneration:
    def test_generates_structured_payload(self, engine: ResonanceEngine, agent_memory: AgentMemory):
        payload = engine.generate_resonance(
            _signal(), agent_memory, resonance_score=62.0
        )
        assert payload is not None
        assert payload.summary
        assert payload.recommended_action
        assert payload.value_proposition
        assert payload.confidence > 0
        assert payload.quality_estimate > 0
        assert payload.content.get("generation") == "template"

    def test_educational_type_for_research_intent(
        self, engine: ResonanceEngine, agent_memory: AgentMemory
    ):
        payload = engine.generate_resonance(
            _signal(matched_intent="research_intent"),
            agent_memory,
            resonance_score=50.0,
        )
        assert payload is not None
        assert payload.resonance_type == ResonanceType.EDUCATIONAL.value

    def test_comparative_type_for_comparison_intent(
        self, engine: ResonanceEngine, agent_memory: AgentMemory
    ):
        payload = engine.generate_resonance(
            _signal(matched_intent="comparison_intent", topic="CRM tools"),
            agent_memory,
            resonance_score=55.0,
        )
        assert payload is not None
        assert payload.resonance_type == ResonanceType.COMPARATIVE.value
        assert "comparison" in payload.value_proposition.lower()

    def test_solution_type_for_problem_solving(
        self, engine: ResonanceEngine, agent_memory: AgentMemory
    ):
        payload = engine.generate_resonance(
            _signal(matched_intent="problem_solving_intent", topic="pipeline errors"),
            agent_memory,
            resonance_score=48.0,
        )
        assert payload is not None
        assert payload.resonance_type == ResonanceType.SOLUTION_ORIENTED.value
        assert "diagnostic" in payload.recommended_action.lower()

    def test_offer_framed_for_purchase_intent(
        self, engine: ResonanceEngine, agent_memory: AgentMemory
    ):
        payload = engine.generate_resonance(
            _signal(matched_intent="purchase_intent", topic="enterprise plan"),
            agent_memory,
            resonance_score=70.0,
        )
        assert payload is not None
        assert payload.resonance_type == ResonanceType.OFFER_FRAMED.value
        assert payload.metadata.get("resource_type") == "offer"

    def test_goals_influence_template_output(
        self, engine: ResonanceEngine, agent_memory: AgentMemory
    ):
        payload = engine.generate_resonance(
            _signal(), agent_memory, resonance_score=50.0
        )
        assert payload is not None
        assert "analytics" in payload.value_proposition.lower()
        assert agent_memory.goals[0] in payload.value_proposition

    def test_episodic_memory_influences_output(
        self, engine: ResonanceEngine, agent_memory: AgentMemory
    ):
        payload = engine.generate_resonance(
            _signal(), agent_memory, resonance_score=50.0
        )
        assert payload is not None
        assert "past resonance" in payload.value_proposition.lower()
        assert "analytics" in payload.content.get("episodic_summary", "").lower()

    def test_high_confidence_offer_includes_url(
        self, engine: ResonanceEngine, agent_memory: AgentMemory
    ):
        payload = engine.generate_resonance(
            _signal(
                matched_intent="purchase_intent",
                topic="analytics suite",
                confidence=0.85,
            ),
            agent_memory,
            resonance_score=65.0,
        )
        assert payload is not None
        assert payload.metadata.get("offer_url")

    def test_low_confidence_skips_generation(self, engine: ResonanceEngine, agent_memory: AgentMemory):
        result = engine.generate_resonance(
            _signal(confidence=0.2), agent_memory, resonance_score=50.0
        )
        assert result is None

    def test_quality_reflects_score_and_episodic(
        self, engine: ResonanceEngine, agent_memory: AgentMemory
    ):
        low = engine.generate_resonance(
            _signal(confidence=0.4), agent_memory, resonance_score=30.0
        )
        high = engine.generate_resonance(
            _signal(confidence=0.9), agent_memory, resonance_score=85.0
        )
        assert low is not None and high is not None
        assert high.quality_estimate > low.quality_estimate


class TestGrokGeneration:
    def test_grok_path_uses_structured_response(
        self, agent_memory: AgentMemory
    ):
        grok_json = json.dumps({
            "summary": "Strong purchase signal for analytics",
            "recommended_action": "Start a guided trial",
            "value_proposition": "Atlas recommends a trial aligned with team analytics goals.",
            "confidence": 0.88,
            "resonance_type": "offer_framed",
            "quality_estimate": 0.91,
            "offer_hint": "trial-analytics-pro",
            "metadata": {"cta_label": "Start trial"},
        })
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": grok_json}}],
        }).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        engine = ResonanceEngine(
            api_key="test-key",
            temperature=0.4,
            max_tokens=512,
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            payload = engine.generate_resonance(
                _signal(matched_intent="purchase_intent"),
                agent_memory,
                resonance_score=72.0,
            )

        assert payload is not None
        assert payload.content["generation"] == "grok"
        assert payload.summary == "Strong purchase signal for analytics"
        assert payload.offer_id == "trial-analytics-pro"
        assert payload.resonance_type == "offer_framed"
        assert payload.quality_estimate == pytest.approx(0.91)

    def test_grok_failure_falls_back_to_template(self, agent_memory: AgentMemory):
        engine = ResonanceEngine(api_key="test-key")

        with patch(
            "urllib.request.urlopen",
            side_effect=Exception("network error"),
        ):
            payload = engine.generate_resonance(
                _signal(), agent_memory, resonance_score=50.0
            )

        assert payload is not None
        assert payload.content["generation"] == "template"

    def test_grok_request_includes_temperature_and_max_tokens(
        self, agent_memory: AgentMemory
    ):
        captured: dict = {}

        def fake_urlopen(req, timeout=30):
            captured["body"] = json.loads(req.data.decode())
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "summary": "s",
                            "recommended_action": "a",
                            "value_proposition": "v",
                            "confidence": 0.7,
                            "quality_estimate": 0.7,
                        }),
                    },
                }],
            }).encode()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            return mock_response

        engine = ResonanceEngine(
            api_key="key",
            temperature=0.33,
            max_tokens=256,
        )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            engine.generate_resonance(
                _signal(), agent_memory, resonance_score=50.0
            )

        assert captured["body"]["temperature"] == 0.33
        assert captured["body"]["max_tokens"] == 256
        system_msg = captured["body"]["messages"][0]["content"]
        assert "AGENT GOALS" in system_msg
        assert "EPISODIC MEMORY" in system_msg