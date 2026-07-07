# Getting Started with ForgeResonance

This guide gets you from zero to a running demo in under two minutes, then shows how to upgrade with optional API keys.

---

## Prerequisites

- Python 3.11+
- `pip install -r requirements.txt`

No API keys, database, or external services are required for the default demo.

---

## Step 1: Clone and install

```bash
git clone https://github.com/manhatton31-svg/forge-resonance.git
cd forge-resonance
pip install -r requirements.txt
```

---

## Step 2: Run the demo (template mode)

Template mode uses the built-in resonance engine fallback — no `XAI_API_KEY` needed.

```bash
python -m demo
```

### What runs

| Phase | Agent(s) | Intents | Demonstrates |
|-------|----------|---------|--------------|
| Single agent | `atlas-demo` | 4 (purchase, comparison, research, support) | Full pipeline per cycle |
| Multi-agent | `atlas-analytics`, `nova-research`, `echo-support` | Overlapping commercial intents | `rank_agents()` by selection weight |

### Expected output (abbreviated)

```
════════════════════════════════════════════════════════════
  ForgeResonance — Single Agent Demo
════════════════════════════════════════════════════════════
  Pipeline: Harvest → Generate → Inject → Handoff → Reflect

── Cycle 1: atlas-demo ──
  Intent: I want to buy analytics software and need pricing for the enterprise plan
  [Harvest] intent detected (purchase_intent, confidence ~0.7+)
  [Generate] template payload (no API key)
  [Inject] formatted message delivered
  [Handoff] Arcly dry-run accepted
  [Reflect] outcome: success | score: 52.50
  Resonant value: <summary line from payload>

── Reputation — atlas-demo ──
  Resonance Score:      54.00
  Visibility multiplier:1.08
  Total resonances:     4
  Success rate:         100%
  ...

════════════════════════════════════════════════════════════
  ForgeResonance — Multi-Agent Ranking Demo
════════════════════════════════════════════════════════════
  ...

── Fabric Agent Ranking (by selection weight) ──
  Rank  Agent              Score  Visibility   Weight  Success  Trend
  ------------------------------------------------------------------------
  1     atlas-analytics     58.0       1.16    0.673     100%  improving
  2     nova-research       52.5       1.05    0.551     100%  stable
  3     echo-support        51.0       1.02    0.520     100%  stable

Demo complete.
```

Exact scores vary slightly with embedding sensitivity; ranking order should place `atlas-analytics` first (most cycles).

---

## Step 3: Explore demo flags

```bash
python -m demo --help
```

| Flag | Effect |
|------|--------|
| `--single-only` | Skip multi-agent ranking |
| `--multi-only` | Ranking showcase only |
| `--swarm-only` | Swarm execution: route, run agents, aggregate outcomes |
| `--verbose` | Print full formatted resonant messages |
| `--quiet` | Suppress banners (cycle output still prints) |
| `--data-dir PATH` | Custom agent memory directory |

**Runnable examples** (no demo UI):

```bash
python examples/single_agent.py
python examples/swarm_route.py
python examples/swarm_execute.py
```

See [examples/README.md](../examples/README.md).

---

## Step 4: Run tests

```bash
pip install -r requirements-dev.txt   # includes pytest
python -m pytest tests/ -v
```

Expect **172** passing tests.

---

## Step 5: Start your own agent

```python
from pathlib import Path
from core.resonance_agent import ResonanceAgent
from core.memory import FileMemoryStore
from harvesting.intent_harvester import EmbeddingIntentHarvester
from generation.resonance_engine import ResonanceEngine
from injection.value_injector import ValueInjector
from integration.arcly_handoff import ArclyHandoff

agent = ResonanceAgent(
    name="my-first-agent",
    goals=["help buyers evaluate software"],
    memory_store=FileMemoryStore(base_dir=Path("data/agents")),
    intent_harvester=EmbeddingIntentHarvester(),
    resonance_engine=ResonanceEngine(api_key=""),  # template mode
    value_injector=ValueInjector(),
    arcly_handoff=ArclyHandoff(force_dry_run=True),
)
agent.start()
agent.submit_intent("Compare HubSpot vs Salesforce for a small sales team")
outcome = agent.run_once()
print(outcome, agent.resonance_score)
print(agent.get_reputation_stats())
```

Or use the demo bootstrap helpers:

```python
from pathlib import Path
from demo.bootstrap import create_demo_stack, create_demo_agent, run_agent_cycles

manager, _ = create_demo_stack(data_dir=Path("data/my-demo"))
agent = create_demo_agent(
    "custom-agent",
    ["deliver contextual analytics guidance"],
    data_dir=Path("data/my-demo"),
    score_manager=manager,
)
result = run_agent_cycles(agent, ["I need enterprise analytics pricing"], verbose=True)
```

---

## Optional upgrades

### Enable Grok generation

```bash
# .env
XAI_API_KEY=your-xai-key
GROK_MODEL=grok-3-mini
```

Restart your agent. `ResonanceEngine` calls Grok when the key is set; falls back to templates on failure.

### Enable Neon persistence

```bash
# .env
FORGE_STORAGE_BACKEND=hybrid
DATABASE_URL=postgresql://user:pass@host/neondb?sslmode=require
```

Agents sync episodic memory and reputation to Neon when reachable; local file/SQLite remains the offline fallback.

### Enable live Arcly handoff

```bash
# .env
ARCLY_API_URL=https://your-arcly-instance.example.com
ARCLY_API_KEY=your-secret
ARCLY_MODE=live
ARCLY_FEEDBACK_ENABLED=true
```

Handoffs include reputation snapshot and offer bundle. Arcly can POST outcomes to `/api/arcly_feedback` to update scores asynchronously.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: demo` | Run from project root: `cd forge-resonance` |
| All cycles `skipped` | Lower `INTENT_RESONANCE_THRESHOLD` in `.env` (default 0.35) |
| Verbose forge.* logs during demo | Demo sets `LOG_LEVEL=WARNING` automatically |
| Neon connection errors | Demo works without `DATABASE_URL`; check URL and SSL mode |

---

## Next reading

- [architecture.md](architecture.md) — layer-by-layer design
- [extending.md](extending.md) — add agents, swarm routes, API handlers
- [deployment.md](deployment.md) — Vercel + Cloudflare KV
- [principles.md](principles.md) — design constraints and glossary
- [roadmap.md](roadmap.md) — milestone status and future work