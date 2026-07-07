"""
Root API index — lightweight landing for the ForgeResonance Vercel deployment.

Route: GET /api
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from forge_resonance import __version__


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = {
            "service": "forge-resonance",
            "version": __version__,
            "status": "ok",
            "endpoints": [
                "/api/health",
                "/api/fabric_health",
                "/api/swarm",
                "/api/arcly_feedback",
            ],
        }
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)