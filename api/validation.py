"""
Request body validation for serverless API endpoints.
"""

from __future__ import annotations

from typing import Any

from api.errors import ApiError, validation_detail
from fabric.swarm import ConsensusStrategy, SwarmStrategy


def _require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ApiError.validation(
            "Request validation failed",
            details=[validation_detail(field, "must be an object")],
        )
    return value


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError.validation(
            "Request validation failed",
            details=[validation_detail(field, "must be a non-empty string")],
        )
    return value.strip()


def validate_swarm_body(body: dict[str, Any]) -> dict[str, Any]:
    """Validate POST /api/swarm body; returns normalized body."""
    details: list[dict[str, str]] = []

    mode = str(body.get("mode", "route")).lower()
    if mode not in ("route", "execute"):
        details.append(validation_detail("mode", "must be 'route' or 'execute'"))

    intent_raw = body.get("intent") or body.get("signal")
    if intent_raw is None:
        details.append(validation_detail("intent", "required object"))
    elif not isinstance(intent_raw, dict):
        details.append(validation_detail("intent", "must be an object"))
    else:
        if not any(
            intent_raw.get(k) for k in ("matched_intent", "text", "topic", "raw_text")
        ):
            details.append(
                validation_detail(
                    "intent",
                    "must include matched_intent, text, topic, or raw_text",
                )
            )
        confidence = body.get("confidence", intent_raw.get("confidence", 0.75))
        try:
            conf = float(confidence)
            if not 0.0 <= conf <= 1.0:
                details.append(validation_detail("confidence", "must be between 0 and 1"))
        except (TypeError, ValueError):
            details.append(validation_detail("confidence", "must be a number"))

    agents = body.get("agents")
    if not isinstance(agents, list) or len(agents) == 0:
        details.append(validation_detail("agents", "required non-empty array"))
    else:
        for index, agent in enumerate(agents):
            if not isinstance(agent, dict):
                details.append(
                    validation_detail(f"agents[{index}]", "must be an object")
                )
                continue
            if not agent.get("agent_id"):
                details.append(
                    validation_detail(f"agents[{index}].agent_id", "required")
                )

    strategy = str(body.get("strategy", SwarmStrategy.BEST_SINGLE.value))
    try:
        SwarmStrategy(strategy)
    except ValueError:
        details.append(
            validation_detail("strategy", "must be best_single or broadcast_top_n")
        )

    if "top_n" in body:
        try:
            top_n = int(body["top_n"])
            if top_n < 1 or top_n > 20:
                details.append(validation_detail("top_n", "must be between 1 and 20"))
        except (TypeError, ValueError):
            details.append(validation_detail("top_n", "must be an integer"))

    if "consensus_strategy" in body:
        try:
            ConsensusStrategy(str(body["consensus_strategy"]))
        except ValueError:
            details.append(
                validation_detail(
                    "consensus_strategy",
                    "must be majority or quality_weighted",
                )
            )

    bound = body.get("bound_agents")
    if bound is not None:
        if not isinstance(bound, list):
            details.append(validation_detail("bound_agents", "must be an array"))
        else:
            for index, entry in enumerate(bound):
                if not isinstance(entry, dict):
                    details.append(
                        validation_detail(f"bound_agents[{index}]", "must be an object")
                    )
                elif not entry.get("agent_id"):
                    details.append(
                        validation_detail(
                            f"bound_agents[{index}].agent_id",
                            "required",
                        )
                    )

    if "timeout_s" in body and body["timeout_s"] is not None:
        try:
            timeout = float(body["timeout_s"])
            if timeout <= 0:
                details.append(validation_detail("timeout_s", "must be positive"))
        except (TypeError, ValueError):
            details.append(validation_detail("timeout_s", "must be a number"))

    if details:
        raise ApiError.validation("Request validation failed", details=details)

    return body


def validate_arcly_feedback_body(body: dict[str, Any]) -> dict[str, Any]:
    """Validate POST /api/arcly_feedback body."""
    details: list[dict[str, str]] = []

    for field in ("agent_id", "resonance_id", "outcome"):
        value = body.get(field)
        if not isinstance(value, str) or not value.strip():
            details.append(validation_detail(field, "required non-empty string"))

    if "quality" in body and body["quality"] is not None:
        try:
            quality = float(body["quality"])
            if not 0.0 <= quality <= 1.0:
                details.append(validation_detail("quality", "must be between 0 and 1"))
        except (TypeError, ValueError):
            details.append(validation_detail("quality", "must be a number"))

    if "metadata" in body and body["metadata"] is not None:
        if not isinstance(body["metadata"], dict):
            details.append(validation_detail("metadata", "must be an object"))

    if details:
        raise ApiError.validation("Request validation failed", details=details)

    return body