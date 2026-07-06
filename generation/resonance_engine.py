"""
Resonance Matching & Generation Engine.

Matches sensed intent to agent offers and generates hyper-contextual
resonance payloads using Grok models via the xAI API.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from config import GROK_MODEL, XAI_API_KEY, XAI_BASE_URL
from core.memory import AgentMemory, EpisodicRecord
from core.resonance_agent import IntentSignal, ResonanceEngineProtocol, ResonancePayload
from utils.logging import setup_logging

logger = setup_logging("forge.generation")


class ResonanceEngine(ResonanceEngineProtocol):
    """
    Grok-native resonance generator.

    Uses agent memory, goals, episodic history, and Resonance Score to
    produce contextual value payloads.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = model or GROK_MODEL
        self._api_key = XAI_API_KEY
        self._base_url = XAI_BASE_URL.rstrip("/")

    def generate(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> ResonancePayload | None:
        """Generate a resonance payload for the given intent signal."""
        return self.generate_resonance(signal, agent_memory, resonance_score)

    def generate_resonance(
        self,
        intent_signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> ResonancePayload | None:
        """
        Primary generation entry point.

        Calls Grok when an API key is present; otherwise uses a local
        template that still incorporates episodic memory context.
        """
        if intent_signal.confidence < 0.3:
            logger.debug(
                "Signal confidence %.2f too low; skipping generation",
                intent_signal.confidence,
            )
            return None

        if self._api_key:
            payload = self._generate_with_grok(
                intent_signal, agent_memory, resonance_score
            )
            if payload is not None:
                return payload
            logger.warning("Grok generation failed; falling back to template")

        return self._generate_template(intent_signal, agent_memory, resonance_score)

    def _episodic_summary(self, agent_memory: AgentMemory, limit: int = 5) -> str:
        """Summarize recent episodic memory for prompt context."""
        recent: list[EpisodicRecord] = agent_memory.episodic[-limit:]
        if not recent:
            return "No prior resonances recorded."

        lines = []
        for ep in recent:
            quality = f"{ep.quality_score:.2f}" if ep.quality_score is not None else "n/a"
            lines.append(
                f"- {ep.outcome} (quality={quality}, id={ep.resonance_id[:8]})"
            )
        return "\n".join(lines)

    def _build_prompt(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> str:
        """Construct the Grok prompt with goals and episodic context."""
        topic = signal.context_vector.get("topic", signal.context_vector.get(
            "matched_intent", "unknown"
        ))
        return (
            f"You are a sovereign resonance agent named '{agent_memory.agent_name}' "
            f"on the ForgeResonance Fabric.\n\n"
            f"Agent goals: {', '.join(agent_memory.goals) or 'none set'}\n"
            f"Resonance Score: {resonance_score:.1f}/100\n"
            f"Intent topic: {topic}\n"
            f"Intent confidence: {signal.confidence:.2f}\n"
            f"Intent hash: {signal.signal_hash}\n\n"
            f"Recent resonance history:\n{self._episodic_summary(agent_memory)}\n\n"
            f"Generate a short, hyper-contextual value message for this intent. "
            f"Respond with JSON only: "
            f'{{"message": "...", "quality_estimate": 0.0-1.0, "offer_hint": "..."}}'
        )

    def _generate_template(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> ResonancePayload:
        """Local template generation when Grok is unavailable."""
        topic = signal.context_vector.get(
            "topic",
            signal.context_vector.get("matched_intent", "your intent"),
        )
        base_quality = min(
            1.0,
            signal.confidence * 0.6 + (resonance_score / 100.0) * 0.4,
        )
        episodic_count = len(agent_memory.episodic)

        message = (
            f"Contextual value for '{topic}': "
            f"As {agent_memory.agent_name}, I can help based on "
            f"{episodic_count} past resonance(s) and your goals: "
            f"{', '.join(agent_memory.goals[:2]) or 'general assistance'}."
        )

        logger.info(
            "Template resonance generated: agent=%s topic=%s quality=%.2f",
            agent_memory.agent_name,
            topic,
            base_quality,
        )

        return ResonancePayload(
            resonance_id="",
            content={
                "type": "contextual_value",
                "message": message,
                "topic": topic,
                "context_hash": signal.signal_hash,
                "goals": agent_memory.goals[:3],
                "generation": "template",
                "episodic_summary": self._episodic_summary(agent_memory, limit=3),
            },
            quality_estimate=base_quality,
        )

    def _generate_with_grok(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> ResonancePayload | None:
        """Call Grok via xAI REST API with episodic memory in the prompt."""
        prompt = self._build_prompt(signal, agent_memory, resonance_score)
        url = f"{self._base_url}/chat/completions"
        body = json.dumps({
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate concise, helpful contextual value for "
                        "ForgeResonance agents. Always respond with valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
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
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            content = data["choices"][0]["message"]["content"]
            parsed = self._parse_grok_response(content)
            quality = float(parsed.get("quality_estimate", 0.7))
            quality = max(0.0, min(1.0, quality))

            logger.info(
                "Grok resonance generated: model=%s topic=%s quality=%.2f",
                self._model,
                signal.context_vector.get("topic", "unknown"),
                quality,
            )

            return ResonancePayload(
                resonance_id="",
                content={
                    "type": "contextual_value",
                    "message": parsed.get("message", content),
                    "offer_hint": parsed.get("offer_hint"),
                    "context_hash": signal.signal_hash,
                    "goals": agent_memory.goals[:3],
                    "generation": "grok",
                    "model": self._model,
                    "episodic_summary": self._episodic_summary(agent_memory, limit=3),
                },
                quality_estimate=quality,
                offer_id=parsed.get("offer_hint"),
            )
        except (urllib.error.URLError, KeyError, json.JSONDecodeError, IndexError) as exc:
            logger.error("Grok API error: %s", exc)
            return None

    @staticmethod
    def _parse_grok_response(content: str) -> dict[str, Any]:
        """Extract JSON from Grok response, tolerating markdown fences."""
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"message": text, "quality_estimate": 0.65}


class ResonanceMatcher(ABC):
    """Abstract matcher for pairing intent signals to agent offers."""

    @abstractmethod
    def match(
        self,
        signal: IntentSignal,
        offers: list[dict[str, Any]],
        resonance_score: float,
    ) -> dict[str, Any] | None:
        """Return the best-matching offer or None."""
        ...


class ScoreWeightedMatcher(ResonanceMatcher):
    """Simple matcher that weights offers by agent Resonance Score."""

    def match(
        self,
        signal: IntentSignal,
        offers: list[dict[str, Any]],
        resonance_score: float,
    ) -> dict[str, Any] | None:
        if not offers:
            return None
        visibility = resonance_score / 100.0
        scored = sorted(
            offers,
            key=lambda o: o.get("relevance", 0.5) * visibility,
            reverse=True,
        )
        return scored[0] if scored else None