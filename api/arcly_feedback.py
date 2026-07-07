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

from api.runtime import get_reputation_layer, send_json, verify_bearer
from integration.arcly_handoff import ArclyHandoff


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        expected_key = os.getenv("ARCLY_API_KEY", "")
        if not verify_bearer(self, expected_key):
            send_json(self, 401, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode() if length else "{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            send_json(self, 400, {"error": "invalid json"})
            return

        agent_id = body.get("agent_id")
        resonance_id = body.get("resonance_id")
        outcome = body.get("outcome")
        if not agent_id or not resonance_id or not outcome:
            send_json(self, 400, {"error": "agent_id, resonance_id, outcome required"})
            return

        handoff = ArclyHandoff(score_manager=get_reputation_layer().score_manager)
        report = handoff.report_outcome(
            agent_id,
            resonance_id,
            outcome,
            quality=body.get("quality"),
            conversion_id=body.get("conversion_id"),
            metadata=body.get("metadata"),
            intent_signal_hash=body.get("signal_hash", ""),
        )

        send_json(self, 200, {
            "recorded": report.recorded,
            "outcome": report.outcome.value,
            "message": report.message,
            "new_score": (
                report.score_update.new_score if report.score_update else None
            ),
        })