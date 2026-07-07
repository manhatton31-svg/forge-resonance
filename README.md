# ForgeResonance

**A self-organizing fabric of sovereign AI agents that earn distribution through demonstrated resonance success.**

ForgeResonance replaces paid advertising with a utility-driven, reputation-weighted system. Agents sense intent privately, deliver hyper-contextual value at the moment it matters, accumulate a **Resonance Score** that governs Fabric visibility, and hand qualified opportunities to **Arcly AI Closer** for conversion.

---

## Why ForgeResonance Exists

Paid advertising optimizes for impressions and spend. It centralizes intent data, interrupts users, and rewards budget — not demonstrated value. There is no primitive for autonomous agents to **earn distribution** by proving they deliver timely, contextual utility.

ForgeResonance introduces that primitive:

| Advertising model | ForgeResonance model |
|-------------------|----------------------|
| Impressions & clicks | Resonance quality & outcomes |
| Central ad auction | Reputation-weighted agent matching |
| Spend for visibility | Earn visibility through success |
| Interruptive placement | Contextual value injection |

---

## Quick Start (< 2 minutes)

No API keys required. The demo uses template generation and in-memory reputation.

```bash
git clone https://github.com/manhatton31-svg/forge-resonance.git
cd forge-resonance
pip install -r requirements.txt
python -m demo
```

You should see:

1. **Single-agent phase** — `atlas-demo` runs four intents (purchase, comparison, research, support). Each cycle shows outcome, score delta, and a resonant value summary.
2. **Multi-agent phase** — Three agents compete on overlapping intents. A ranking table shows selection weight (visibility × score).

```bash
python -m demo --help    # explain each demo phase and flag
python -m demo --single-only
python -m demo --multi-only
python -m demo --swarm-only  # intent routing across agent swarm
python -m demo --verbose # full formatted messages per cycle
```

Run tests:

```bash
python -m pytest tests/ -v
```

---

## Getting Started

See [docs/getting-started.md](docs/getting-started.md) for a step-by-step guide with expected output, template mode, and optional upgrades (Grok, Neon, Arcly).

**Template mode (zero keys):**

```bash
cp .env.example .env   # defaults work for local demo
python -m demo
```

**Start a single agent programmatically:**

```python
from core.resonance_agent import ResonanceAgent

agent = ResonanceAgent("my-agent", goals=["deliver contextual value"])
agent.start()
agent.submit_intent("I want to buy analytics software and need enterprise pricing")
print(agent.run_once())  # success | partial | failure | skipped
print(agent.get_reputation_stats())
```

---

## Architecture Overview

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
│              │   Neon Postgres        │  (optional)                 │
│              └────────────────────────┘                             │
└───────────────────────────┬─────────────────────────────────────────┘
                            ▼
              ┌────────────────────────┐
              │   Arcly AI Closer      │
              │   (conversion layer)   │
              └────────────────────────┘
```

**Per-agent pipeline:**

```
Harvest → Generate → Inject → Handoff → Reflect
   ↑                                        |
   └──────── Resonance Score update ────────┘
```

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Core | `core/` | Agent lifecycle, memory, state |
| Harvesting | `harvesting/` | Privacy-preserving intent detection |
| Generation | `generation/` | Grok-native resonance payloads |
| Injection | `injection/` | Contextual value delivery |
| Reputation | `reputation/` | Score, visibility, multi-agent ranking |
| Integration | `integration/` | Arcly handoff, offer framing |
| Demo | `demo/` | End-to-end showcase without API keys |

Full design: [docs/architecture.md](docs/architecture.md)

---

## Key Concepts

### Resonance

A **resonance** is one complete cycle: sense intent → generate contextual value → inject it → optionally hand off to Arcly → reflect on outcome. Successful resonances increase an agent's score; poor ones decrease it.

### Resonance Score

A 0–100 reputation primitive (default 50). Updated after every cycle based on outcome tier and quality:

- Success (+2.5), partial (+0.5), failure (−1.5), rejection (−3.0)
- Full audit trail in `reputation_ledger`

### Visibility Multiplier

Maps score to Fabric routing weight: **0.1 (low trust) → 2.0 (high trust)**. At score 50, visibility ≈ 1.05. Used by `rank_agents()` to prefer agents that consistently deliver value.

### Offer Framing

`OfferFramer` (`integration/offer_framer.py`) tags commercial intents (`purchase_intent`, `evaluation_intent`) as `offer_ready`, embedding `offer_id`, `offer_url`, `cta_text`, and `value_prop` into the payload and Arcly handoff package.

### Selection Weight

`visibility_multiplier × (score / 100)` — the metric multi-agent ranking uses. Higher weight → more likely to receive the next intent in a swarm.

---

## Arcly Integration

ForgeResonance senses intent and delivers value. **Arcly** closes the loop (email follow-up, offer presentation, conversion tracking).

```
ResonanceAgent → ValueInjector → OfferFramer → ArclyHandoff → Arcly AI Closer
                     │                              │
              handoff_package              reputation + offer_bundle
                                                    │
                              report_outcome() ←────┘
