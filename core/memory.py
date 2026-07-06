"""
Agent memory subsystem for ForgeResonance.

Provides three storage tiers:
  1. Working memory  — short-lived, in-process + file cache
  2. Episodic memory   — long-term resonance history
  3. Neon Postgres     — production-grade persistence (provisioned via Neon MCP)

The hybrid backend writes to local file/SQLite first, then syncs to Neon
when DATABASE_URL is configured. This keeps agents sovereign and functional
offline while enabling fabric-scale reputation aggregation.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import (
    AGENT_DATA_DIR,
    DATABASE_URL,
    EPISODIC_MEMORY_LIMIT,
    SQLITE_PATH,
    WORKING_MEMORY_TTL_SECONDS,
    load_config,
)
from utils.logging import setup_logging

logger = setup_logging("forge.memory")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class MemoryEntry:
    """A single working-memory key/value pair with optional expiry."""

    key: str
    value: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at


@dataclass
class EpisodicRecord:
    """A past resonance event stored in long-term episodic memory."""

    resonance_id: str
    context: dict[str, Any]
    outcome: str
    quality_score: float | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "resonance_id": self.resonance_id,
            "context": self.context,
            "outcome": self.outcome,
            "quality_score": self.quality_score,
            "recorded_at": self.recorded_at.isoformat(),
        }


@dataclass
class AgentMemory:
    """In-memory representation of an agent's full memory state."""

    agent_id: str
    agent_name: str
    working: dict[str, MemoryEntry] = field(default_factory=dict)
    episodic: list[EpisodicRecord] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract store interface
# ---------------------------------------------------------------------------


