"""
ForgeResonance configuration.

Centralizes environment-driven settings for agents, storage backends,
xAI/Grok integration, Arcly handoff, and observability hooks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
AGENT_DATA_DIR = DATA_DIR / "agents"
SQLITE_PATH = DATA_DIR / "forge_resonance.db"

# ---------------------------------------------------------------------------
# Storage backend selection
# ---------------------------------------------------------------------------

StorageBackend = Literal["file", "sqlite", "neon", "hybrid"]

DEFAULT_STORAGE_BACKEND: StorageBackend = os.getenv(
    "FORGE_STORAGE_BACKEND", "hybrid"
)  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Neon Postgres (provisioned via Neon MCP — project: forge-resonance)
# ---------------------------------------------------------------------------

NEON_PROJECT_ID = os.getenv("NEON_PROJECT_ID", "late-glade-09092928")
NEON_BRANCH_ID = os.getenv("NEON_BRANCH_ID", "br-jolly-mountain-adw7q2vw")
NEON_DATABASE = os.getenv("NEON_DATABASE", "neondb")

# Connection string MUST be supplied via environment — never hardcode credentials.
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ---------------------------------------------------------------------------
# Deployment / serverless (Vercel)
# ---------------------------------------------------------------------------

VERCEL = os.getenv("VERCEL", "") == "1"
VERCEL_ENV = os.getenv("VERCEL_ENV", "development")
VERCEL_REGION = os.getenv("VERCEL_REGION", "")
VERCEL_URL = os.getenv("VERCEL_URL", "")

# Cap per-function duration on Vercel (seconds). Hobby default is 10; Pro up to 60+.
VERCEL_FUNCTION_MAX_DURATION = int(os.getenv("VERCEL_FUNCTION_MAX_DURATION", "60"))

# When true, apply serverless-safe defaults (shorter swarm timeouts, less parallelism).
SERVERLESS_MODE = (
    os.getenv("SERVERLESS_MODE", "auto").lower() == "true"
    or (os.getenv("SERVERLESS_MODE", "auto").lower() == "auto" and VERCEL)
)


def is_serverless() -> bool:
    """True when running inside a serverless host (Vercel, Lambda, etc.)."""
    if SERVERLESS_MODE:
        return True
    if VERCEL:
        return True
    return os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None


def is_secret_configured(name: str) -> bool:
    """Return whether an environment variable is set (never expose the value)."""
    return bool(os.getenv(name, "").strip())


def redact_env_snapshot() -> dict[str, bool]:
    """Safe snapshot of which secrets are configured — for health endpoints only."""
    return {
        "database_url": is_secret_configured("DATABASE_URL"),
        "xai_api_key": is_secret_configured("XAI_API_KEY"),
        "arcly_api_key": is_secret_configured("ARCLY_API_KEY"),
        "cloudflare_api_token": is_secret_configured("CLOUDFLARE_API_TOKEN"),
        "cloudflare_kv_namespace": is_secret_configured("CLOUDFLARE_KV_NAMESPACE"),
        "sentry_dsn": is_secret_configured("SENTRY_DSN"),
        "axiom_token": is_secret_configured("AXIOM_TOKEN"),
    }


def get_deployment_info() -> dict[str, str | bool]:
    """Deployment context for observability and health checks."""
    return {
        "platform": "vercel" if VERCEL else "local",
        "environment": VERCEL_ENV,
        "region": VERCEL_REGION,
        "serverless": is_serverless(),
        "function_max_duration_s": VERCEL_FUNCTION_MAX_DURATION,
    }

# ---------------------------------------------------------------------------
# Resonance Score parameters
# ---------------------------------------------------------------------------

RESONANCE_SCORE_MIN = 0.0
RESONANCE_SCORE_MAX = 100.0
RESONANCE_SCORE_DEFAULT = 50.0

# Score deltas applied per outcome tier
SCORE_DELTA_SUCCESS = float(os.getenv("SCORE_DELTA_SUCCESS", "2.5"))
SCORE_DELTA_PARTIAL = float(os.getenv("SCORE_DELTA_PARTIAL", "0.5"))
SCORE_DELTA_FAILURE = float(os.getenv("SCORE_DELTA_FAILURE", "-1.5"))
SCORE_DELTA_REJECTION = float(os.getenv("SCORE_DELTA_REJECTION", "-3.0"))

# Visibility multiplier derived from score (used by reputation layer)
VISIBILITY_FLOOR = float(os.getenv("VISIBILITY_FLOOR", "0.1"))
VISIBILITY_CEILING = float(os.getenv("VISIBILITY_CEILING", "2.0"))
VISIBILITY_MULTIPLIER_MAX = VISIBILITY_CEILING

# ---------------------------------------------------------------------------
# xAI / Grok
# ---------------------------------------------------------------------------

XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")
GROK_TEMPERATURE = float(os.getenv("GROK_TEMPERATURE", "0.55"))
GROK_MAX_TOKENS = int(os.getenv("GROK_MAX_TOKENS", "1024"))

# ---------------------------------------------------------------------------
# Arcly integration
# ---------------------------------------------------------------------------

ARCLY_API_URL = os.getenv("ARCLY_API_URL", "http://localhost:8000")
ARCLY_API_KEY = os.getenv("ARCLY_API_KEY", "")
ARCLY_HANDOFF_TIMEOUT_SECONDS = int(os.getenv("ARCLY_HANDOFF_TIMEOUT", "30"))
ARCLY_HANDOFF_MAX_RETRIES = int(os.getenv("ARCLY_HANDOFF_MAX_RETRIES", "2"))
ARCLY_HANDOFF_RETRY_DELAY_SECONDS = float(
    os.getenv("ARCLY_HANDOFF_RETRY_DELAY", "1.0")
)
# Mode: auto (live when key+url configured) | dry_run | live
ARCLY_MODE = os.getenv("ARCLY_MODE", "auto").lower()
ARCLY_FEEDBACK_ENABLED = os.getenv("ARCLY_FEEDBACK_ENABLED", "true").lower() == "true"
ARCLY_DEFAULT_URL = "http://localhost:8000"


@dataclass(frozen=True)
class ArclyConfig:
    """Arcly handoff configuration snapshot."""

    api_url: str = ARCLY_API_URL
    api_key: str = ARCLY_API_KEY
    timeout_seconds: int = ARCLY_HANDOFF_TIMEOUT_SECONDS
    max_retries: int = ARCLY_HANDOFF_MAX_RETRIES
    retry_delay_seconds: float = ARCLY_HANDOFF_RETRY_DELAY_SECONDS
    mode: str = ARCLY_MODE
    feedback_enabled: bool = ARCLY_FEEDBACK_ENABLED

    @property
    def effective_mode(self) -> str:
        if self.mode == "dry_run":
            return "dry_run"
        if self.mode == "live":
            return "live"
        # auto: live when credentials and non-local URL are set
        if self.api_key and self.api_url.rstrip("/") != ARCLY_DEFAULT_URL:
            return "live"
        return "dry_run"

    @property
    def is_live(self) -> bool:
        return self.effective_mode == "live"


def load_arcly_config() -> ArclyConfig:
    """Load Arcly configuration from environment."""
    return ArclyConfig(
        api_url=ARCLY_API_URL.rstrip("/"),
        api_key=ARCLY_API_KEY,
        timeout_seconds=ARCLY_HANDOFF_TIMEOUT_SECONDS,
        max_retries=ARCLY_HANDOFF_MAX_RETRIES,
        retry_delay_seconds=ARCLY_HANDOFF_RETRY_DELAY_SECONDS,
        mode=ARCLY_MODE,
        feedback_enabled=ARCLY_FEEDBACK_ENABLED,
    )

# ---------------------------------------------------------------------------
# Observability (Sentry + Axiom + Cloudflare)
# ---------------------------------------------------------------------------

SENTRY_DSN = os.getenv("SENTRY_DSN", "")
AXIOM_TOKEN = os.getenv("AXIOM_TOKEN", "")
AXIOM_DATASET = os.getenv("AXIOM_DATASET", "forge-resonance")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Cloudflare edge reputation (M4 — KV replication layer)
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_REPUTATION_KV_NAMESPACE = os.getenv("CF_REPUTATION_KV_NAMESPACE", "")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", os.getenv("CF_API_TOKEN", ""))
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", CF_ACCOUNT_ID)
CLOUDFLARE_KV_NAMESPACE = os.getenv(
    "CLOUDFLARE_KV_NAMESPACE", CF_REPUTATION_KV_NAMESPACE
)
CLOUDFLARE_KV_KEY_PREFIX = os.getenv("CLOUDFLARE_KV_KEY_PREFIX", "reputation:")
CLOUDFLARE_KV_TIMEOUT_SECONDS = float(os.getenv("CLOUDFLARE_KV_TIMEOUT", "10"))
EDGE_REPUTATION_ENABLED = (
    os.getenv("EDGE_REPUTATION_ENABLED", "false").lower() == "true"
)
EdgeReadPreference = Literal["edge_first", "local_first", "local_only"]
_EDGE_READ_RAW = os.getenv("EDGE_READ_PREFERENCE", "edge_first").lower()
EDGE_READ_PREFERENCE: EdgeReadPreference = (
    _EDGE_READ_RAW
    if _EDGE_READ_RAW in ("edge_first", "local_first", "local_only")
    else "edge_first"
)


@dataclass(frozen=True)
class EdgeReputationConfig:
    """Cloudflare KV edge reputation cache configuration."""

    enabled: bool = EDGE_REPUTATION_ENABLED
    api_token: str = CLOUDFLARE_API_TOKEN
    account_id: str = CLOUDFLARE_ACCOUNT_ID
    namespace_id: str = CLOUDFLARE_KV_NAMESPACE
    key_prefix: str = CLOUDFLARE_KV_KEY_PREFIX
    timeout_seconds: float = CLOUDFLARE_KV_TIMEOUT_SECONDS
    read_preference: EdgeReadPreference = EDGE_READ_PREFERENCE

    @property
    def is_configured(self) -> bool:
        """True when edge sync is enabled and all required credentials are set."""
        return bool(
            self.enabled
            and self.api_token
            and self.account_id
            and self.namespace_id
        )


def load_edge_reputation_config() -> EdgeReputationConfig:
    """Load edge reputation settings from environment."""
    return EdgeReputationConfig(
        enabled=EDGE_REPUTATION_ENABLED,
        api_token=CLOUDFLARE_API_TOKEN,
        account_id=CLOUDFLARE_ACCOUNT_ID or CF_ACCOUNT_ID,
        namespace_id=CLOUDFLARE_KV_NAMESPACE or CF_REPUTATION_KV_NAMESPACE,
        key_prefix=CLOUDFLARE_KV_KEY_PREFIX,
        timeout_seconds=CLOUDFLARE_KV_TIMEOUT_SECONDS,
        read_preference=EDGE_READ_PREFERENCE,
    )

# ---------------------------------------------------------------------------
# Firecrawl (future intent enrichment)
# ---------------------------------------------------------------------------

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
FIRECRAWL_ENABLED = os.getenv("FIRECRAWL_ENABLED", "false").lower() == "true"

# Intent harvesting thresholds
INTENT_RESONANCE_THRESHOLD = float(os.getenv("INTENT_RESONANCE_THRESHOLD", "0.35"))
INTENT_SIMILARITY_THRESHOLD = float(os.getenv("INTENT_SIMILARITY_THRESHOLD", "0.55"))
INTENT_MULTI_TURN_LIMIT = int(os.getenv("INTENT_MULTI_TURN_LIMIT", "5"))

# ---------------------------------------------------------------------------
# Agent runtime
# ---------------------------------------------------------------------------

AGENT_LOOP_INTERVAL_SECONDS = float(os.getenv("AGENT_LOOP_INTERVAL", "5.0"))
WORKING_MEMORY_TTL_SECONDS = int(os.getenv("WORKING_MEMORY_TTL", "3600"))
EPISODIC_MEMORY_LIMIT = int(os.getenv("EPISODIC_MEMORY_LIMIT", "1000"))

# ---------------------------------------------------------------------------
# Swarm execution (Fabric multi-agent coordination)
# ---------------------------------------------------------------------------

_SWARM_TIMEOUT_DEFAULT = "25.0" if is_serverless() else "120.0"
SWARM_AGENT_TIMEOUT = float(os.getenv("SWARM_AGENT_TIMEOUT", _SWARM_TIMEOUT_DEFAULT))
SWARM_MAX_PARALLEL = max(1, int(os.getenv("SWARM_MAX_PARALLEL", "3")))
SWARM_SERVERLESS_TIMEOUT = float(os.getenv("SWARM_SERVERLESS_TIMEOUT", "25.0"))
SWARM_SERVERLESS_MAX_PARALLEL = max(1, int(os.getenv("SWARM_SERVERLESS_MAX_PARALLEL", "2")))
SwarmConsensusStrategy = Literal["majority", "quality_weighted"]
_SWARM_CONSENSUS_RAW = os.getenv("SWARM_CONSENSUS_STRATEGY", "quality_weighted").lower()
SWARM_CONSENSUS_STRATEGY: SwarmConsensusStrategy = (
    _SWARM_CONSENSUS_RAW
    if _SWARM_CONSENSUS_RAW in ("majority", "quality_weighted")
    else "quality_weighted"
)


@dataclass(frozen=True)
class SwarmExecutionConfig:
    """Runtime configuration for swarm intent execution."""

    agent_timeout_s: float = SWARM_AGENT_TIMEOUT
    max_parallel: int = SWARM_MAX_PARALLEL
    consensus_strategy: SwarmConsensusStrategy = SWARM_CONSENSUS_STRATEGY


def load_swarm_config() -> SwarmExecutionConfig:
    """Load swarm execution settings from environment."""
    timeout = SWARM_AGENT_TIMEOUT
    max_parallel = SWARM_MAX_PARALLEL
    if is_serverless():
        if timeout <= 0 or timeout > SWARM_SERVERLESS_TIMEOUT:
            timeout = SWARM_SERVERLESS_TIMEOUT
        max_parallel = min(max_parallel, SWARM_SERVERLESS_MAX_PARALLEL)
        max_duration = float(VERCEL_FUNCTION_MAX_DURATION)
        if max_duration > 0:
            timeout = min(timeout, max(5.0, max_duration - 5.0))
    return SwarmExecutionConfig(
        agent_timeout_s=timeout,
        max_parallel=max_parallel,
        consensus_strategy=SWARM_CONSENSUS_STRATEGY,
    )


@dataclass
class ForgeConfig:
    """Immutable runtime configuration snapshot."""

    storage_backend: StorageBackend = DEFAULT_STORAGE_BACKEND
    database_url: str = DATABASE_URL
    neon_project_id: str = NEON_PROJECT_ID
    data_dir: Path = field(default_factory=lambda: DATA_DIR)
    grok_model: str = GROK_MODEL
    grok_temperature: float = GROK_TEMPERATURE
    grok_max_tokens: int = GROK_MAX_TOKENS
    xai_api_key: str = XAI_API_KEY
    arcly_api_url: str = ARCLY_API_URL
    arcly_api_key: str = ARCLY_API_KEY
    arcly_mode: str = ARCLY_MODE
    arcly_timeout_seconds: int = ARCLY_HANDOFF_TIMEOUT_SECONDS
    log_level: str = LOG_LEVEL
    resonance_score_default: float = RESONANCE_SCORE_DEFAULT
    edge_reputation_enabled: bool = EDGE_REPUTATION_ENABLED
    swarm_agent_timeout: float = SWARM_AGENT_TIMEOUT
    swarm_max_parallel: int = SWARM_MAX_PARALLEL
    swarm_consensus_strategy: SwarmConsensusStrategy = SWARM_CONSENSUS_STRATEGY

    def ensure_directories(self) -> None:
        """Create on-disk data directories if they do not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        AGENT_DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> ForgeConfig:
    """Load configuration from environment with sane defaults."""
    cfg = ForgeConfig()
    if not is_serverless():
        cfg.ensure_directories()
    return cfg


def ping_database(timeout_s: float = 3.0) -> dict[str, bool | str]:
    """Lightweight Neon/Postgres reachability check for deployment health."""
    if not DATABASE_URL:
        return {"configured": False, "reachable": False, "detail": "not_configured"}
    try:
        import psycopg2

        conn = psycopg2.connect(DATABASE_URL, connect_timeout=int(timeout_s))
        conn.close()
        return {"configured": True, "reachable": True, "detail": "ok"}
    except Exception as exc:
        return {"configured": True, "reachable": False, "detail": type(exc).__name__}