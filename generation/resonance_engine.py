"""
Resonance Matching & Generation Engine.

Matches sensed intent to agent offers and generates hyper-contextual
resonance payloads using Grok models via the xAI API, with a rich
context-aware template fallback when no API key is available.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

from config import (
    GROK_MAX_TOKENS,
    GROK_MODEL,
    GROK_TEMPERATURE,
    XAI_API_KEY,
    XAI_BASE_URL,
)
from core.memory import AgentMemory, EpisodicRecord
from core.resonance_agent import IntentSignal, ResonanceEngineProtocol, ResonancePayload
from utils.logging import setup_logging

logger = setup_logging("forge.generation")


class ResonanceType(str, Enum):
    """Framing strategy for generated contextual value."""

    EDUCATIONAL = "educational"
    COMPARATIVE = "comparative"
    SOLUTION_ORIENTED = "solution_oriented"
    OFFER_FRAMED = "offer_framed"


# Map harvested intent labels to preferred resonance framing.
INTENT_TO_RESONANCE_TYPE: dict[str, ResonanceType] = {
    "research_intent": ResonanceType.EDUCATIONAL,
    "comparison_intent": ResonanceType.COMPARATIVE,
    "problem_solving_intent": ResonanceType.SOLUTION_ORIENTED,
    "support_intent": ResonanceType.SOLUTION_ORIENTED,
    "purchase_intent": ResonanceType.OFFER_FRAMED,
    "evaluation_intent": ResonanceType.OFFER_FRAMED,
}


@dataclass(frozen=True)
class EpisodicInsights:
    """Aggregated signals from recent episodic memory."""

    summary_text: str
    episode_count: int
    success_rate: float
    avg_quality: float
    recent_topics: tuple[str, ...]


@dataclass(frozen=True)
class GenerationContext:
    """Normalized inputs for resonance generation."""

    topic: str
    matched_intent: str
    resonance_type: ResonanceType
    signal_confidence: float
    resonance_score: float
    goals: tuple[str, ...]
    episodic: EpisodicInsights
    context_vector: dict[str, Any]


class ResonanceEngine(ResonanceEngineProtocol):
    """
    Grok-native resonance generator.

    Uses agent goals, episodic history, Resonance Score, and intent
    confidence to produce structured ResonancePayload objects with
    educational, comparative, solution-oriented, or offer-framed framing.
    """

    GROK_OUTPUT_SCHEMA = (
        '{"summary": "...", "recommended_action": "...", '
        '"value_proposition": "...", "confidence": 0.0-1.0, '
        '"resonance_type": "educational|comparative|solution_oriented|offer_framed", '
        '"quality_estimate": 0.0-1.0, "offer_hint": "...", '
        '"metadata": {"offer_url": "...", "cta_label": "..."}}'
    )

    def __init__(
        self,
        model: str | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        api_key: str | None = None,
    ) -> None:
        self._model = model or GROK_MODEL
        self._temperature = temperature if temperature is not None else GROK_TEMPERATURE
        self._max_tokens = max_tokens if max_tokens is not None else GROK_MAX_TOKENS
        self._api_key = api_key if api_key is not None else XAI_API_KEY
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

        Calls Grok when an API key is present; otherwise uses context-aware
        templates that still incorporate goals, episodic memory, and score.
        """
        if intent_signal.confidence < 0.3:
            logger.debug(
                "Signal confidence %.2f too low; skipping generation",
                intent_signal.confidence,
            )
            return None

        ctx = self._build_context(intent_signal, agent_memory, resonance_score)

        if self._api_key:
            payload = self._generate_with_grok(ctx, intent_signal, agent_memory)
            if payload is not None:
                return payload
            logger.warning("Grok generation failed; falling back to template")

        return self._generate_template(ctx, intent_signal, agent_memory)

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def _build_context(
        self,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        resonance_score: float,
    ) -> GenerationContext:
        """Normalize signal + memory into a generation context."""
        cv = signal.context_vector
        raw_topic = cv.get("topic", "")
        matched_intent = str(cv.get("matched_intent") or cv.get("intent") or "")
        # Harvester stores pattern label in ``topic`` (e.g. research_intent).
        if not matched_intent and isinstance(raw_topic, str) and raw_topic.endswith(
            "_intent"
        ):
            matched_intent = raw_topic
        if not matched_intent:
            matched_intent = "unknown_intent"
        if isinstance(raw_topic, str) and raw_topic.endswith("_intent"):
            topic = raw_topic.replace("_intent", "").replace("_", " ")
        elif raw_topic:
            topic = str(raw_topic)
        else:
            topic = matched_intent.replace("_intent", "").replace("_", " ")
        resonance_type = self._resolve_resonance_type(matched_intent, cv)
        episodic = self._analyze_episodic(agent_memory)

        return GenerationContext(
            topic=topic,
            matched_intent=matched_intent,
            resonance_type=resonance_type,
            signal_confidence=signal.confidence,
            resonance_score=resonance_score,
            goals=tuple(agent_memory.goals),
            episodic=episodic,
            context_vector=cv,
        )

    @staticmethod
    def _resolve_resonance_type(
        matched_intent: str,
        context_vector: dict[str, Any],
    ) -> ResonanceType:
        """Pick resonance framing from intent label or explicit override."""
        override = context_vector.get("resonance_type")
        if override:
            try:
                return ResonanceType(str(override))
            except ValueError:
                pass
        return INTENT_TO_RESONANCE_TYPE.get(
            matched_intent,
            ResonanceType.EDUCATIONAL,
        )

    def _analyze_episodic(
        self,
        agent_memory: AgentMemory,
        limit: int = 8,
    ) -> EpisodicInsights:
        """Summarize recent episodic memory for prompts and quality scoring."""
        recent: list[EpisodicRecord] = agent_memory.episodic[-limit:]
        if not recent:
            return EpisodicInsights(
                summary_text="No prior resonances recorded.",
                episode_count=0,
                success_rate=0.5,
                avg_quality=0.5,
                recent_topics=(),
            )

        successes = sum(1 for ep in recent if ep.outcome in ("success", "partial"))
        qualities = [
            ep.quality_score
            for ep in recent
            if ep.quality_score is not None
        ]
        avg_quality = sum(qualities) / len(qualities) if qualities else 0.5
        success_rate = successes / len(recent)

        topics: list[str] = []
        lines: list[str] = []
        for ep in recent:
            topic = ep.context.get("topic") or ep.context.get("matched_intent")
            if topic and topic not in topics:
                topics.append(str(topic))
            quality = (
                f"{ep.quality_score:.2f}"
                if ep.quality_score is not None
                else "n/a"
            )
            snippet = ep.context.get("message") or ep.context.get("summary")
            snippet_text = f' — "{str(snippet)[:60]}"' if snippet else ""
            lines.append(
                f"- {ep.outcome} (quality={quality}, topic={topic or 'n/a'})"
                f"{snippet_text}"
            )

        summary = (
            f"{len(recent)} recent episode(s); "
            f"success_rate={success_rate:.0%}; avg_quality={avg_quality:.2f}\n"
            + "\n".join(lines)
        )
        return EpisodicInsights(
            summary_text=summary,
            episode_count=len(recent),
            success_rate=success_rate,
            avg_quality=avg_quality,
            recent_topics=tuple(topics[:5]),
        )

    def _estimate_quality(self, ctx: GenerationContext) -> float:
        """
        Blend intent confidence, agent score, and episodic momentum.

        Higher past success and quality nudge estimates upward; weak episodic
        track records dampen confidence in generation quality.
        """
        intent_component = ctx.signal_confidence * 0.35
        score_component = (ctx.resonance_score / 100.0) * 0.25
        episodic_component = (
            ctx.episodic.avg_quality * 0.5 + ctx.episodic.success_rate * 0.5
        ) * 0.25
        type_fit = 0.15 if ctx.matched_intent != "unknown_intent" else 0.08
        raw = intent_component + score_component + episodic_component + type_fit
        return max(0.0, min(1.0, raw))

    # ------------------------------------------------------------------
    # Grok generation
    # ------------------------------------------------------------------

    def _build_system_prompt(self, ctx: GenerationContext, agent_name: str) -> str:
        """High-quality system prompt incorporating agent context."""
        goals_text = ", ".join(ctx.goals) if ctx.goals else "general contextual assistance"
        return (
            f"You are the resonance generation layer for '{agent_name}', "
            "a sovereign agent on the ForgeResonance Fabric.\n\n"
            "MISSION: Produce hyper-contextual value at the moment of intent — "
            "helpful, specific, and non-interruptive. Never use generic marketing "
            "fluff; ground every field in the supplied intent and agent context.\n\n"
            f"AGENT GOALS: {goals_text}\n"
            f"RESONANCE SCORE: {ctx.resonance_score:.1f}/100 "
            f"(higher = more trusted; lean into proven strengths)\n"
            f"EPISODIC MEMORY:\n{ctx.episodic.summary_text}\n\n"
            f"DETECTED INTENT: {ctx.matched_intent}\n"
            f"INTENT TOPIC: {ctx.topic}\n"
            f"INTENT CONFIDENCE: {ctx.signal_confidence:.2f}\n"
            f"PREFERRED RESONANCE TYPE: {ctx.resonance_type.value}\n\n"
            "RESONANCE TYPE GUIDANCE:\n"
            "- educational: teach, orient, summarize key concepts\n"
            "- comparative: contrast options with clear decision criteria\n"
            "- solution_oriented: diagnose and propose concrete next steps\n"
            "- offer_framed: connect intent to a relevant offer without hard selling\n\n"
            "OUTPUT RULES:\n"
            "- Respond with valid JSON only — no markdown fences or commentary\n"
            f"- Schema: {self.GROK_OUTPUT_SCHEMA}\n"
            "- summary: 1-2 sentences capturing user need\n"
            "- recommended_action: single imperative next step\n"
            "- value_proposition: the resonant message delivered to the user "
            "(2-4 sentences, contextual and actionable)\n"
            "- confidence: your certainty this payload fits the intent (0-1)\n"
            "- quality_estimate: expected resonance quality (0-1)\n"
            "- metadata: optional offer_url, cta_label, resource_links"
        )

    def _build_user_prompt(self, ctx: GenerationContext, signal: IntentSignal) -> str:
        """User turn with signal-specific context vector."""
        extra = {
            k: v
            for k, v in ctx.context_vector.items()
            if k not in ("topic", "matched_intent", "intent")
        }
        extra_json = json.dumps(extra, default=str) if extra else "{}"
        return (
            f"Generate a {ctx.resonance_type.value} resonance payload for "
            f"topic '{ctx.topic}'.\n"
            f"Signal hash: {signal.signal_hash}\n"
            f"Additional context: {extra_json}"
        )

    def _generate_with_grok(
        self,
        ctx: GenerationContext,
        signal: IntentSignal,
        agent_memory: AgentMemory,
    ) -> ResonancePayload | None:
        """Call Grok via xAI REST API with full agent and episodic context."""
        system_prompt = self._build_system_prompt(ctx, agent_memory.agent_name)
        user_prompt = self._build_user_prompt(ctx, signal)
        url = f"{self._base_url}/chat/completions"
        body = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
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
            return self._payload_from_parsed(
                parsed,
                ctx,
                signal,
                agent_memory,
                generation="grok",
            )
        except Exception as exc:
            logger.error("Grok API error: %s", exc)
            return None

    def _payload_from_parsed(
        self,
        parsed: dict[str, Any],
        ctx: GenerationContext,
        signal: IntentSignal,
        agent_memory: AgentMemory,
        *,
        generation: str,
    ) -> ResonancePayload:
        """Normalize Grok or template dict into a structured payload."""
        summary = str(
            parsed.get("summary")
            or parsed.get("message")
            or f"Contextual guidance for {ctx.topic}"
        )
        value_prop = str(
            parsed.get("value_proposition")
            or parsed.get("message")
            or summary
        )
        recommended = str(
            parsed.get("recommended_action")
            or self._default_action(ctx)
        )
        resonance_type = str(
            parsed.get("resonance_type", ctx.resonance_type.value)
        )
        payload_confidence = float(
            parsed.get("confidence", ctx.signal_confidence)
        )
        payload_confidence = max(0.0, min(1.0, payload_confidence))

        quality = float(parsed.get("quality_estimate", self._estimate_quality(ctx)))
        quality = max(0.0, min(1.0, quality))

        metadata = dict(parsed.get("metadata") or {})
        offer_hint = parsed.get("offer_hint")
        if offer_hint and "offer_id" not in metadata:
            metadata["offer_id"] = offer_hint

        logger.info(
            "%s resonance generated: model=%s topic=%s type=%s quality=%.2f",
            generation.capitalize(),
            self._model if generation == "grok" else "template",
            ctx.topic,
            resonance_type,
            quality,
        )

        return ResonancePayload.from_structured(
            summary=summary,
            recommended_action=recommended,
            value_proposition=value_prop,
            confidence=payload_confidence,
            resonance_type=resonance_type,
            quality_estimate=quality,
            metadata=metadata,
            offer_id=offer_hint or metadata.get("offer_id"),
            extra_content={
                "topic": ctx.topic,
                "matched_intent": ctx.matched_intent,
                "context_hash": signal.signal_hash,
                "goals": list(ctx.goals[:5]),
                "generation": generation,
                "model": self._model if generation == "grok" else None,
                "episodic_summary": ctx.episodic.summary_text,
                "resonance_score": ctx.resonance_score,
            },
        )

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
            return {
                "summary": text[:200],
                "value_proposition": text,
                "recommended_action": "Review the guidance above",
                "quality_estimate": 0.65,
                "confidence": 0.6,
            }

    # ------------------------------------------------------------------
    # Template fallback
    # ------------------------------------------------------------------

    def _generate_template(
        self,
        ctx: GenerationContext,
        signal: IntentSignal,
        agent_memory: AgentMemory,
    ) -> ResonancePayload:
        """Context-aware local generation when Grok is unavailable."""
        builder = _TEMPLATE_BUILDERS.get(
            ctx.resonance_type,
            _build_educational_template,
        )
        parsed = builder(ctx, agent_memory)
        quality = self._estimate_quality(ctx)
        # High-confidence intents get a small template boost
        if ctx.signal_confidence >= 0.7:
            quality = min(1.0, quality + 0.05)
        parsed["quality_estimate"] = quality
        parsed["confidence"] = ctx.signal_confidence
        parsed["resonance_type"] = ctx.resonance_type.value
        return self._payload_from_parsed(
            parsed,
            ctx,
            signal,
            agent_memory,
            generation="template",
        )

    @staticmethod
    def _default_action(ctx: GenerationContext) -> str:
        """Fallback recommended action by resonance type."""
        actions = {
            ResonanceType.EDUCATIONAL: f"Review a concise overview of {ctx.topic}",
            ResonanceType.COMPARATIVE: f"Compare top options for {ctx.topic} side by side",
            ResonanceType.SOLUTION_ORIENTED: f"Apply the first fix for {ctx.topic}",
            ResonanceType.OFFER_FRAMED: f"Explore the best-fit offer for {ctx.topic}",
        }
        return actions.get(ctx.resonance_type, f"Explore options for {ctx.topic}")


