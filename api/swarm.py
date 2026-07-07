"""
Swarm routing and execution endpoint for Vercel serverless.

Route: POST /api/swarm

Body:
  mode: "route" | "execute" (default route)
  intent: { matched_intent, text?, confidence? }
  agents: [{ agent_id, name, goals?, specialties? }]
  bound_agents: optional for execute — ephemeral agent stubs
  strategy: best_single | broadcast_top_n
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler

from api.runtime import (
    read_json_body,
    run_swarm_execute,
    run_swarm_route,
    send_json,
    verify_bearer,
)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        api_key = os.getenv("FORGE_API_KEY", "")
        if not verify_bearer(self, api_key):
            send_json(self, 401, {"error": "unauthorized"})
            return

        try:
            body = read_json_body(self)
        except (ValueError, json.JSONDecodeError):
            send_json(self, 400, {"error": "invalid json body"})
            return

        mode = str(body.get("mode", "route")).lower()
        try:
            if mode == "execute":
                result = run_swarm_execute(body)
            elif mode == "route":
                result = run_swarm_route(body)
            else:
                send_json(self, 400, {"error": "mode must be route or execute"})
                return
        except ValueError as exc:
            send_json(self, 400, {"error": str(exc)})
            return
        except Exception as exc:
            send_json(self, 500, {"error": "swarm_failed", "detail": str(exc)})
            return

        send_json(self, 200, result)

    def do_GET(self):
        send_json(
            self,
            200,
            {
                "endpoint": "/api/swarm",
                "methods": ["POST"],
                "modes": ["route", "execute"],
                "auth": "Bearer FORGE_API_KEY (optional when unset)",
            },
        )