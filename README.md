# ForgeResonance

**v0.1.0** · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

**Earn distribution through demonstrated value — not ad spend.**

ForgeResonance is a reputation-weighted fabric of sovereign AI agents. Each agent senses intent privately, delivers hyper-contextual value, accumulates a **Resonance Score** that governs Fabric visibility, and hands qualified opportunities to **Arcly AI Closer** for conversion.

```bash
git clone https://github.com/manhatton31-svg/forge-resonance.git
cd forge-resonance && pip install -r requirements.txt && python -m demo
```

No API keys. Template generation and in-memory reputation. **~2 minutes to first output.**

---

## When to use ForgeResonance

| Use case | Why ForgeResonance |
|----------|-------------------|
| **Agent-native distribution** | Agents earn visibility from outcomes, not budgets |
| **Multi-agent routing** | Reputation + capability matching across a swarm |
| **Conversion handoff** | Clean Arcly integration with two-way score feedback |
| **Edge reputation** | Cloudflare KV cache for fast routing reads (Neon = source of truth) |
| **Serverless Fabric API** | Health, swarm route/execute, Arcly webhooks on Vercel |

**Not a fit** if you need a traditional ad server, centralized intent database, or heavy always-on agent loops on serverless alone — use Workers or local runtime for full resonance cycles.

---

## Try it in 2 minutes

```bash
pip install -r requirements.txt
python -m demo                    # single agent + multi-agent ranking
python -m demo --swarm-only       # swarm execution across 3 agents
python -m pytest tests/ -q        # 174 tests
```

**Example scripts** (same paths, no demo UI):

```bash
python examples/single_agent.py
python examples/swarm_execute.py
```

See [examples/](examples/) and [docs/getting-started.md](docs/getting-started.md).

### Versioning & releases

ForgeResonance follows [Semantic Versioning](https://semver.org/). Release notes are in [CHANGELOG.md](CHANGELOG.md).

```python
from forge_resonance import __version__  # "0.1.0"
```

Tag `v0.1.0` marks the first foundation release (M1–M5 complete). Future work is tracked under `[Unreleased]` in the changelog.

---

## Key concepts (at a glance)

| Concept | One-line definition |
|---------|---------------------|
| **Resonance** | One cycle: Harvest → Generate → Inject → Handoff → Reflect |
| **Resonance Score** | 0–100 reputation; success raises it, failure lowers it |
| **Visibility multiplier** | Score → routing weight (0.1–2.0) |
| **Selection weight** | `visibility × (score/100)` — swarm ranking metric |
| **Swarm execute** | Route intent, run agent cycles, aggregate with consensus |

**Architecture:**

```
Agents (sovereign) → Reputation Layer → Neon (optional) → Arcly (conversion)
                         ↑
                   Cloudflare KV (edge cache, optional)
```

Per-agent pipeline: `Harvest → Generate → Inject → Handoff → Reflect`

Full design: [docs/architecture.md](docs/architecture.md) · Extend: [docs/extending.md](docs/extending.md)

---

## Common integration paths

### 1. Single agent (simplest)

```python
from demo.bootstrap import create_demo_stack, create_demo_agent, run_agent_cycles_compact
from pathlib import Path

manager, _ = create_demo_stack(data_dir=Path("data/my-agent"))
agent = create_demo_agent("my-agent", ["deliver contextual value"], data_dir=Path("data/my-agent"), score_manager=manager)
run_agent_cycles_compact(agent, ["I need enterprise analytics pricing"])
```

Or: `python examples/single_agent.py`

### 2. Swarm execution

```python
from core.resonance_agent import IntentSignal
from fabric.swarm import SwarmCoordinator, SwarmStrategy

signal = IntentSignal.from_context({"matched_intent": "purchase_intent", "text": "..."}, confidence=0.85)
swarm = SwarmCoordinator(registry, reputation_layer)
swarm.bind_agents([agent_a, agent_b])
result = swarm.execute(signal, strategy=SwarmStrategy.BEST_SINGLE)
```

Or: `python examples/swarm_execute.py`

### 3. Serverless API

```bash
curl https://<your-app>.vercel.app/api/health
curl -X POST https://<your-app>.vercel.app/api/swarm -H "Content-Type: application/json" -d '{"mode":"route", ...}'
```

See [examples/api_calls.md](examples/api_calls.md) and [docs/deployment.md](docs/deployment.md).

---

## Demo options

| Command | What it shows |
|---------|---------------|
| `python -m demo` | Single agent (4 cycles) + multi-agent ranking |
| `python -m demo --single-only` | Full pipeline per intent |
| `python -m demo --multi-only` | `rank_agents()` selection weights |
| `python -m demo --swarm-only` | `SwarmCoordinator.execute()` with metrics |
| `python -m demo --verbose` | Full formatted resonant messages |
| `python -m demo --help` | Phase-by-phase documentation |

---

## Configuration

```bash
cp .env.example .env   # defaults work for local demo
```

| Variable | Purpose | Demo default |
|----------|---------|--------------|
| `XAI_API_KEY` | Grok generation | Empty → templates |
| `DATABASE_URL` | Neon persistence | Optional |
| `ARCLY_API_KEY` | Conversion handoff | Empty → dry_run |
| `EDGE_REPUTATION_ENABLED` | KV edge cache | `false` |
| `FORGE_API_KEY` | API Bearer auth | Set on Vercel only |
| `LOG_LEVEL` | Logging | `INFO` (demo → `WARNING`) |

Full reference: [.env.example](.env.example)

---

## Project structure

```
forge-resonance/
├── forge_resonance/  # Package metadata (`__version__`)
├── core/             # ResonanceAgent, memory, scoring
├── fabric/           # IntentRouter, SwarmCoordinator
├── reputation/       # Resonance Score, edge KV
├── api/              # Vercel serverless handlers
├── demo/             # Interactive CLI (`python -m demo`)
├── examples/         # Runnable integration scripts
├── docs/             # Architecture, deployment, extending
├── CHANGELOG.md      # Release history
└── tests/            # 174 tests
```

---

## Deployment

```bash
vercel link && vercel --prod
curl https://<your-app>.vercel.app/api/health?deep=1
```

Endpoints: `/api/health`, `/api/fabric_health`, `/api/swarm`, `/api/arcly_feedback`

Guide: [docs/deployment.md](docs/deployment.md)

---

## Roadmap

| Milestone | Status |
|-----------|--------|
| M1 Foundation | Complete |
| M2 Intent Harvesting | Complete |
| M3 Resonance Engine | Complete |
| M4 Fabric & Edge | Complete (v0.1) |
| M5 Production & API | Complete (v0.1) |

**v0.1.0** released 2026-07-06. Post-release work is in [CHANGELOG.md § Unreleased](CHANGELOG.md#unreleased).

Details: [docs/roadmap.md](docs/roadmap.md)

---

## Principles

Sovereignty · Privacy by design · Resonance over advertising · Arcly integration · Grok-native · Modularity · Production mindset

[docs/principles.md](docs/principles.md)

---

## Links

| Resource | URL |
|----------|-----|
| Repository | [github.com/manhatton31-svg/forge-resonance](https://github.com/manhatton31-svg/forge-resonance) |
| Linear | [ForgeResonance Fabric](https://linear.app/arclya2a/project/forgeresonance-fabric-dcf8b429da66) |
| Notion | [Project documentation](https://app.notion.com/p/3958bb06641d81b7b970ea87a30fe64d) |

---

## License

[MIT](LICENSE) — see [CONTRIBUTING.md](CONTRIBUTING.md) for how to extend and contribute.