# ------------------------------------------------------------------
# Template builders (intent-type + confidence aware)
# ------------------------------------------------------------------


def _goal_phrase(ctx: GenerationContext) -> str:
    if ctx.goals:
        return ctx.goals[0]
    return "your goals"


def _episodic_phrase(ctx: GenerationContext) -> str:
    if ctx.episodic.episode_count == 0:
        return "This is our first resonance together."
    rate = int(ctx.episodic.success_rate * 100)
    return (
        f"Drawing on {ctx.episodic.episode_count} past resonance(s) "
        f"({rate}% positive outcomes, avg quality {ctx.episodic.avg_quality:.2f})."
    )


def _confidence_tone(confidence: float) -> str:
    if confidence >= 0.75:
        return "high-confidence"
    if confidence >= 0.5:
        return "moderate-confidence"
    return "emerging"


def _build_educational_template(
    ctx: GenerationContext,
    agent_memory: AgentMemory,
) -> dict[str, Any]:
    tone = _confidence_tone(ctx.signal_confidence)
    summary = (
        f"{tone.capitalize()} research intent detected around '{ctx.topic}'."
    )
    value = (
        f"As {agent_memory.agent_name}, here's a focused orientation on {ctx.topic}: "
        f"start with fundamentals, then narrow to what matters for {_goal_phrase(ctx)}. "
        f"{_episodic_phrase(ctx)}"
    )
    if ctx.episodic.recent_topics:
        value += f" Related past topics: {', '.join(ctx.episodic.recent_topics[:3])}."
    return {
        "summary": summary,
        "value_proposition": value,
        "recommended_action": f"Read a 5-minute overview of {ctx.topic}",
        "metadata": {"resource_type": "overview"},
    }


