"""
Arcly outcome feedback webhook for Vercel serverless.

Route: POST /api/arcly_feedback

Arcly calls this endpoint when conversion processing completes so
ForgeResonance can update Resonance Scores asynchronously.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler

from integration.arcly_handoff import ArclyHandoff
from reputation.score_layer import create_score_manager


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        expected_key = os.getenv("ARCLY_API_KEY", "")
        auth = self.headers.get("Authorization", "")
        if expected_key and auth != f"Bearer {expected_key}":
            self._respond(401, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode() if length else "{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid json"})
            return

        agent_id = body.get("agent_id")
        resonance_id = body.get("resonance_id")
        outcome = body.get("outcome")
        if not agent_id or not resonance_id or not outcome:
            self._respond(400, {"error": "agent_id, resonance_id, outcome required"})
            return

        handoff = ArclyHandoff(score_manager=create_score_manager())
        report = handoff.report_outcome(
            agent_id,
            resonance_id,
            outcome,
            quality=body.get("quality"),
            conversion_id=body.get("conversion_id"),
            metadata=body.get("metadata"),
            intent_signal_hash=body.get("signal_hash", ""),
        )

        self._respond(200, {
            "recorded": report.recorded,
            "outcome": report.outcome.value,
            "message": report.message,
            "new_score": (
                report.score_update.new_score if report.score_update else None
            ),
        })

    def _respond(self, status: int, body: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())