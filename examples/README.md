# ForgeResonance Examples

Runnable scripts for the three most common integration paths. No API keys required — all examples use template generation and in-memory reputation.

Run from the **repository root**:

```bash
python examples/single_agent.py
python examples/swarm_route.py
python examples/swarm_execute.py
```

## Scripts

| Script | What it demonstrates |
|--------|----------------------|
| `single_agent.py` | One `ResonanceAgent`, four intent cycles, reputation stats |
| `swarm_route.py` | `IntentRouter` + reputation-weighted routing (no execution) |
| `swarm_execute.py` | Full `SwarmCoordinator.execute()` with best-single and broadcast |

## Serverless API

See [api_calls.md](api_calls.md) for `curl` examples against `/api/health`, `/api/swarm`, and `/api/arcly_feedback` on Vercel.

## Next steps

- [docs/getting-started.md](../docs/getting-started.md) — step-by-step onboarding
- [docs/extending.md](../docs/extending.md) — add agents, routes, and API handlers
- `python -m demo` — interactive showcase with ranking tables