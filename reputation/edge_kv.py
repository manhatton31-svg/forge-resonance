"""
Cloudflare KV client for Edge Reputation replication.

KV acts as a fast edge cache for Resonance Scores and visibility multipliers.
Neon/SQLite remain the authoritative source of truth; KV is written after
local persistence and read when local state is cold (no outcome history).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from config import load_edge_reputation_config
from config import EdgeReputationConfig
from reputation.multiplier import get_visibility_multiplier
from utils.logging import setup_logging

logger = setup_logging("forge.edge_kv")

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
RequestFn = Callable[..., Any]


@dataclass
class EdgeReputationRecord:
    """Serialized reputation snapshot stored in KV."""

    agent_id: str
    score: float
    visibility_multiplier: float
    synced_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "agent_id": self.agent_id,
            "score": self.score,
            "visibility_multiplier": self.visibility_multiplier,
            "synced_at": self.synced_at,
            "metadata": self.metadata,
        })

    @classmethod
    def from_json(cls, raw: str, *, agent_id: str = "") -> EdgeReputationRecord | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in KV record for agent=%s", agent_id)
            return None
        if not isinstance(data, dict):
            return None
        return cls(
            agent_id=str(data.get("agent_id") or agent_id),
            score=float(data.get("score", 0.0)),
            visibility_multiplier=float(data.get("visibility_multiplier", 0.0)),
            synced_at=str(data.get("synced_at", "")),
            metadata=dict(data.get("metadata") or {}),
        )


class CloudflareKVClient:
    """
    REST client for Cloudflare Workers KV namespace reputation cache.

    Configure via ``EdgeReputationConfig`` (environment-driven). When disabled
    or misconfigured, all methods no-op or return ``None`` without raising.
    """

    def __init__(
        self,
        config: EdgeReputationConfig | None = None,
        *,
        request_fn: RequestFn | None = None,
    ) -> None:
        self._config = config or load_edge_reputation_config()
        self._request_fn = request_fn or _default_http_request
        self._last_sync_at: dict[str, str] = {}
        self._last_reachable_check: str | None = None
        self._last_reachable: bool | None = None

    @property
    def config(self) -> EdgeReputationConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.is_configured

    def _kv_key(self, agent_id: str) -> str:
        return f"{self._config.key_prefix}{agent_id}"

    def _values_url(self, agent_id: str) -> str:
        encoded_key = quote(self._kv_key(agent_id), safe="")
        return (
            f"{CLOUDFLARE_API_BASE}/accounts/{self._config.account_id}"
            f"/storage/kv/namespaces/{self._config.namespace_id}"
            f"/values/{encoded_key}"
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_token}",
            "Content-Type": "application/json",
        }

    def get_record(self, agent_id: str) -> EdgeReputationRecord | None:
        """Fetch full reputation record from KV."""
        if not self.enabled:
            return None
        try:
            status, body = self._request_fn(
                "GET",
                self._values_url(agent_id),
                headers=self._headers(),
                timeout=self._config.timeout_seconds,
            )
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            logger.warning("KV get failed for agent=%s: %s", agent_id, exc)
            return None

        if status == 404:
            return None
        if status < 200 or status >= 300:
            logger.warning(
                "KV get unexpected status=%s for agent=%s", status, agent_id
            )
            return None

        text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
        return EdgeReputationRecord.from_json(text, agent_id=agent_id)

    def get_score(self, agent_id: str) -> float | None:
        """Return cached Resonance Score from KV, or ``None`` if missing."""
        record = self.get_record(agent_id)
        return record.score if record else None

    def get_visibility_multiplier(self, agent_id: str) -> float | None:
        """Return cached visibility multiplier from KV, or ``None`` if missing."""
        record = self.get_record(agent_id)
        if record:
            return record.visibility_multiplier
        return None

    def set_score(
        self,
        agent_id: str,
        score: float,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Write score to KV; visibility derived from score."""
        visibility = get_visibility_multiplier(score)
        return self.sync_score(
            agent_id,
            score,
            visibility,
            metadata=metadata,
        )

    def sync_score(
        self,
        agent_id: str,
        score: float,
        visibility_multiplier: float,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Write score + visibility snapshot to KV.

        Returns ``True`` on success, ``False`` when disabled or on failure.
        """
        if not self.enabled:
            logger.debug("Edge KV disabled; sync skipped for agent=%s", agent_id)
            return False

        record = EdgeReputationRecord(
            agent_id=agent_id,
            score=score,
            visibility_multiplier=visibility_multiplier,
            synced_at=datetime.now(timezone.utc).isoformat(),
            metadata=dict(metadata or {}),
        )

        try:
            status, _ = self._request_fn(
                "PUT",
                self._values_url(agent_id),
                headers=self._headers(),
                body=record.to_json().encode("utf-8"),
                timeout=self._config.timeout_seconds,
            )
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            logger.warning("KV sync failed for agent=%s: %s", agent_id, exc)
            return False

        if status < 200 or status >= 300:
            logger.warning(
                "KV sync unexpected status=%s for agent=%s", status, agent_id
            )
            return False

        synced_at = record.synced_at
        self._last_sync_at[agent_id] = synced_at
        logger.info(
            "Edge KV synced: agent=%s score=%.2f visibility=%.2f",
            agent_id,
            score,
            visibility_multiplier,
        )
        return True

    def get_last_sync_time(self, agent_id: str) -> str | None:
        """Return ISO timestamp of last successful sync for an agent."""
        return self._last_sync_at.get(agent_id)

    def ping(self) -> bool:
        """Lightweight reachability check (namespace metadata GET)."""
        if not self.enabled:
            self._last_reachable = False
            return False
        url = (
            f"{CLOUDFLARE_API_BASE}/accounts/{self._config.account_id}"
            f"/storage/kv/namespaces/{self._config.namespace_id}"
        )
        try:
            status, _ = self._request_fn(
                "GET",
                url,
                headers=self._headers(),
                timeout=self._config.timeout_seconds,
            )
            reachable = 200 <= status < 300
        except (HTTPError, URLError, TimeoutError, OSError):
            reachable = False
        self._last_reachable = reachable
        self._last_reachable_check = datetime.now(timezone.utc).isoformat()
        return reachable

    @property
    def last_reachable_check(self) -> str | None:
        return self._last_reachable_check


def _default_http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 10.0,
) -> tuple[int, bytes]:
    """Perform an HTTP request; returns (status_code, response_body)."""
    req = Request(url, data=body, headers=headers or {}, method=method)
    with urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


_edge_kv_singleton: CloudflareKVClient | None = None


def create_edge_kv_client(
    config: EdgeReputationConfig | None = None,
    *,
    reuse: bool = True,
) -> CloudflareKVClient:
    """
    Factory for CloudflareKVClient from environment config.

    When ``reuse=True`` (default) and no explicit config is passed, returns a
    module-level singleton so warm serverless invocations reuse the REST client
    state (reachability cache, last sync timestamps).
    """
    global _edge_kv_singleton
    if config is not None:
        return CloudflareKVClient(config=config)
    if reuse:
        if _edge_kv_singleton is None:
            _edge_kv_singleton = CloudflareKVClient(
                config=load_edge_reputation_config()
            )
        return _edge_kv_singleton
    return CloudflareKVClient(config=load_edge_reputation_config())


def reset_edge_kv_client() -> None:
    """Clear the cached client (for tests or config hot-reload)."""
    global _edge_kv_singleton
    _edge_kv_singleton = None