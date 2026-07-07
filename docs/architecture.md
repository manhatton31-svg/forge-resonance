# ForgeResonance Architecture

## Overview

ForgeResonance is a decentralized fabric of sovereign AI agents that earn distribution through demonstrated resonance success. The system replaces paid advertising with a utility-driven, reputation-weighted coordination layer.

**Core loop per agent:**

```
Harvest → Generate → Inject → Handoff → Reflect → (idle)
```

**Fabric-level view:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                     ForgeResonance Fabric                           │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  Agent A     │  │  Agent B     │  │  Agent C     │  ...         │
│  │  (sovereign) │  │  (sovereign) │  │  (sovereign) │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         └─────────────────┼─────────────────┘                       │
│                           ▼                                         │
│              ┌────────────────────────┐                             │
│              │   Reputation Layer     │                             │
│              │   (Resonance Score)    │                             │
│              └────────────┬───────────┘                             │
│                           ▼                                         │
│              ┌────────────────────────┐                             │
│              │   Neon Postgres        │  optional                   │
│              └────────────────────────┘                             │
└───────────────────────────┬─────────────────────────────────────────┘
                            ▼
              ┌────────────────────────┐
              │   Arcly AI Closer      │
              └────────────────────────┘
```

## Key Concepts

| Term | Definition |
|------|------------|
| **Resonance** | One full cycle from intent detection through value delivery and score reflection |
| **Resonance Score** | 0–100 reputation metric; default 50; updated per outcome tier |
| **Visibility Multiplier** | Score → routing weight mapping (0.1–2.0); used in multi-agent selection |
| **Selection Weight** | `visibility × (score/100)` — ranking metric for swarm routing |
| **ResonancePayload** | Structured value unit: summary, action, value prop, type, quality |
| **OfferFramer** | Tags commercial intents with offer-ready metadata for Arcly |
| **IntentSignal** | Privacy-preserving harvested intent (hashed context, confidence, type) |

See [principles.md](principles.md) for design rationale.

---

## Layer Architecture

### 1. Sovereign Resonance Agents (`core/resonance_agent.py`)

The foundational primitive. Each agent:

- Maintains persistent memory (working + episodic)
- Owns sovereign goals and offer catalog
- Runs an autonomous lifecycle loop
- Accumulates a Resonance Score through outcomes

**Lifecycle phases:** `initializing → idle → sensing → resonating → injecting → handoff → reflecting → idle`

### 2. Intent Signal Harvesting (`harvesting/`)

Privacy-preserving local intent detection via `EmbeddingIntentHarvester`:

```
External source                Harvester                     Agent loop
───────────────               ─────────────                 ──────────
ingest_text()        ──►  detect_intent()  ──►  queue signal  ──►  harvest()
ingest_from_chat()   ──►  keyword+embedding match              should_resonate()
ingest_from_webhook()──►  multi-turn context boost             run_once()
       │                      │
       └── URL in text ──► FirecrawlEnricher (opt-in)
```

**Intent patterns:** purchase, research, comparison, problem_solving, support, evaluation.

**Confidence scoring:** keyword hits (45%) + embedding similarity (55%) + multi-turn boost + Firecrawl bonus. Signals below `INTENT_RESONANCE_THRESHOLD` are skipped.

**Privacy boundary:** Raw text is hashed locally; only `IntentSignal` context vectors propagate downstream.

### 3. Resonance Matching & Generation (`generation/`)

`ResonanceEngine` transforms `IntentSignal` + agent context into a `ResonancePayload`.

```
IntentSignal + AgentMemory + Resonance Score
        │
        ▼
  Build GenerationContext
        │
        ├── XAI_API_KEY set? ──► Grok ──► parse JSON ──► ResonancePayload
        └── no key / failure   ──► context-aware template fallback
```

**Resonance types:** `educational`, `comparative`, `solution_oriented`, `offer_framed`

**Quality estimation:** Blends intent confidence (35%), score (25%), episodic momentum (25%), intent-type fit (15%).

### 4. Contextual Value Injection (`injection/`)

`ValueInjector` delivers `ResonancePayload` via configurable modes:

| Mode | Output |
|------|--------|
| `echo` | Raw stdout (dev) |
| `formatted_message` | Human-readable markdown (default) |
| `structured_card` | JSON card for chat widgets |
| `offer_ready` | Conversion package with CTA and offer URL |

When `prepare_handoff=True`, attaches `handoff_package` to payload content for Arcly.

**Outcome tiers:** quality ≥ 0.7 → success; ≥ 0.4 → partial; else failure.

### 5. Reputation / Resonance Score (`reputation/`, `core/scoring.py`)

`ResonanceScoreManager` (`reputation/score_layer.py`) records outcomes and drives the distribution flywheel.

```
Reflect step → record_outcome() → ResonanceScorer + OutcomeHistoryStore
```

**Visibility multiplier** (`get_visibility_multiplier(score)`):

- Maps score [0, 100] → multiplier [0.1, 2.0]
- Score 50 → visibility ≈ 1.05

**Multi-agent ranking:** `ReputationLayer.rank_agents()` sorts by `selection_weight` with tie-breakers on visibility, score, and success rate.

**Persistence:** Neon Postgres (when `DATABASE_URL` set) → SQLite fallback → in-memory for tests.

#### Edge Reputation (Cloudflare KV — M4)

Hybrid replication for low-latency Fabric routing at the edge:

```
record_outcome() → Neon/SQLite (source of truth)
        │
        └── EDGE_REPUTATION_ENABLED → CloudflareKVClient.sync_score()
                    │
                    └── KV key: reputation:{agent_id}
                        { score, visibility_multiplier, synced_at, metadata }