def _build_comparative_template(
    ctx: GenerationContext,
    agent_memory: AgentMemory,
) -> dict[str, Any]:
    score_note = ""
    if ctx.resonance_score >= 60:
        score_note = (
            f" With a Resonance Score of {ctx.resonance_score:.0f}, "
            "prioritize criteria-backed comparisons over hype."
        )
    summary = f"Comparison intent for '{ctx.topic}' — evaluate trade-offs explicitly."
    value = (
        f"{agent_memory.agent_name} suggests a structured comparison for {ctx.topic}: "
        f"list must-have features, cost, and fit for {_goal_phrase(ctx)}.{score_note} "
        f"{_episodic_phrase(ctx)}"
    )
    return {
        "summary": summary,
        "value_proposition": value,
        "recommended_action": f"Build a comparison matrix for {ctx.topic}",
        "metadata": {"resource_type": "comparison_matrix"},
    }


def _build_solution_template(
    ctx: GenerationContext,
    agent_memory: AgentMemory,
) -> dict[str, Any]:
    urgency = "urgent" if ctx.signal_confidence >= 0.7 else "exploratory"
    summary = f"{urgency.capitalize()} problem-solving intent around '{ctx.topic}'."
    value = (
        f"{agent_memory.agent_name} can help resolve {ctx.topic}: "
        f"1) isolate the symptom, 2) check common causes, 3) apply the smallest fix "
        f"that advances {_goal_phrase(ctx)}. {_episodic_phrase(ctx)}"
    )
    if ctx.episodic.avg_quality < 0.4 and ctx.episodic.episode_count > 0:
        value += " Adjusting approach based on mixed past outcomes."
    return {
        "summary": summary,
        "value_proposition": value,
        "recommended_action": f"Run the first diagnostic step for {ctx.topic}",
        "metadata": {"resource_type": "troubleshooting_guide"},
    }


