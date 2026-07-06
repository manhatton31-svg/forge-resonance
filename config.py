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

# ---------------------------------------------------------------------------
# Observability (Sentry + Axiom + Cloudflare)
# ---------------------------------------------------------------------------

SENTRY_DSN = os.getenv("SENTRY_DSN", "")
AXIOM_TOKEN = os.getenv("AXIOM_TOKEN", "")
AXIOM_DATASET = os.getenv("AXIOM_DATASET", "forge-resonance")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Cloudflare Workers binding names (future edge deployment)
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_REPUTATION_KV_NAMESPACE = os.getenv("CF_REPUTATION_KV_NAMESPACE", "")

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
    log_level: str = LOG_LEVEL
    resonance_score_default: float = RESONANCE_SCORE_DEFAULT

    def ensure_directories(self) -> None:
        """Create on-disk data directories if they do not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        AGENT_DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> ForgeConfig:
    """Load configuration from environment with sane defaults."""
    cfg = ForgeConfig()
    cfg.ensure_directories()
    return cfg