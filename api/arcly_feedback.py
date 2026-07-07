"""
Arcly outcome feedback webhook for Vercel serverless.

Route: POST /api/arcly_feedback
Auth: Bearer ARCLY_API_KEY (required when configured and API_ARCLY_AUTH_REQUIRED=true)
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from api.runtime import get_reputation_layer, read_json_body
from api.security import (
    AuthPolicy,
    build_request_context,
    check_bearer_auth,
    enforce_rate_limit,
    run_api_handler,
)
from api.validation import validate_arcly_feedback_body
from config import load_api_security_config
from integration.arcly_handoff import ArclyHandoff


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        ctx = build_request_context(self, "/api/arcly_feedback", method="POST")
        security = load_api_security_config()

        def _handle() -> dict:
            if security.arcly_auth_required or security.arcly_api_key:
                check_bearer_auth(
                    self,
                    AuthPolicy(
                        env_key="ARCLY_API_KEY",
                        required_when_configured=security.arcly_auth_required,
                    ),
                )
            enforce_rate_limit(
                ctx,
                route_key="arcly_feedback",
                limit=security.rate_limit_arcly,
                window_seconds=security.rate_limit_window_seconds,
                enabled=security.rate_limit_enabled,
            )
            body = validate_arcly_feedback_body(read_json_body(self))
            handoff = ArclyHandoff(score_manager=get_reputation_layer().score_manager)
            report = handoff.report_outcome(
                body["agent_id"],
                body["resonance_id"],
                body["outcome"],
                quality=body.get("quality"),
                conversion_id=body.get("conversion_id"),
                metadata=body.get("metadata"),
                intent_signal_hash=body.get("signal_hash", ""),
            )
            return {
                "recorded": report.recorded,
                "outcome": report.outcome.value,
                "message": report.message,
                "new_score": (
                    report.score_update.new_score if report.score_update else None
                ),
            }

        run_api_handler(self, ctx, _handle)