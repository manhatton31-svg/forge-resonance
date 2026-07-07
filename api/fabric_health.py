"""
Fabric health endpoint — reputation storage and edge KV status.

Route: GET /api/fabric_health (public)
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api.runtime import build_fabric_health_payload
from api.security import build_request_context, run_api_handler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ctx = build_request_context(self, "/api/fabric_health", method="GET")
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        raw_ids = params.get("agent_ids", [""])[0]
        agent_ids = [a.strip() for a in raw_ids.split(",") if a.strip()] or None

        def _handle() -> dict:
            return build_fabric_health_payload(agent_ids)

        run_api_handler(self, ctx, _handle)