```

| Layer | Role |
|-------|------|
| Neon / SQLite | Authoritative scores, ledger, outcome history |
| Cloudflare KV | Fast edge cache for `rank_agents()` and swarm routers |
| `resolve_score()` | Local score when warm; KV fallback when local is cold |
| `resolve_ranking_metrics()` | Active read path for ranking and selection weight |

**Edge-aware ranking** (`ReputationLayer.rank_agents(use_edge_data=True)`):

```
EDGE_READ_PREFERENCE=edge_first (default)
        │
        ├── KV record exists + local warm → blended score/visibility/weight
        ├── KV only (local cold)        → edge metrics (edge_fallback)
        └── KV missing / unreachable    → local metrics (graceful degrade)
```

Selection weight blends local and edge weights when both sources exist:
`(local_visibility × local_score/100 + edge_visibility × edge_score/100) / 2`.

Observability: `sync_status(agent_ids)` reports KV reachability, last sync times,
and score drift between local and edge. `fabric_health()` includes aggregate drift.

Enable with `EDGE_REPUTATION_ENABLED=true` plus `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and `CLOUDFLARE_KV_NAMESPACE`. Sync failures are logged and never block local persistence.

Implementation: `reputation/edge_kv.py` (`CloudflareKVClient`).

#### Swarm Routing & Execution (M4)

Multi-agent intent assignment and execution using reputation + capability:

```
IntentSignal → IntentRouter.route()
        │
        ├── AgentRegistry.list_available()
        ├── ReputationLayer.rank_agents(use_edge_data=True)
        ├── capability match (intent label vs goals/specialties)
        └── combined_score = reputation × 0.6 + capability × 0.4 (load-adjusted)

SwarmCoordinator.dispatch()          # routing + optional submit (no run_once)
        ├── BEST_SINGLE      → top-1 agent
        └── BROADCAST_TOP_N  → top N agents (default 3)

SwarmCoordinator.execute()           # route → process_intent → aggregate
        ├── bind_agent() / bind_agents() — live ResonanceAgent instances
        ├── parallel execution (ThreadPoolExecutor, SWARM_MAX_PARALLEL)
        ├── per-agent timeout (SWARM_AGENT_TIMEOUT, overridable per call)
        ├── agent.process_intent(signal) — standardized swarm entry point
        ├── AgentExecutionResult per participant (outcome, quality, failure_kind)
        ├── SwarmResult — best result, consensus, metrics, timing metadata
        └── reputation feedback (automatic via run_once; manual on failure/timeout)
```

**Execution modes**

| Strategy | Behavior |
|----------|----------|
| `BEST_SINGLE` | Route to top-1 agent, run one resonance cycle, pick best by composite rank |
| `BROADCAST_TOP_N` | Fan out to top N agents (parallel), aggregate quality and consensus |

**Consensus strategies** (`SWARM_CONSENSUS_STRATEGY`)

| Strategy | Behavior |
|----------|----------|
| `majority` | Simple vote count across agent outcomes |
| `quality_weighted` | Weight votes by `quality × routing.combined_score` (default) |

**Reliability**

- Per-agent timeouts isolate slow agents; other agents continue unaffected
- Exceptions and unbound agents return `AgentExecutionResult` with `failure_kind` (`timeout`, `exception`, `unbound`)
- `best_result` is only set from successful agents — partial swarm failure is safe

**Observability**

Structured log events: `swarm_execute_start`, `swarm_agent_result`, `swarm_execute_complete`, `swarm_reputation_failure`. Axiom events emitted when `AXIOM_TOKEN` is set.

`SwarmExecutionMetrics` on every `SwarmResult`:

- `total_duration_ms`, `success_rate`, `average_quality`
- `failure_count`, `timeout_count`, `exception_count`, `unbound_count`