```

**Modes** (`ARCLY_MODE`):

| Mode | When to use |
|------|-------------|
| `auto` (default) | Live when `ARCLY_API_KEY` + non-local `ARCLY_API_URL` |
| `dry_run` | Local dev, demos — simulated acceptance |
| `live` | Force production POST with retries |

**Two-way feedback:** Arcly reports outcomes via `report_outcome()` or `POST /api/arcly_feedback`, updating Resonance Score when `ARCLY_FEEDBACK_ENABLED=true`.

---

## Configuration

Copy `.env.example` to `.env`. Only `DATABASE_URL` and API keys are needed for production features.

### Essential variables

| Variable | Purpose | Demo default |
|----------|---------|--------------|
| `XAI_API_KEY` | Grok generation | Empty → template fallback |
| `DATABASE_URL` | Neon Postgres sync | Optional |
| `ARCLY_API_URL` | Arcly endpoint | `http://localhost:8000` |
| `ARCLY_API_KEY` | Arcly auth | Empty → dry_run |
| `ARCLY_MODE` | Handoff behavior | `auto` |
| `LOG_LEVEL` | Logging verbosity | `INFO` (demo sets `WARNING`) |

### Neon (optional persistence)

Schema on project `forge-resonance`:

- `agents`, `working_memory`, `episodic_memory`, `resonance_events`, `reputation_ledger`

Set `DATABASE_URL` and `FORGE_STORAGE_BACKEND=hybrid` to sync local agents with Neon.

### Arcly (conversion handoff)

```bash
ARCLY_API_URL=https://your-arcly-instance.example.com
ARCLY_API_KEY=your-secret-key
ARCLY_MODE=live
ARCLY_FEEDBACK_ENABLED=true
```

### Edge Reputation (Cloudflare KV — optional, M4)

Replicate scores and visibility multipliers to Cloudflare KV for fast edge lookups. Neon/SQLite remain the source of truth.

```bash
EDGE_REPUTATION_ENABLED=true
CLOUDFLARE_API_TOKEN=your-api-token
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_KV_NAMESPACE=your-kv-namespace-id
```

Scores sync automatically after each `record_outcome()`. When enabled, `rank_agents()` reads KV data for ranking (default `EDGE_READ_PREFERENCE=edge_first`) and blends local + edge selection weights when both are available. KV unreachable → graceful fallback to local.

See [.env.example](.env.example) for all variables with inline comments.

---

## Demo Options

| Command | What it shows |
|---------|---------------|
| `python -m demo` | Full showcase: single agent + multi-agent ranking |
| `python -m demo --single-only` | One agent, four intent cycles, reputation stats |
| `python -m demo --multi-only` | Three agents, divergent scores, ranking table |
| `python -m demo --swarm-only` | Swarm execute: route, run agents, aggregate outcomes |
| `python -m demo --verbose` | Full formatted resonant messages per cycle |
| `python -m demo --data-dir ./tmp` | Custom demo data directory |

**Single-agent phase** demonstrates: intent harvesting → template/Grok generation → value injection → Arcly dry-run handoff → score reflection.

**Multi-agent phase** demonstrates: shared `ResonanceScoreManager`, `rank_agents()` by selection weight, swarm routing primitive.

**Swarm execution** (`--swarm-only`) demonstrates: `AgentRegistry`, `IntentRouter`, and `SwarmCoordinator.execute()` routing purchase/research/support intents, running resonance cycles on bound agents, and aggregating `SwarmResult` outcomes with reputation feedback.

### Swarm execution example

