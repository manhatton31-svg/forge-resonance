"""
Vercel serverless health check endpoint.

Route: GET /api/health
Query: ?deep=1 for database ping + fabric health (slower cold start)
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api.runtime import build_health_payload, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        deep = params.get("deep", ["0"])[0] in ("1", "true", "yes")
        send_json(self, 200, build_health_payload(deep=deep))