**Configuration** (`.env`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SWARM_AGENT_TIMEOUT` | `120` | Per-agent cycle timeout (seconds; `0` = disabled) |
| `SWARM_MAX_PARALLEL` | `3` | Max concurrent agents in broadcast mode |
| `SWARM_CONSENSUS_STRATEGY` | `quality_weighted` | Broadcast consensus algorithm |

**Result types**

- `AgentExecutionResult` — per-agent outcome, formatted message, `failure_kind`, duration
- `SwarmResult` — dispatch, best/consensus, `started_at`/`completed_at`, `metrics`

Unbound agents, timeouts, and exceptions record `OutcomeTier.FAILURE` without double-counting successful `run_once()` paths. Optional `apply_swarm_bonus` nudges reputation when swarm-level quality is very high or low.

| Module | Role |
|--------|------|
| `agents/registry.py` | Agent directory (goals, specialties, load) |
| `fabric/router.py` | Intent → agent routing |
| `fabric/swarm.py` | Swarm dispatch, execution, aggregation |
| `fabric/capabilities.py` | Intent label → specialty matching |

Demo: `python -m demo --swarm-only`

**Serverless deployment:** Vercel hosts `/api/health`, `/api/fabric_health`, `/api/arcly_feedback`, and `/api/swarm`. Edge KV uses the REST API (no Workers binding). Swarm `mode=route` is serverless-safe; full agent cycles belong on Workers or local runtime. See [deployment.md](deployment.md).

### 6. Demo & Bootstrap Layer (`demo/`)

Interactive showcase without API keys:

```bash
python -m demo              # single + multi-agent
python -m demo --multi-only # ranking only
python -m demo --help       # phase documentation
```

| Phase | Demonstrates |
|-------|--------------|
| Single agent | Harvest → Generate → Inject → Handoff → Reflect |
| Multi-agent | Shared score manager, divergent outcomes, `rank_agents()` |

### 7. Arcly Integration (`integration/`)

```
ResonanceAgent → ValueInjector → OfferFramer → ArclyHandoff → Arcly AI Closer
                     │                              │
              handoff_package              agent_stats + offer_bundle
                                                    │
                              report_outcome() ←────┘
```

**Handoff modes** (`ARCLY_MODE`):

| Mode | Behavior |
|------|----------|
| `auto` | Live when key + non-local URL |
| `dry_run` | Simulated acceptance (demo default) |
| `live` | POST with Bearer auth, retries |

**OfferFramer:** Commercial intents get `offer_id`, `offer_url`, `cta_text`, `value_prop` in payload and handoff.

**Feedback:** `report_outcome()` and `POST /api/arcly_feedback` update score when `ARCLY_FEEDBACK_ENABLED=true`.

### 8. Memory Subsystem (`core/memory.py`)

| Tier | Backend | Purpose |
|------|---------|---------|
| Working | In-process + file/DB | Short-lived context (TTL) |
| Episodic | File/SQLite/Neon | Long-term resonance history |
| Hybrid | File + Neon sync | Offline sovereignty + Fabric scale |

### 9. Observability (`utils/logging.py`)

- Structured JSON logging (`LOG_LEVEL`)
- Sentry (when `SENTRY_DSN` set)
- Axiom events (when `AXIOM_TOKEN` set)

---

## Data Flow

```
1. Agent loop starts (idle)
2. Harvester senses intent → IntentSignal (or None → skip)
3. Engine generates ResonancePayload weighted by score
4. Injector delivers value → outcome tier
5. Handoff sends qualified resonances to Arcly
6. Scorer applies outcome delta → updates ledger
7. Episodic memory records the cycle
8. Agent returns to idle
```

---

## Deployment Topology

### Development (current)

```
Local Python process
  ├── File memory (data/agents/)
  ├── SQLite (data/forge_resonance.db)
  └── Neon sync (when DATABASE_URL set)
```

### Production (planned — M4/M5)

```
Vercel Serverless Functions
  ├── /api/agents
  ├── /api/resonance
  ├── /api/arcly_feedback
  └── /api/health

Cloudflare Workers (edge)
  ├── Reputation KV cache
  ├── Intent preprocessing
  └── Lightweight agent runners

Neon Postgres
  └── Authoritative memory + reputation store
```

---

## Extension Points

All layer boundaries use protocol/ABC interfaces:

```python
IntentHarvesterProtocol  → harvesting/intent_harvester.py
ResonanceEngineProtocol  → generation/resonance_engine.py
ValueInjectorProtocol    → injection/value_injector.py
ArclyHandoffProtocol     → integration/arcly_handoff.py
MemoryStore              → core/memory.py
ScoreStore               → core/scoring.py
```

Custom agents in `agents/` compose these interfaces without modifying core modules.

---

## Security Model

- No central intent database
- Secrets via environment only
- Agent data isolated by name/ID
- Reputation ledger is append-only
- Arcly handoff uses Bearer token auth

---

## Related Docs

- [getting-started.md](getting-started.md) — run the demo in < 2 minutes
- [principles.md](principles.md) — design constraints
- [roadmap.md](roadmap.md) — milestone status