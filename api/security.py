"""
Authentication, rate limiting, and request context for serverless API routes.
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from threading import Lock
from typing import Any, Callable

from api.errors import ApiError, format_error_response
from utils.logging import emit_axiom_event, setup_logging

logger = setup_logging("forge.api")


@dataclass(frozen=True)
class AuthPolicy:
    """Per-route Bearer token policy."""

    env_key: str
    required_when_configured: bool = True
    allow_anonymous_when_unconfigured: bool = True


@dataclass(frozen=True)
class RequestContext:
    """Per-request metadata for logging and error correlation."""

    request_id: str
    route: str
    method: str
    client_ip: str


@dataclass
class _RateBucket:
    window_start: float
    count: int = 0


class InMemoryRateLimiter:
    """Fixed-window in-memory rate limiter (per route + client IP)."""

    def __init__(self) -> None:
        self._buckets: dict[str, _RateBucket] = {}
        self._lock = Lock()

    def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """
        Return (allowed, retry_after_seconds).

        When limit is exceeded, ``retry_after_seconds`` is time until window reset.
        """
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or now - bucket.window_start >= window_seconds:
                self._buckets[key] = _RateBucket(window_start=now, count=1)
                return True, 0
            if bucket.count >= limit:
                retry = max(1, int(window_seconds - (now - bucket.window_start)))
                return False, retry
            bucket.count += 1
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_rate_limiter = InMemoryRateLimiter()


def get_rate_limiter() -> InMemoryRateLimiter:
    return _rate_limiter


def reset_rate_limiter() -> None:
    _rate_limiter.reset()


def get_client_ip(handler: BaseHTTPRequestHandler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = handler.headers.get("X-Real-Ip", "")
    if real_ip:
        return real_ip.strip()
    if handler.client_address:
        return str(handler.client_address[0])
    return "unknown"


def resolve_request_id(handler: BaseHTTPRequestHandler) -> str:
    for header in ("X-Request-Id", "X-Correlation-Id", "X-Vercel-Id"):
        value = handler.headers.get(header, "").strip()
        if value:
            return value[:128]
    return uuid.uuid4().hex[:16]


def build_request_context(
    handler: BaseHTTPRequestHandler,
    route: str,
    *,
    method: str | None = None,
) -> RequestContext:
    return RequestContext(
        request_id=resolve_request_id(handler),
        route=route,
        method=method or getattr(handler, "command", "GET"),
        client_ip=get_client_ip(handler),
    )


def _resolve_secret(env_key: str) -> str:
    import os

    return os.getenv(env_key, "").strip()


def check_bearer_auth(handler: BaseHTTPRequestHandler, policy: AuthPolicy) -> None:
    """Raise ``ApiError`` when Bearer auth fails."""
    secret = _resolve_secret(policy.env_key)
    if not secret:
        if policy.allow_anonymous_when_unconfigured:
            return
        raise ApiError.unauthorized(f"{policy.env_key} is not configured")

    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise ApiError.unauthorized("Bearer token required")

    token = auth[7:].strip()
    if not token or not secrets.compare_digest(token, secret):
        raise ApiError.unauthorized("Invalid bearer token")


def enforce_rate_limit(
    ctx: RequestContext,
    *,
    route_key: str,
    limit: int,
    window_seconds: int,
    enabled: bool,
) -> None:
    if not enabled:
        return
    bucket_key = f"{route_key}:{ctx.client_ip}"
    allowed, retry_after = get_rate_limiter().check(
        bucket_key,
        limit=limit,
        window_seconds=window_seconds,
    )
    if not allowed:
        raise ApiError.rate_limited(retry_after_s=retry_after)


def log_request_start(ctx: RequestContext, *, extra: dict[str, Any] | None = None) -> None:
    fields = {
        "request_id": ctx.request_id,
        "route": ctx.route,
        "method": ctx.method,
        "client_ip": ctx.client_ip,
    }
    if extra:
        fields.update(extra)
    logger.info(
        "api_request_start request_id=%s route=%s method=%s client_ip=%s",
        ctx.request_id,
        ctx.route,
        ctx.method,
        ctx.client_ip,
    )
    emit_axiom_event("api_request_start", fields)


def log_request_complete(
    ctx: RequestContext,
    *,
    status: int,
    duration_ms: float,
    extra: dict[str, Any] | None = None,
) -> None:
    fields = {
        "request_id": ctx.request_id,
        "route": ctx.route,
        "method": ctx.method,
        "status": status,
        "duration_ms": duration_ms,
    }
    if extra:
        fields.update(extra)
    logger.info(
        "api_request_complete request_id=%s route=%s status=%d duration_ms=%.1f",
        ctx.request_id,
        ctx.route,
        status,
        duration_ms,
    )
    emit_axiom_event("api_request_complete", fields)


def log_request_error(ctx: RequestContext, error: ApiError) -> None:
    logger.warning(
        "api_request_error request_id=%s route=%s code=%s message=%s",
        ctx.request_id,
        ctx.route,
        error.code.value,
        error.message,
    )
    emit_axiom_event(
        "api_request_error",
        {
            "request_id": ctx.request_id,
            "route": ctx.route,
            "error_code": error.code.value,
            "status": error.status,
        },
    )


def send_json_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: dict[str, Any],
    *,
    extra_headers: dict[str, str] | None = None,
) -> None:
    import json

    payload = json.dumps(body, default=str).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    if extra_headers:
        for key, value in extra_headers.items():
            handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(payload)


def send_success(
    handler: BaseHTTPRequestHandler,
    ctx: RequestContext,
    body: dict[str, Any],
    *,
    status: int = 200,
) -> None:
    enriched = {"request_id": ctx.request_id, **body}
    send_json_response(handler, status, enriched)


def send_api_error(
    handler: BaseHTTPRequestHandler,
    ctx: RequestContext,
    error: ApiError,
) -> None:
    log_request_error(ctx, error)
    extra: dict[str, str] = {}
    if error.status == 429 and isinstance(error.details, dict):
        retry = error.details.get("retry_after_s")
        if retry is not None:
            extra["Retry-After"] = str(retry)
    send_json_response(
        handler,
        error.status,
        format_error_response(error, ctx.request_id),
        extra_headers=extra,
    )


def run_api_handler(
    handler: BaseHTTPRequestHandler,
    ctx: RequestContext,
    fn: Callable[[], dict[str, Any]],
    *,
    success_status: int = 200,
) -> None:
    """Execute a route handler with standardized error handling and logging."""
    start = time.perf_counter()
    log_request_start(ctx)
    try:
        result = fn()
        duration_ms = (time.perf_counter() - start) * 1000.0
        send_success(handler, ctx, result, status=success_status)
        log_request_complete(ctx, status=success_status, duration_ms=duration_ms)
    except ApiError as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        send_api_error(handler, ctx, exc)
        log_request_complete(ctx, status=exc.status, duration_ms=duration_ms)
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000.0
        logger.exception(
            "api_unhandled_error request_id=%s route=%s",
            ctx.request_id,
            ctx.route,
        )
        emit_axiom_event(
            "api_unhandled_error",
            {"request_id": ctx.request_id, "route": ctx.route},
        )
        internal = ApiError.internal()
        send_api_error(handler, ctx, internal)
        log_request_complete(ctx, status=500, duration_ms=duration_ms)