# Extending ForgeResonance

ForgeResonance is designed as a composable foundation. Most extensions fit one of three paths below.

---

## Path 1: Add a sovereign agent

**When:** You want one agent that senses intent, delivers value, and earns reputation.

**Start here:** `core/resonance_agent.py`, `examples/single_agent.py`

```python
from pathlib import Path
from demo.bootstrap import create_demo_stack, create_demo_agent, run_agent_cycles

manager, _ = create_demo_stack(data_dir=Path("data/my-agent"))
agent = create_demo_agent(
    "my-agent",
    goals=["help buyers evaluate analytics tools"],
    data_dir=Path("data/my-agent"),
    score_manager=manager,
)
run_agent_cycles(agent, ["I need enterprise analytics pricing"], verbose=True)
```

**Swap components** via constructor injection:

| Component | Default | Replace with |
|-----------|---------|--------------|
| Intent harvester | `EmbeddingIntentHarvester` | Custom `IntentHarvesterProtocol` |
| Resonance engine | `ResonanceEngine` (Grok or template) | Custom `ResonanceEngineProtocol` |
| Value injector | `ValueInjector` | Custom `ValueInjectorProtocol` |
| Arcly handoff | `ArclyHandoff` | Custom `ArclyHandoffProtocol` |
| Memory | `FileMemoryStore` | `SqliteMemoryStore`, Neon hybrid |

---

## Path 2: Add swarm routing or execution

**When:** Multiple agents compete for intents; reputation should govern visibility.

**Start here:** `fabric/router.py`, `fabric/swarm.py`, `examples/swarm_execute.py`

1. Register agents in `AgentRegistry` with `specialties` for capability matching.
2. Share one `ReputationLayer` / `ResonanceScoreManager` across agents.
3. **Route only:** `IntentRouter.route(signal, top_n=3)` — lightweight, serverless-safe.
4. **Route + execute:** `SwarmCoordinator.execute(signal, strategy=...)` — runs full resonance cycles.

```python
from fabric.swarm import SwarmCoordinator, SwarmStrategy

swarm = SwarmCoordinator(registry, reputation_layer)
swarm.bind_agents([agent_a, agent_b])
result = swarm.execute(signal, strategy=SwarmStrategy.BEST_SINGLE)
```

**Edge reputation:** Enable `EDGE_REPUTATION_ENABLED` so `rank_agents()` reads Cloudflare KV at the edge. Neon remains source of truth.

---

## Path 3: Add or extend API routes

**When:** You need webhooks, health checks, or serverless swarm endpoints on Vercel.

**Start here:** `api/runtime.py`, `api/swarm.py`, `examples/api_calls.md`

| Handler | Shared runtime |
|---------|----------------|
| Health | `build_health_payload(deep=True)` |
| Swarm | `handle_swarm_request(body)` |
| Arcly feedback | `record_arcly_outcome(body)` |

New routes should use `api/errors.py` for standardized JSON errors and `api/security.py` for Bearer auth and rate limits.

**Serverless constraint:** Full `ResonanceAgent` loops are heavy on Vercel. Use `mode=route` for production routing; reserve `mode=execute` with `bound_agents` stubs or run full execution locally / on Workers.

---

## Testing your extension

```bash
python -m pytest tests/ -q
python examples/single_agent.py      # smoke test agent path
python -m demo --swarm-only          # smoke test swarm path
```

Add focused tests under `tests/` mirroring existing patterns (`test_fabric_routing.py`, `test_api_serverless.py`).

---

## Related docs

- [getting-started.md](getting-started.md) — onboarding
- [architecture.md](architecture.md) — layer design and extension points
- [deployment.md](deployment.md) — Vercel + KV setup