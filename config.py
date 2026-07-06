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

    def ensure_directories(self) -> None:
        """Create on-disk data directories if they do not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        AGENT_DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> ForgeConfig:
    """Load configuration from environment with sane defaults."""
    cfg = ForgeConfig()
    cfg.ensure_directories()
    return cfg