def _build_offer_template(
    ctx: GenerationContext,
    agent_memory: AgentMemory,
) -> dict[str, Any]:
    visibility = ctx.resonance_score / 100.0
    framing = "direct" if ctx.signal_confidence >= 0.65 else "soft"
    summary = (
        f"{framing.capitalize()}-framed purchase/evaluation intent for '{ctx.topic}'."
    )
    value = (
        f"Based on your interest in {ctx.topic}, {agent_memory.agent_name} "
        f"recommends an offer aligned with {_goal_phrase(ctx)}. "
        f"Visibility weight: {visibility:.2f} (Resonance Score {ctx.resonance_score:.0f}). "
        f"{_episodic_phrase(ctx)}"
    )
    metadata: dict[str, Any] = {
        "resource_type": "offer",
        "cta_label": "View recommended offer",
        "visibility": visibility,
    }
    if ctx.signal_confidence >= 0.6:
        metadata["offer_url"] = f"/offers/{ctx.topic.replace(' ', '-').lower()}"
    return {
        "summary": summary,
        "value_proposition": value,
        "recommended_action": f"Review the recommended offer for {ctx.topic}",
        "metadata": metadata,
        "offer_hint": metadata.get("offer_url"),
    }


_TEMPLATE_BUILDERS = {
    ResonanceType.EDUCATIONAL: _build_educational_template,
    ResonanceType.COMPARATIVE: _build_comparative_template,
    ResonanceType.SOLUTION_ORIENTED: _build_solution_template,
    ResonanceType.OFFER_FRAMED: _build_offer_template,
}


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