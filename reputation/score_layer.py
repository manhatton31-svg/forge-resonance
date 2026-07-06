"""
Decentralized Reputation / Resonance Score Layer.

Aggregates agent scores across the Fabric and provides visibility
weighting for resonance matching. Future deployment on Cloudflare
Workers + KV for edge-native, low-latency reputation lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import CF_REPUTATION_KV_NAMESPACE, DATABASE_URL
from core.scoring import ResonanceScorer, ScoreUpdate, create_scorer
from utils.logging import setup_logging

logger = setup_logging("forge.reputation")


@dataclass
class AgentReputation:
    """Public reputation snapshot for an agent on the Fabric."""

    agent_id: str
    agent_name: str
    resonance_score: float
    visibility_multiplier: float
    total_resonances: int = 0
    success_rate: float = 0.0


class ReputationLayer:
    """
    Fabric-wide reputation aggregation.

    Reads from Neon Postgres in centralized mode; designed for
    replication to Cloudflare KV for decentralized edge lookups.
    """

    def __init__(self, scorer: ResonanceScorer | None = None) -> None:
        self._scorer = scorer or create_scorer()
        self._cf_kv_namespace = CF_REPUTATION_KV_NAMESPACE

    def get_reputation(self, agent_id: str, agent_name: str = "") -> AgentReputation:
        """Fetch current reputation for an agent."""
        score = self._scorer.get_score(agent_id)
        visibility = self._scorer.visibility_for(agent_id)
        return AgentReputation(
            agent_id=agent_id,
            agent_name=agent_name,
            resonance_score=score,
            visibility_multiplier=visibility,
        )

    def rank_agents(
        self,
        agent_ids: list[str],
        *,
        min_visibility: float = 0.0,
    ) -> list[AgentReputation]:
        """
        Rank agents by Resonance Score for matching prioritization.

        Agents below min_visibility are excluded from active matching.
        """
        reputations = [
            self.get_reputation(aid) for aid in agent_ids
        ]
        eligible = [
            r for r in reputations if r.visibility_multiplier >= min_visibility
        ]
        return sorted(eligible, key=lambda r: r.resonance_score, reverse=True)

    def sync_to_edge(self, update: ScoreUpdate) -> None:
        """
        Push score update to Cloudflare KV for edge reputation cache.

        Requires CF_REPUTATION_KV_NAMESPACE binding in production.
        """
        if not self._cf_kv_namespace:
            logger.debug("Cloudflare KV not configured; edge sync skipped")
            return
        logger.info(
            "Edge sync queued: agent=%s score=%.2f",
            update.agent_id,
            update.new_score,
        )

    def fabric_health(self) -> dict[str, Any]:
        """Return aggregate Fabric health metrics."""
        return {
            "storage": "neon" if DATABASE_URL else "local",
            "edge_sync": bool(self._cf_kv_namespace),
            "score_range": [0.0, 100.0],
        }