```python
from core.resonance_agent import IntentSignal
from fabric.swarm import ConsensusStrategy, SwarmCoordinator, SwarmStrategy

signal = IntentSignal.from_context(
    {"matched_intent": "purchase_intent", "text": "I want analytics pricing"},
    confidence=0.85,
)

swarm = SwarmCoordinator(registry, reputation_layer)
swarm.bind_agents([atlas_agent, nova_agent, echo_agent])

# Best single agent runs one cycle (120s default timeout from SWARM_AGENT_TIMEOUT)
result = swarm.execute(signal, strategy=SwarmStrategy.BEST_SINGLE)
if result.best_result:
    print(result.best_result.agent_name, result.swarm_quality)
else:
    print("All agents failed:", result.metrics.failure_count)

# Broadcast to top 3 with quality-weighted consensus
broadcast = swarm.execute(
    signal,
    strategy=SwarmStrategy.BROADCAST_TOP_N,
    top_n=3,
    consensus_strategy=ConsensusStrategy.QUALITY_WEIGHTED,
)
print(broadcast.consensus_outcome, broadcast.metrics.success_rate)

# Inspect per-agent failures without crashing the swarm
for agent_result in broadcast.agent_results:
    if agent_result.failure_kind:
        print(agent_result.agent_name, agent_result.failure_kind, agent_result.error)
```

**Swarm env vars:** `SWARM_AGENT_TIMEOUT`, `SWARM_MAX_PARALLEL`, `SWARM_CONSENSUS_STRATEGY` — see `.env.example`.

---

## Project Structure

```
forge-resonance/
├── core/               # Agent runtime, memory, scoring, state
├── harvesting/         # Privacy-preserving intent signals
├── generation/         # Grok-native resonance engine
├── injection/          # Contextual value delivery
├── reputation/         # Resonance Score + multi-agent ranking
├── integration/        # Arcly handoff + OfferFramer
├── demo/               # Interactive demo (`python -m demo`)
├── api/                # Vercel serverless endpoints
├── docs/               # Architecture, principles, roadmap
├── tests/              # Test suite (~110 tests)
└── config.py           # Environment-driven configuration
```

---

## Development Roadmap

| Milestone | Status | Highlights |
|-----------|--------|------------|
| **M1** Foundation | Complete | Agent lifecycle, memory backends, scoring, Arcly contract |
| **M2** Intent Harvesting | Complete | Embedding harvester, multi-turn context, Firecrawl hook |
| **M3** Resonance Engine | Complete | Grok prompts, template fallback, quality estimation |
| **M4** Fabric & Edge | In Progress | KV edge reputation (initial), Workers, swarm routing |
| **M5** Production Launch | Planned | Operator dashboard, full observability pipeline |

Details: [docs/roadmap.md](docs/roadmap.md)

**Immediate next steps:**

- Edge-deployed agent runners on Cloudflare Workers
- KV-backed reputation snapshots with Neon sync
- Fabric-wide weighted routing at swarm scale

---

## Principles

1. **Sovereignty First** — Agents own memory and goals
2. **Privacy by Design** — Local intent processing, opt-in only
3. **Resonance Over Advertising** — Outcomes drive visibility
4. **Positive-Sum Flywheel** — Success breeds opportunity
5. **Arcly Integration** — Clean conversion handoff
6. **Grok-Native** — Optimized for xAI models
7. **Modularity** — Protocol interfaces at every layer
8. **Production Mindset** — Typed, tested, observable

See [docs/principles.md](docs/principles.md).

---

## Deployment

### Vercel (API layer)

```bash
npm i -g vercel
vercel link
vercel --prod
```

**Endpoints:** `/api/health`, `/api/fabric_health`, `/api/arcly_feedback`, `/api/swarm`

Set secrets in the Vercel dashboard (never commit): `DATABASE_URL`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_KV_NAMESPACE`, `ARCLY_API_KEY`, optional `FORGE_API_KEY`.

```bash
# Quick health check after deploy
curl https://<your-app>.vercel.app/api/health?deep=1
```

Full guide: [docs/deployment.md](docs/deployment.md) — env vars, KV setup, serverless swarm limits, troubleshooting.

**Local dev:** `pip install -r requirements-dev.txt` (tests) · `pip install -r requirements.txt` (Vercel parity)

**Cloudflare Workers (planned):** Long-running edge agents — see [docs/architecture.md](docs/architecture.md).

---

## Links

| Resource | URL |
|----------|-----|
| Repository | [github.com/manhatton31-svg/forge-resonance](https://github.com/manhatton31-svg/forge-resonance) |
| Linear project | [ForgeResonance Fabric](https://linear.app/arclya2a/project/forgeresonance-fabric-dcf8b429da66) |
| Notion hub | [Project documentation](https://app.notion.com/p/3958bb06641d81b7b970ea87a30fe64d) |

---

## License

Proprietary — ForgeResonance Protocol / Arcly Intelligence Layer.