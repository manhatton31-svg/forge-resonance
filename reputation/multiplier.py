"""
Visibility multiplier for the ForgeResonance reputation layer.

Maps Resonance Score (0–100) to a distribution weight (0.1–2.0) used when
selecting agents in a multi-agent network.
"""

from __future__ import annotations

from config import (
    RESONANCE_SCORE_MAX,
    RESONANCE_SCORE_MIN,
    VISIBILITY_CEILING,
    VISIBILITY_FLOOR,
)


def get_visibility_multiplier(score: float) -> float:
    """
    Return a visibility weight for the given Resonance Score.

    Linear map from score range [0, 100] to multiplier range
    [VISIBILITY_FLOOR, VISIBILITY_CEILING] (default 0.1 – 2.0).
    """
    clamped = max(RESONANCE_SCORE_MIN, min(RESONANCE_SCORE_MAX, score))
    span = RESONANCE_SCORE_MAX - RESONANCE_SCORE_MIN
    if span <= 0:
        return VISIBILITY_FLOOR
    normalized = (clamped - RESONANCE_SCORE_MIN) / span
    return VISIBILITY_FLOOR + normalized * (VISIBILITY_CEILING - VISIBILITY_FLOOR)