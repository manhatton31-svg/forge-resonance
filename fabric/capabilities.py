"""
Intent → agent capability matching for Fabric routing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.registry import RegisteredAgent

# Intent labels map to specialty keywords used in goals/specialties matching.
INTENT_SPECIALTY_MAP: dict[str, tuple[str, ...]] = {
    "purchase_intent": (
        "commercial",
        "conversion",
        "purchase",
        "pricing",
        "analytics",
        "enterprise",
        "quote",
    ),
    "evaluation_intent": (
        "commercial",
        "evaluation",
        "purchase",
        "trial",
        "demo",
    ),
    "research_intent": (
        "research",
        "educate",
        "education",
        "overview",
        "learn",
        "guide",
    ),
    "comparison_intent": (
        "comparison",
        "compare",
        "evaluate",
        "analytics",
        "tools",
        "trade-off",
    ),
    "support_intent": (
        "support",
        "billing",
        "refund",
        "resolve",
        "account",
        "help",
    ),
    "problem_solving_intent": (
        "support",
        "solution",
        "diagnostic",
        "resolve",
        "problem",
    ),
}


def specialties_for_intent(intent_label: str) -> tuple[str, ...]:
    """Return target specialty keywords for an intent label."""
    return INTENT_SPECIALTY_MAP.get(intent_label, ())


def intent_label_from_signal(context_vector: dict) -> str:
    """Extract matched intent label from signal context."""
    return str(
        context_vector.get("matched_intent")
        or context_vector.get("intent")
        or context_vector.get("topic")
        or ""
    )


def capability_score_for_agent(
    agent: RegisteredAgent,
    intent_label: str,
) -> float:
    """
    Score how well an agent's goals/specialties match an intent (0.0 – 1.0).

    Returns 0.5 (neutral) when no intent label or no specialty map exists.
    """
    targets = specialties_for_intent(intent_label)
    if not intent_label or not targets:
        return 0.5

    searchable = " ".join(agent.specialties + agent.goals).lower()
    if not searchable.strip():
        return 0.3

    hits = sum(1 for token in targets if token in searchable)
    if hits == 0:
        return 0.15

    # Scale: one hit ≈ 0.5, multiple hits approach 1.0
    raw = hits / len(targets)
    return min(1.0, 0.35 + raw * 0.85)