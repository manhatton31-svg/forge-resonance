"""
Tests for API production hardening (auth, rate limits, errors, validation).

Run with: python -m pytest tests/test_api_hardening.py -v
"""

from __future__ import annotations

import io
from http.server import BaseHTTPRequestHandler
from unittest.mock import MagicMock

import pytest

from api.errors import ApiError, ErrorCode, format_error_response
from api.security import (
    AuthPolicy,
    InMemoryRateLimiter,
    build_request_context,
    check_bearer_auth,
    enforce_rate_limit,
    reset_rate_limiter,
)
from api.validation import validate_arcly_feedback_body, validate_swarm_body


class _MockHandler(BaseHTTPRequestHandler):
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.client_address = ("127.0.0.1", 12345)
        self.command = "POST"

    def log_message(self, format: str, *args) -> None:
        return


class TestErrorFormat:
    def test_format_error_response_shape(self):
        err = ApiError.validation(
            "bad input",
            details=[{"field": "agents", "message": "required"}],
        )
        payload = format_error_response(err, "req-abc")
        assert payload["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
        assert payload["error"]["message"] == "bad input"
        assert payload["error"]["request_id"] == "req-abc"
        assert payload["error"]["details"][0]["field"] == "agents"

    def test_internal_error_hides_details(self):
        err = ApiError.internal()
        payload = format_error_response(err, "req-xyz")
        assert payload["error"]["code"] == "internal_error"
        assert "traceback" not in str(payload).lower()


class TestBearerAuth:
    def test_allows_when_secret_unconfigured(self, monkeypatch):
        monkeypatch.delenv("FORGE_API_KEY", raising=False)
        handler = _MockHandler()
        check_bearer_auth(handler, AuthPolicy(env_key="FORGE_API_KEY"))

    def test_rejects_missing_bearer(self, monkeypatch):
        monkeypatch.setenv("FORGE_API_KEY", "secret-key")
        handler = _MockHandler()
        with pytest.raises(ApiError) as exc:
            check_bearer_auth(handler, AuthPolicy(env_key="FORGE_API_KEY"))
        assert exc.value.status == 401

    def test_rejects_invalid_token(self, monkeypatch):
        monkeypatch.setenv("FORGE_API_KEY", "secret-key")
        handler = _MockHandler({"Authorization": "Bearer wrong"})
        with pytest.raises(ApiError) as exc:
            check_bearer_auth(handler, AuthPolicy(env_key="FORGE_API_KEY"))
        assert exc.value.code == ErrorCode.UNAUTHORIZED

    def test_accepts_valid_token(self, monkeypatch):
        monkeypatch.setenv("FORGE_API_KEY", "secret-key")
        handler = _MockHandler({"Authorization": "Bearer secret-key"})
        check_bearer_auth(handler, AuthPolicy(env_key="FORGE_API_KEY"))


class TestRateLimiter:
    def setup_method(self) -> None:
        reset_rate_limiter()

    def test_allows_under_limit(self):
        from api.security import RequestContext, get_rate_limiter

        limiter = get_rate_limiter()
        allowed, _ = limiter.check("swarm:1.2.3.4", limit=3, window_seconds=60)
        assert allowed is True

    def test_blocks_over_limit(self):
        from api.security import get_rate_limiter

        limiter = get_rate_limiter()
        for _ in range(3):
            limiter.check("swarm:1.2.3.4", limit=3, window_seconds=60)
        allowed, retry = limiter.check("swarm:1.2.3.4", limit=3, window_seconds=60)
        assert allowed is False
        assert retry >= 1

    def test_enforce_rate_limit_raises(self):
        from api.security import RequestContext

        ctx = RequestContext("r1", "/api/swarm", "POST", "9.9.9.9")
        for _ in range(2):
            enforce_rate_limit(
                ctx,
                route_key="swarm",
                limit=2,
                window_seconds=60,
                enabled=True,
            )
        with pytest.raises(ApiError) as exc:
            enforce_rate_limit(
                ctx,
                route_key="swarm",
                limit=2,
                window_seconds=60,
                enabled=True,
            )
        assert exc.value.code == ErrorCode.RATE_LIMITED
        assert exc.value.status == 429


class TestValidation:
    def test_swarm_requires_agents(self):
        with pytest.raises(ApiError) as exc:
            validate_swarm_body({"intent": {"matched_intent": "purchase_intent"}})
        assert exc.value.code == ErrorCode.VALIDATION_ERROR
        assert any(d["field"] == "agents" for d in exc.value.details)

    def test_swarm_valid_body(self):
        body = validate_swarm_body({
            "mode": "route",
            "intent": {"matched_intent": "purchase_intent", "confidence": 0.8},
            "agents": [{"agent_id": "atlas", "name": "atlas-analytics"}],
        })
        assert body["mode"] == "route"

    def test_swarm_rejects_invalid_mode(self):
        with pytest.raises(ApiError) as exc:
            validate_swarm_body({
                "mode": "fly",
                "intent": {"matched_intent": "x"},
                "agents": [{"agent_id": "a"}],
            })
        assert any(d["field"] == "mode" for d in exc.value.details)

    def test_arcly_requires_fields(self):
        with pytest.raises(ApiError) as exc:
            validate_arcly_feedback_body({"agent_id": "a"})
        fields = {d["field"] for d in exc.value.details}
        assert "resonance_id" in fields
        assert "outcome" in fields

    def test_arcly_valid_body(self):
        body = validate_arcly_feedback_body({
            "agent_id": "agent-1",
            "resonance_id": "res-1",
            "outcome": "success",
            "quality": 0.9,
        })
        assert body["outcome"] == "success"


class TestRequestContext:
    def test_uses_correlation_header(self):
        handler = _MockHandler({"X-Request-Id": "corr-123"})
        ctx = build_request_context(handler, "/api/health", method="GET")
        assert ctx.request_id == "corr-123"
        assert ctx.client_ip == "127.0.0.1"