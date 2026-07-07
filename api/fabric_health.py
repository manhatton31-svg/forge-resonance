"""
Fabric health endpoint — reputation storage and edge KV status.

Route: GET /api/fabric_health
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api.runtime import build_fabric_health_payload, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        raw_ids = params.get("agent_ids", [""])[0]
        agent_ids = [a.strip() for a in raw_ids.split(",") if a.strip()] or None
        send_json(self, 200, build_fabric_health_payload(agent_ids))