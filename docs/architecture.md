# ForgeResonance Architecture

## Overview

ForgeResonance is a decentralized fabric of sovereign AI agents that earn distribution through demonstrated resonance success. The system replaces paid advertising with a utility-driven, reputation-weighted coordination layer.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     ForgeResonance Fabric                           │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  Agent A     │  │  Agent B     │  │  Agent C     │  ...         │
│  │  (sovereign) │  │  (sovereign) │  │  (sovereign) │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                 │                 │                       │
│         └─────────────────┼─────────────────┘                       │
│                           │                                         │
│              ┌────────────▼────────────┐                            │
│              │   Reputation Layer      │                            │
│              │   (Resonance Score)     │                            │
│              └────────────┬────────────┘                            │
│                           │                                         │
│              ┌────────────▼────────────┐                            │
│              │   Neon Postgres         │                            │
│              │   (shared ledger)       │                            │
│              └─────────────────────────┘                            │
└─────────────────────────────────────────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │   Arcly AI Closer       │
              │   (conversion layer)    │
              └─────────────────────────┘
```

## Layer Architecture

### 1. Sovereign Resonance Agents (`core/resonance_agent.py`)

The foundational primitive. Each agent:

- Maintains persistent memory (working + episodic)
- Owns sovereign goals and offer catalog
- Runs an autonomous lifecycle loop
- Accumulates a Resonance Score through outcomes

**Lifecycle phases:** `initializing → idle → sensing → resonating → injecting → handoff → reflecting → idle`

### 2. Intent Signal Harvesting (`harvesting/`)

Privacy-preserving local intent detection:

- Opt-in gate before any harvesting
- Local embedding processing
- Anonymized `IntentSignal` with SHA-256 hash
- Firecrawl hook for opt-in web enrichment (future)

**Privacy boundary:** Raw signals never cross the local processing boundary.

### 3. Resonance Matching & Generation (`generation/`)

Grok-native engine that:

- Matches intent to agent offers
- Weights matching by Resonance Score (visibility)
- Generates contextual value payloads via xAI API
- Estimates quality for score adjustment

### 4. Contextual Value Injection (`injection/`)

Delivers generated value into the user's active context:

- Channel selection based on signal confidence
- Preemptive utility delivery (not interruption)
- Outcome reporting for score engine

### 5. Reputation / Resonance Score (`reputation/`, `core/scoring.py`)

The Fabric's reputation primitive:

- Score range: 0–100 (default: 50)
- Outcome-tier deltas: success (+2.5), partial (+0.5), failure (−1.5), rejection (−3.0)
- Quality multiplier on positive deltas
- Full audit trail in `reputation_ledger`
- Visibility multiplier for matching prioritization

**Future:** Cloudflare KV edge cache for sub-millisecond reputation lookups.

### 6. Arcly Integration (`integration/`)

Clean handoff contract:

```
ResonanceAgent → ValueInjector → ArclyHandoff → Arcly AI Closer
                                                      │
                                              conversion outcome
                                                      │
                                              ResonanceScorer ←──┘
```

### 7. Memory Subsystem (`core/memory.py`)

Three-tier storage:

| Tier | Backend | Purpose |
|------|---------|---------|
| Working | In-process + file/DB | Short-lived context (TTL) |
| Episodic | File/SQLite/Neon | Long-term resonance history |
| Hybrid | File + Neon sync | Offline sovereignty + Fabric scale |

**Neon schema** (provisioned via Neon MCP):

- `agents` — identity, score, goals
- `working_memory` — keyed short-term store
- `episodic_memory` — resonance history
- `resonance_events` — event stream
- `reputation_ledger` — score audit trail

### 8. Observability (`utils/logging.py`)

- Structured JSON logging
- Sentry error capture (when `SENTRY_DSN` set)
- Axiom event emission (when `AXIOM_TOKEN` set)
- Cloudflare Logpush compatible format

## Data Flow

```
1. Agent loop starts (idle)
2. Harvester senses local intent → IntentSignal (or None → skip)
3. Engine generates ResonancePayload weighted by score
4. Injector delivers value → outcome tier
5. Handoff sends qualified resonances to Arcly
6. Scorer applies outcome delta → updates ledger
7. Episodic memory records the cycle
8. Agent returns to idle
```

## Deployment Topology

### Development (current)

```
Local Python process
  ├── File memory (data/agents/)
  ├── SQLite (data/forge_resonance.db)
  └── Neon sync (when DATABASE_URL set)
```

### Production (planned)

```
Vercel Serverless Functions
  ├── /api/agents — agent management API
  ├── /api/resonance — resonance event ingestion
  └── /api/health — Fabric health check

Cloudflare Workers (edge)
  ├── Reputation KV cache
  ├── Intent preprocessing (privacy boundary)
  └── Agent lightweight runners

Neon Postgres
  └── Authoritative memory + reputation store
```

## MCP Integration Map

| MCP Server | Role in Architecture |
|------------|---------------------|
| **grok_com_github** | Source control, CI/CD foundation |
| **neon** | Production Postgres (project: `forge-resonance`) |
| **grok_com_vercel** | Serverless API deployment |
| **Cloudflare plugins** | Edge reputation, Workers, observability |
| **grok_com_linear** | Engineering task tracking |
| **grok_com_notion** | Project documentation hub |
| **firecrawl** | Opt-in intent enrichment (M2) |
| **sentry** | Error monitoring |
| **axiom** | Telemetry and alerting |
| **mongodb** | Alternative document store (if needed) |

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

## Security Model

- No central intent database
- DATABASE_URL and API keys via environment only
- Agent data isolated by name/ID
- Reputation ledger is append-only
- Arcly handoff uses Bearer token auth