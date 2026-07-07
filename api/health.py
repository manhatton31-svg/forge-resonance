"""
Vercel serverless health check endpoint.

Route: GET /api/health
Query: ?deep=1 for database ping + fabric health (requires Bearer when configured)
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api.runtime import build_health_payload
from api.security import (
    AuthPolicy,
    build_request_context,
    check_bearer_auth,
    run_api_handler,
)
from config import load_api_security_config


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ctx = build_request_context(self, "/api/health", method="GET")
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        deep = params.get("deep", ["0"])[0] in ("1", "true", "yes")
        security = load_api_security_config()

        def _handle() -> dict:
            if deep and security.health_deep_auth and security.forge_api_key:
                check_bearer_auth(
                    self,
                    AuthPolicy(env_key="FORGE_API_KEY", required_when_configured=True),
                )
            return build_health_payload(deep=deep)

        run_api_handler(self, ctx, _handle)