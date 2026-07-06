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

## Current Status

**Phase: M1 Foundation — Complete**

- [x] Full project structure with 25+ modules
- [x] ResonanceAgent with lifecycle loop
- [x] File + SQLite + Neon memory backends
- [x] Resonance Score engine with ledger
- [x] Arcly handoff contract
- [x] Neon database schema
- [x] GitHub repository initialized
- [x] Linear project + milestone issues
- [x] Notion documentation hub
- [x] Unit tests passing
- [x] Vercel deployment config

**Next:** Wire real harvester + Grok generation (M2/M3). See [docs/roadmap.md](docs/roadmap.md).

## License

Proprietary — ForgeResonance Protocol / Arcly Intelligence Layer.