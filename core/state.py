"""
Agent state persistence for ForgeResonance.

Tracks runtime lifecycle state (idle, sensing, resonating, handoff)
separately from memory content. State survives restarts via file persistence
and syncs agent metadata to Neon when available.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from config import AGENT_DATA_DIR, load_config
from utils.logging import setup_logging

logger = setup_logging("forge.state")


class AgentLifecycle(str, Enum):
    """Discrete lifecycle phases of a sovereign resonance agent."""

    INITIALIZING = "initializing"
    IDLE = "idle"
    SENSING = "sensing"
    MATCHING = "matching"
    RESONATING = "resonating"
    INJECTING = "injecting"
    HANDOFF = "handoff"
    REFLECTING = "reflecting"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class AgentState:
    """Serializable snapshot of an agent's runtime state."""

    agent_id: str
    agent_name: str
    lifecycle: AgentLifecycle = AgentLifecycle.INITIALIZING
    resonance_score: float = 50.0
    current_resonance_id: str | None = None
    last_intent_hash: str | None = None
    loop_count: int = 0
    last_error: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = field(default_factory=dict)

    def transition(self, new_phase: AgentLifecycle) -> None:
        """Move to a new lifecycle phase and stamp the update time."""
        logger.debug(
            "Agent '%s' transition: %s → %s",
            self.agent_name,
            self.lifecycle.value,
            new_phase.value,
        )
        self.lifecycle = new_phase
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["lifecycle"] = self.lifecycle.value
        d["updated_at"] = self.updated_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentState:
        return cls(
            agent_id=data["agent_id"],
            agent_name=data["agent_name"],
            lifecycle=AgentLifecycle(data.get("lifecycle", "idle")),
            resonance_score=data.get("resonance_score", 50.0),
            current_resonance_id=data.get("current_resonance_id"),
            last_intent_hash=data.get("last_intent_hash"),
            loop_count=data.get("loop_count", 0),
            last_error=data.get("last_error"),
            updated_at=datetime.fromisoformat(
                data.get("updated_at", datetime.now(timezone.utc).isoformat())
            ),
            context=data.get("context", {}),
        )


class StateManager:
    """Persists and retrieves agent state from local JSON files."""

    def __init__(self, base_dir: Path | None = None) -> None:
        cfg = load_config()
        cfg.ensure_directories()
        self._base_dir = base_dir or (AGENT_DATA_DIR / "state")
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, agent_name: str) -> Path:
        safe = agent_name.replace("/", "_").replace("\\", "_")
        return self._base_dir / f"{safe}_state.json"

    def load(self, agent_id: str, agent_name: str) -> AgentState:
        path = self._path(agent_name)
        if not path.exists():
            return AgentState(agent_id=agent_id, agent_name=agent_name)
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        state = AgentState.from_dict(data)
        state.agent_id = agent_id
        return state

    def save(self, state: AgentState) -> None:
        state.updated_at = datetime.now(timezone.utc)
        path = self._path(state.agent_name)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2, default=str)
        logger.debug("State saved for agent '%s' [%s]", state.agent_name, state.lifecycle.value)

    def reset(self, state: AgentState) -> None:
        """Reset agent to idle, clearing transient context."""
        state.current_resonance_id = None
        state.last_intent_hash = None
        state.last_error = None
        state.context = {}
        state.transition(AgentLifecycle.IDLE)
        self.save(state)