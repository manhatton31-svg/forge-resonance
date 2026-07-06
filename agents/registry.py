"""
Agent Registry — directory of sovereign agents on the Fabric.

Tracks agent metadata (goals, specialties, load) for capability-based routing
and reputation-weighted swarm selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from core.resonance_agent import ResonanceAgent
from utils.logging import setup_logging

logger = setup_logging("forge.registry")


@dataclass
class RegisteredAgent:
    """Metadata entry for an agent available on the Fabric."""

    agent_id: str
    name: str
    goals: list[str] = field(default_factory=list)
    specialties: list[str] = field(default_factory=list)
    current_load: int = 0
    max_load: int = 10
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_capacity(self) -> bool:
        return self.active and self.current_load < self.max_load

    @property
    def load_ratio(self) -> float:
        if self.max_load <= 0:
            return 1.0
        return min(1.0, self.current_load / self.max_load)

    @classmethod
    def from_resonance_agent(
        cls,
        agent: ResonanceAgent,
        *,
        specialties: list[str] | None = None,
        max_load: int = 10,
        metadata: dict[str, Any] | None = None,
    ) -> RegisteredAgent:
        """Build a registry entry from a live ``ResonanceAgent``."""
        return cls(
            agent_id=agent.agent_id,
            name=agent.name,
            goals=list(agent.goals),
            specialties=list(specialties or []),
            max_load=max_load,
            metadata=dict(metadata or {}),
        )


class AgentRegistry:
    """
    In-memory agent directory for Fabric routing.

    Supports registration, capability queries, and load tracking.
    """

    def __init__(self) -> None:
        self._agents: dict[str, RegisteredAgent] = {}

    def __len__(self) -> int:
        return len(self._agents)

    def __iter__(self) -> Iterator[RegisteredAgent]:
        return iter(self._agents.values())

    def register(self, entry: RegisteredAgent) -> None:
        """Register or replace an agent entry."""
        self._agents[entry.agent_id] = entry
        logger.debug("Registered agent=%s name=%s", entry.agent_id, entry.name)

    def register_agent(
        self,
        agent: ResonanceAgent,
        *,
        specialties: list[str] | None = None,
        max_load: int = 10,
        metadata: dict[str, Any] | None = None,
    ) -> RegisteredAgent:
        """Register a live ``ResonanceAgent`` and return the entry."""
        entry = RegisteredAgent.from_resonance_agent(
            agent,
            specialties=specialties,
            max_load=max_load,
            metadata=metadata,
        )
        self.register(entry)
        return entry

    def unregister(self, agent_id: str) -> bool:
        return self._agents.pop(agent_id, None) is not None

    def get(self, agent_id: str) -> RegisteredAgent | None:
        return self._agents.get(agent_id)

    def list_all(self, *, active_only: bool = True) -> list[RegisteredAgent]:
        agents = list(self._agents.values())
        if active_only:
            agents = [a for a in agents if a.active]
        return agents

    def list_available(self) -> list[RegisteredAgent]:
        """Active agents with remaining capacity."""
        return [a for a in self._agents.values() if a.has_capacity]

    def agent_ids(self, *, available_only: bool = False) -> list[str]:
        source = self.list_available() if available_only else self.list_all()
        return [a.agent_id for a in source]

    def increment_load(self, agent_id: str, amount: int = 1) -> None:
        entry = self._agents.get(agent_id)
        if entry:
            entry.current_load = min(entry.max_load, entry.current_load + amount)

    def decrement_load(self, agent_id: str, amount: int = 1) -> None:
        entry = self._agents.get(agent_id)
        if entry:
            entry.current_load = max(0, entry.current_load - amount)

    def query_by_specialty(self, specialty: str) -> list[RegisteredAgent]:
        """Return agents whose specialties or goals mention ``specialty``."""
        needle = specialty.lower()
        matches: list[RegisteredAgent] = []
        for agent in self.list_all():
            searchable = " ".join(agent.specialties + agent.goals).lower()
            if needle in searchable:
                matches.append(agent)
        return matches

    def query_by_intent_label(self, intent_label: str) -> list[RegisteredAgent]:
        """Return agents likely suited for an intent category."""
        from fabric.capabilities import specialties_for_intent

        targets = specialties_for_intent(intent_label)
        if not targets:
            return self.list_available()

        scored: list[tuple[float, RegisteredAgent]] = []
        for agent in self.list_available():
            from fabric.capabilities import capability_score_for_agent

            score = capability_score_for_agent(agent, intent_label)
            if score > 0.1:
                scored.append((score, agent))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [agent for _, agent in scored]

    def top_by_reputation(
        self,
        ranked_ids: list[str],
        *,
        limit: int | None = None,
    ) -> list[RegisteredAgent]:
        """Order registry entries by a pre-ranked agent id list."""
        by_id = self._agents
        ordered = [by_id[aid] for aid in ranked_ids if aid in by_id]
        if limit is not None:
            return ordered[:limit]
        return ordered