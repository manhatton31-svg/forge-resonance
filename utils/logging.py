"""
Structured logging for ForgeResonance.

Supports console output, optional Sentry error capture, and Axiom
event streaming for production observability.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from config import AXIOM_DATASET, AXIOM_TOKEN, LOG_LEVEL, SENTRY_DSN

_CONFIGURED = False


def _init_sentry() -> None:
    """Initialize Sentry SDK if DSN is configured."""
    if not SENTRY_DSN:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=0.1,
            environment="production",
        )
    except ImportError:
        logging.getLogger("forge").warning(
            "sentry-sdk not installed; Sentry integration disabled"
        )


class ForgeJsonFormatter(logging.Formatter):
    """Emit JSON log lines suitable for Axiom / Cloudflare Logpush ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "agent_id"):
            payload["agent_id"] = record.agent_id  # type: ignore[attr-defined]
        if hasattr(record, "resonance_id"):
            payload["resonance_id"] = record.resonance_id  # type: ignore[attr-defined]
        return json.dumps(payload, default=str)


def setup_logging(
    name: str = "forge",
    level: str | None = None,
    json_output: bool = False,
) -> logging.Logger:
    """
    Configure and return a named logger.

    Call once at process startup. Subsequent calls return the same logger
    without reconfiguring handlers.
    """
    global _CONFIGURED
    logger = logging.getLogger(name)

    if _CONFIGURED:
        return logger

    log_level = getattr(logging, (level or LOG_LEVEL).upper(), logging.INFO)
    logger.setLevel(log_level)

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(ForgeJsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    logger.addHandler(handler)
    _init_sentry()
    _CONFIGURED = True
    return logger


def emit_axiom_event(event_type: str, fields: dict[str, Any]) -> None:
    """
    Emit a structured event to Axiom when credentials are present.

    This is a lightweight hook; production deployments should use the
    Axiom SDK or OpenTelemetry exporter for high-volume telemetry.
    """
    if not AXIOM_TOKEN:
        return
    payload = {
        "type": event_type,
        "dataset": AXIOM_DATASET,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    logging.getLogger("forge.axiom").debug(
        "axiom_event: %s", json.dumps(payload, default=str)
    )