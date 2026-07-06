# ForgeResonance Protocol

**A self-organizing fabric of sovereign AI agents that earn distribution through demonstrated resonance success.**

ForgeResonance replaces paid advertising with a utility-driven, reputation-weighted system where agents sense intent privately, deliver hyper-contextual value at the moment it matters, and accumulate Resonance Score that governs future visibility on the Fabric.

## The Problem

Paid advertising optimizes for impressions and clicks. It centralizes intent data, interrupts users, and rewards spend — not value. There is no primitive for agents to earn distribution by proving they deliver timely, contextual utility.

## The Solution

ForgeResonance introduces the **Resonance Score** — a reputation primitive where:

- Successful resonances **increase** an agent's Fabric visibility
- Poor performance **decreases** it
- Intent is sensed **locally** with opt-in privacy
- Value is injected **contextually**, not interruptively
- Conversion hands off cleanly to **Arcly AI Closer**

## Architecture

```
Sovereign Agents → Intent Harvesting → Resonance Engine → Value Injection
       ↑                                                        |
       └──────── Resonance Score ← Arcly Handoff ←─────────────┘
```

See [docs/architecture.md](docs/architecture.md) for the full system design.

## Quick Start

```bash
# Clone
git clone https://github.com/manhatton31-svg/forge-resonance.git
cd forge-resonance

# Install
pip install -r requirements.txt

# Configure (copy and edit)
cp .env.example .env

# Run tests
python -m pytest tests/ -v

# Quick Demo — full pipeline + multi-agent ranking
python -m demo
# Or: python demo/run_demo.py
# Options: --single-only  --multi-only  --data-dir ./data/demo

# Start an agent (Python)
python -c "
from core.resonance_agent import ResonanceAgent
agent = ResonanceAgent('my-agent', goals=['deliver contextual value'])
agent.start()
print(agent)
agent.run_once()
"
```

## Project Structure

```
forge-resonance/
├── core/               # Agent runtime, memory, scoring, state
├── harvesting/         # Privacy-preserving intent signals
├── generation/         # Grok-native resonance engine
├── injection/          # Contextual value delivery
├── reputation/         # Decentralized Resonance Score layer
├── integration/        # Arcly AI Closer handoff
├── agents/             # Custom agent implementations
├── utils/              # Logging and observability
├── api/                # Vercel serverless endpoints
├── docs/               # Architecture, principles, roadmap
├── demo/               # Interactive demo + multi-agent ranking showcase
├── tests/              # Test suite
└── config.py           # Environment-driven configuration
```

## Core Principles

1. **Sovereignty First** — Agents own their memory and goals
2. **Privacy by Design** — Local intent processing, opt-in only
3. **Resonance Over Advertising** — Quality outcomes drive visibility
4. **Positive-Sum Flywheel** — Success breeds more opportunity
5. **Arcly Integration** — Clean conversion handoff
6. **Grok-Native** — Optimized for xAI models
7. **Original Design** — Built from first principles
8. **Production Mindset** — Typed, tested, observable from day one

See [docs/principles.md](docs/principles.md) for details.

## MCP Integrations

This project was initialized using Grok Build MCP servers:

| MCP | Usage |
|-----|-------|
| **GitHub** (`grok_com_github`) | Repository: [manhatton31-svg/forge-resonance](https://github.com/manhatton31-svg/forge-resonance) |
| **Neon** (`neon`) | Postgres project `forge-resonance` — agent memory + reputation schema |
| **Linear** (`grok_com_linear`) | Project: [ForgeResonance Fabric](https://linear.app/arclya2a/project/forgeresonance-fabric-dcf8b429da66) |
| **Notion** (`grok_com_notion`) | [Project Hub](https://app.notion.com/p/3958bb06641d81b7b970ea87a30fe64d) + Roadmap |
| **Vercel** (`grok_com_vercel`) | `vercel.json` + `/api/health` serverless endpoint |
| **Cloudflare** | Edge reputation layer (documented, M4) |
| **Firecrawl** | Intent enrichment hook (M2) |
| **Sentry / Axiom** | Observability patterns in `utils/logging.py` |

### Neon Database

Schema provisioned via Neon MCP on project `forge-resonance` (`late-glade-09092928`):

- `agents` — identity, Resonance Score, goals
- `working_memory` — short-term keyed store
- `episodic_memory` — resonance history
- `resonance_events` — event stream
- `reputation_ledger` — score audit trail

Set `DATABASE_URL` in `.env` to enable Neon sync.

## Deployment

### Vercel (API layer)

```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
cd forge-resonance
vercel

# Set environment variables in Vercel dashboard:
# DATABASE_URL, XAI_API_KEY, ARCLY_API_KEY, SENTRY_DSN
```

### Cloudflare (future — edge agents + reputation)

See [docs/architecture.md](docs/architecture.md#deployment-topology) for the planned Cloudflare Workers + KV topology.

## Quick Demo

Run the end-to-end showcase from the project root:

```bash
python -m demo
```

This runs two phases:

1. **Single agent** — `atlas-demo` processes four realistic intents (purchase, comparison, research, support). Each cycle prints the formatted resonant value and updates reputation.
2. **Multi-agent ranking** — Three agents (`atlas-analytics`, `nova-research`, `echo-support`) run overlapping intents. `ReputationLayer.rank_agents()` ranks them by selection weight (visibility × score).

```bash
python -m demo --single-only    # one agent, four cycles
python -m demo --multi-only     # ranking showcase only
```

No API keys required — uses template generation and in-memory reputation.

## Arcly AI Closer Integration

ForgeResonance hands qualified resonances to **Arcly** for conversion (email follow-up, offer presentation, close tracking).

**Dry-run (default):** No `ARCLY_API_KEY` or local URL → simulated handoff with reputation context.

**Live mode:** Set credentials and a production URL:

```bash
ARCLY_API_URL=https://your-arcly-instance.example.com
ARCLY_API_KEY=your-secret-key
ARCLY_MODE=live   # or auto (default)
```

Each handoff includes:
- Formatted payload + offer bundle (for commercial intents)
- Agent reputation (`resonance_score`, `visibility_multiplier`, `success_rate`, `trend`)

**Two-way feedback:** Arcly reports conversion outcomes back via `report_outcome()` or the webhook:

```bash
POST /api/arcly_feedback
Authorization: Bearer <ARCLY_API_KEY>
{"agent_id": "...", "resonance_id": "...", "outcome": "success", "quality": 0.9}
```

This updates the agent's Resonance Score asynchronously.

## Current Status

**Phase: M1 Foundation — Complete**

- [x] Full project structure with 25+ modules
- [x] ResonanceAgent with lifecycle loop
- [x] File + SQLite + Neon memory backends
- [x] Resonance Score engine with ledger
- [x] Arcly handoff contract
- [x] Neon database schema
- [x] Interactive demo (`python -m demo`)
- [x] Multi-agent reputation ranking
- [x] GitHub repository initialized
- [x] Linear project + milestone issues
- [x] Notion documentation hub
- [x] Unit tests passing
- [x] Vercel deployment config

**Next:** Agent swarm routing at scale (M4). See [docs/roadmap.md](docs/roadmap.md).

## License

Proprietary — ForgeResonance Protocol / Arcly Intelligence Layer.