class MemoryStore(ABC):
    """Contract for pluggable memory backends."""

    @abstractmethod
    def load(self, agent_name: str) -> AgentMemory:
        ...

    @abstractmethod
    def save(self, memory: AgentMemory) -> None:
        ...

    @abstractmethod
    def set_working(
        self,
        memory: AgentMemory,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        ...

    @abstractmethod
    def record_episode(
        self,
        memory: AgentMemory,
        record: EpisodicRecord,
    ) -> None:
        ...


# ---------------------------------------------------------------------------
# File-based backend (MVP / sovereign local storage)
# ---------------------------------------------------------------------------


class FileMemoryStore(MemoryStore):
    """JSON file persistence — one file per agent under data/agents/."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or AGENT_DATA_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, agent_name: str) -> Path:
        safe_name = agent_name.replace("/", "_").replace("\\", "_")
        return self._base_dir / f"{safe_name}.json"

    def load(self, agent_name: str) -> AgentMemory:
        path = self._path(agent_name)
        if not path.exists():
            agent_id = str(uuid.uuid4())
            logger.info("Creating new file-backed memory for agent '%s'", agent_name)
            return AgentMemory(agent_id=agent_id, agent_name=agent_name)

        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)

        working: dict[str, MemoryEntry] = {}
        for key, entry in raw.get("working", {}).items():
            working[key] = MemoryEntry(
                key=key,
                value=entry["value"],
                created_at=datetime.fromisoformat(entry["created_at"]),
                expires_at=(
                    datetime.fromisoformat(entry["expires_at"])
                    if entry.get("expires_at")
                    else None
                ),
            )

        episodic = [
            EpisodicRecord(
                resonance_id=e["resonance_id"],
                context=e["context"],
                outcome=e["outcome"],
                quality_score=e.get("quality_score"),
                recorded_at=datetime.fromisoformat(e["recorded_at"]),
            )
            for e in raw.get("episodic", [])
        ]

        return AgentMemory(
            agent_id=raw["agent_id"],
            agent_name=agent_name,
            working=working,
            episodic=episodic,
            goals=raw.get("goals", []),
            metadata=raw.get("metadata", {}),
        )

    def save(self, memory: AgentMemory) -> None:
        path = self._path(memory.agent_name)
        payload = {
            "agent_id": memory.agent_id,
            "agent_name": memory.agent_name,
            "goals": memory.goals,
            "metadata": memory.metadata,
            "working": {
                k: {
                    "value": v.value,
                    "created_at": v.created_at.isoformat(),
                    "expires_at": v.expires_at.isoformat() if v.expires_at else None,
                }
                for k, v in memory.working.items()
                if not v.is_expired()
            },
            "episodic": [e.to_dict() for e in memory.episodic[-EPISODIC_MEMORY_LIMIT:]],
        }
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        logger.debug("Saved file memory for agent '%s'", memory.agent_name)

    def set_working(
        self,
        memory: AgentMemory,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds or WORKING_MEMORY_TTL_SECONDS
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        memory.working[key] = MemoryEntry(key=key, value=value, expires_at=expires_at)
        self.save(memory)

    def record_episode(self, memory: AgentMemory, record: EpisodicRecord) -> None:
        memory.episodic.append(record)
        if len(memory.episodic) > EPISODIC_MEMORY_LIMIT:
            memory.episodic = memory.episodic[-EPISODIC_MEMORY_LIMIT:]
        self.save(memory)


# ---------------------------------------------------------------------------
# SQLite backend (local structured queries)
# ---------------------------------------------------------------------------


class SQLiteMemoryStore(MemoryStore):
    """SQLite persistence for agents requiring local structured queries."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or SQLITE_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    goals TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS working_memory (
                    agent_id TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    memory_value TEXT NOT NULL,
                    expires_at TEXT,
                    PRIMARY KEY (agent_id, memory_key)
                );
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    resonance_id TEXT NOT NULL,
                    context TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    quality_score REAL,
                    recorded_at TEXT NOT NULL
                );
                """
            )

    def load(self, agent_name: str) -> AgentMemory:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE name = ?", (agent_name,)
            ).fetchone()
            if row is None:
                agent_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO agents (id, name) VALUES (?, ?)",
                    (agent_id, agent_name),
                )
                return AgentMemory(agent_id=agent_id, agent_name=agent_name)

            agent_id = row["id"]
            working_rows = conn.execute(
                "SELECT * FROM working_memory WHERE agent_id = ?", (agent_id,)
            ).fetchall()
            episodic_rows = conn.execute(
                "SELECT * FROM episodic_memory WHERE agent_id = ? ORDER BY recorded_at DESC LIMIT ?",
                (agent_id, EPISODIC_MEMORY_LIMIT),
            ).fetchall()

        working: dict[str, MemoryEntry] = {}
        for wr in working_rows:
            entry = MemoryEntry(
                key=wr["memory_key"],
                value=json.loads(wr["memory_value"]),
                expires_at=(
                    datetime.fromisoformat(wr["expires_at"])
                    if wr["expires_at"]
                    else None
                ),
            )
            if not entry.is_expired():
                working[entry.key] = entry

        episodic = [
            EpisodicRecord(
                resonance_id=er["resonance_id"],
                context=json.loads(er["context"]),
                outcome=er["outcome"],
                quality_score=er["quality_score"],
                recorded_at=datetime.fromisoformat(er["recorded_at"]),
            )
            for er in reversed(episodic_rows)
        ]

        return AgentMemory(
            agent_id=agent_id,
            agent_name=agent_name,
            working=working,
            episodic=episodic,
            goals=json.loads(row["goals"]),
            metadata=json.loads(row["metadata"]),
        )

    def save(self, memory: AgentMemory) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agents (id, name, goals, metadata)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET goals=excluded.goals, metadata=excluded.metadata
                """,
                (
                    memory.agent_id,
                    memory.agent_name,
                    json.dumps(memory.goals),
                    json.dumps(memory.metadata),
                ),
            )
        logger.debug("Saved SQLite memory for agent '%s'", memory.agent_name)

    def set_working(
        self,
        memory: AgentMemory,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds or WORKING_MEMORY_TTL_SECONDS
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
        memory.working[key] = MemoryEntry(
            key=key,
            value=value,
            expires_at=datetime.fromisoformat(expires_at),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO working_memory (agent_id, memory_key, memory_value, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(agent_id, memory_key) DO UPDATE SET
                    memory_value=excluded.memory_value, expires_at=excluded.expires_at
                """,
                (memory.agent_id, key, json.dumps(value, default=str), expires_at),
            )

    def record_episode(self, memory: AgentMemory, record: EpisodicRecord) -> None:
        memory.episodic.append(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episodic_memory
                    (agent_id, resonance_id, context, outcome, quality_score, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.agent_id,
                    record.resonance_id,
                    json.dumps(record.context, default=str),
                    record.outcome,
                    record.quality_score,
                    record.recorded_at.isoformat(),
                ),
            )


# ---------------------------------------------------------------------------
# Neon Postgres backend (production — schema provisioned via Neon MCP)
# ---------------------------------------------------------------------------


class NeonMemoryStore(MemoryStore):
    """
    PostgreSQL-backed memory via Neon serverless Postgres.

    Schema tables (created via Neon MCP run_sql_transaction):
      - agents, working_memory, episodic_memory
    """

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or DATABASE_URL
        if not self._database_url:
            raise ValueError(
                "DATABASE_URL must be set to use NeonMemoryStore. "
                "Provision via Neon MCP: project 'forge-resonance' (late-glade-09092928)."
            )

    def _get_connection(self):
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError as exc:
            raise ImportError(
                "psycopg2-binary is required for Neon backend. "
                "Install via: pip install psycopg2-binary"
            ) from exc
        return psycopg2.connect(self._database_url)

    def load(self, agent_name: str) -> AgentMemory:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, goals, metadata FROM agents WHERE name = %s", (agent_name,))
                row = cur.fetchone()
                if row is None:
                    agent_id = str(uuid.uuid4())
                    cur.execute(
                        "INSERT INTO agents (id, name) VALUES (%s::uuid, %s) RETURNING id",
                        (agent_id, agent_name),
                    )
                    conn.commit()
                    return AgentMemory(agent_id=agent_id, agent_name=agent_name)

                agent_id = str(row[0])
                goals = row[1] if isinstance(row[1], list) else json.loads(row[1] or "[]")
                metadata = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")

                cur.execute(
                    """
                    SELECT memory_key, memory_value, expires_at
                    FROM working_memory WHERE agent_id = %s::uuid
                    """,
                    (agent_id,),
                )
                working_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT resonance_id, context, outcome, quality_score, recorded_at
                    FROM episodic_memory
                    WHERE agent_id = %s::uuid
                    ORDER BY recorded_at DESC LIMIT %s
                    """,
                    (agent_id, EPISODIC_MEMORY_LIMIT),
                )
                episodic_rows = cur.fetchall()

        working: dict[str, MemoryEntry] = {}
        for wr in working_rows:
            entry = MemoryEntry(
                key=wr[0],
                value=wr[1] if isinstance(wr[1], (dict, list)) else json.loads(wr[1]),
                expires_at=wr[2],
            )
            if not entry.is_expired():
                working[entry.key] = entry

        episodic = [
            EpisodicRecord(
                resonance_id=er[0],
                context=er[1] if isinstance(er[1], dict) else json.loads(er[1]),
                outcome=er[2],
                quality_score=float(er[3]) if er[3] is not None else None,
                recorded_at=er[4] if isinstance(er[4], datetime) else er[4],
            )
            for er in reversed(episodic_rows)
        ]

        return AgentMemory(
            agent_id=agent_id,
            agent_name=agent_name,
            working=working,
            episodic=episodic,
            goals=goals,
            metadata=metadata,
        )

    def save(self, memory: AgentMemory) -> None:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agents (id, name, goals, metadata, updated_at)
                    VALUES (%s::uuid, %s, %s::jsonb, %s::jsonb, NOW())
                    ON CONFLICT (name) DO UPDATE SET
                        goals = EXCLUDED.goals,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """,
                    (
                        memory.agent_id,
                        memory.agent_name,
                        json.dumps(memory.goals),
                        json.dumps(memory.metadata),
                    ),
                )
            conn.commit()
        logger.debug("Saved Neon memory for agent '%s'", memory.agent_name)

    def set_working(
        self,
        memory: AgentMemory,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds or WORKING_MEMORY_TTL_SECONDS
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        memory.working[key] = MemoryEntry(key=key, value=value, expires_at=expires_at)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO working_memory (agent_id, memory_key, memory_value, expires_at)
                    VALUES (%s::uuid, %s, %s::jsonb, %s)
                    ON CONFLICT (agent_id, memory_key) DO UPDATE SET
                        memory_value = EXCLUDED.memory_value,
                        expires_at = EXCLUDED.expires_at
                    """,
                    (
                        memory.agent_id,
                        key,
                        json.dumps(value, default=str),
                        expires_at,
                    ),
                )
            conn.commit()

    def record_episode(self, memory: AgentMemory, record: EpisodicRecord) -> None:
        memory.episodic.append(record)
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO episodic_memory
                        (agent_id, resonance_id, context, outcome, quality_score)
                    VALUES (%s::uuid, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        memory.agent_id,
                        record.resonance_id,
                        json.dumps(record.context, default=str),
                        record.outcome,
                        record.quality_score,
                    ),
                )
            conn.commit()


