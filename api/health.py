"""
Vercel serverless health check endpoint.

Deploy: vercel deploy
Route: GET /api/health
"""

from http.server import BaseHTTPRequestHandler
import json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {
            "status": "ok",
            "service": "forge-resonance",
            "version": "0.1.0",
            "fabric": "operational",
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())