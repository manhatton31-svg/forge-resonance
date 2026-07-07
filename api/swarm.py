"""
Swarm routing and execution endpoint for Vercel serverless.

Route: POST /api/swarm
Auth: Bearer FORGE_API_KEY (required when configured)
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from api.runtime import read_json_body, run_swarm_execute, run_swarm_route
from api.security import (
    AuthPolicy,
    build_request_context,
    check_bearer_auth,
    enforce_rate_limit,
    run_api_handler,
)
from api.validation import validate_swarm_body
from config import load_api_security_config


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        ctx = build_request_context(self, "/api/swarm", method="POST")
        security = load_api_security_config()

        def _handle() -> dict:
            check_bearer_auth(
                self,
                AuthPolicy(env_key="FORGE_API_KEY", required_when_configured=True),
            )
            enforce_rate_limit(
                ctx,
                route_key="swarm",
                limit=security.rate_limit_swarm,
                window_seconds=security.rate_limit_window_seconds,
                enabled=security.rate_limit_enabled,
            )
            body = validate_swarm_body(read_json_body(self))
            mode = str(body.get("mode", "route")).lower()
            if mode == "execute":
                return run_swarm_execute(body)
            return run_swarm_route(body)

        run_api_handler(self, ctx, _handle)

    def do_GET(self):
        ctx = build_request_context(self, "/api/swarm", method="GET")
        security = load_api_security_config()

        def _handle() -> dict:
            return {
                "endpoint": "/api/swarm",
                "methods": ["POST"],
                "modes": ["route", "execute"],
                "auth": {
                    "type": "bearer",
                    "env_key": "FORGE_API_KEY",
                    "required_when_configured": True,
                    "configured": bool(security.forge_api_key),
                },
                "rate_limit": {
                    "enabled": security.rate_limit_enabled,
                    "limit": security.rate_limit_swarm,
                    "window_seconds": security.rate_limit_window_seconds,
                },
            }

        run_api_handler(self, ctx, _handle)