# ---------------------------------------------------------------------------
# Hybrid store — local sovereignty + Neon sync
# ---------------------------------------------------------------------------


class HybridMemoryStore(MemoryStore):
    """
    Writes to file store always; syncs to Neon when DATABASE_URL is set.

    Agents remain functional offline. Neon receives episodic records for
    fabric-wide reputation aggregation.
    """

    def __init__(self) -> None:
        self._local = FileMemoryStore()
        self._remote: NeonMemoryStore | None = None
        if neon_is_reachable():
            try:
                self._remote = NeonMemoryStore()
                logger.info("Hybrid memory: Neon sync enabled")
            except (ValueError, ImportError) as exc:
                logger.warning("Neon sync unavailable: %s", exc)
        elif DATABASE_URL:
            logger.info("Hybrid memory: Neon configured but unreachable; local only")

    def load(self, agent_name: str) -> AgentMemory:
        memory = self._local.load(agent_name)
        if self._remote:
            try:
                remote = self._remote.load(agent_name)
                memory.agent_id = remote.agent_id
                if len(remote.episodic) > len(memory.episodic):
                    memory.episodic = remote.episodic
            except Exception as exc:
                logger.warning("Neon load fallback to local: %s", exc)
        return memory

    def save(self, memory: AgentMemory) -> None:
        self._local.save(memory)
        if self._remote:
            try:
                self._remote.save(memory)
            except Exception as exc:
                logger.warning("Neon save deferred: %s", exc)

    def set_working(
        self,
        memory: AgentMemory,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        self._local.set_working(memory, key, value, ttl_seconds)
        if self._remote:
            try:
                self._remote.set_working(memory, key, value, ttl_seconds)
            except Exception as exc:
                logger.warning("Neon working memory sync failed: %s", exc)

    def record_episode(self, memory: AgentMemory, record: EpisodicRecord) -> None:
        self._local.record_episode(memory, record)
        if self._remote:
            try:
                self._remote.record_episode(memory, record)
            except Exception as exc:
                logger.warning("Neon episodic sync failed: %s", exc)


def neon_is_reachable(database_url: str | None = None) -> bool:
    """Test whether Neon Postgres is reachable; used for graceful fallback."""
    url = database_url or DATABASE_URL
    if not url:
        return False
    try:
        import psycopg2

        conn = psycopg2.connect(url, connect_timeout=5)
        conn.close()
        return True
    except Exception as exc:
        logger.warning("Neon unreachable, using local fallback: %s", exc)
        return False


def create_memory_store(backend: str | None = None) -> MemoryStore:
    """Factory for memory backends based on config or explicit override."""
    cfg = load_config()
    backend = backend or cfg.storage_backend

    if backend == "file":
        return FileMemoryStore()
    if backend == "sqlite":
        return SQLiteMemoryStore()
    if backend == "neon":
        if neon_is_reachable():
            try:
                return NeonMemoryStore()
            except (ValueError, ImportError) as exc:
                logger.warning("Neon store unavailable: %s", exc)
        logger.info("Falling back to SQLiteMemoryStore")
        return SQLiteMemoryStore()
    if backend == "hybrid":
        return HybridMemoryStore()
    return HybridMemoryStore()