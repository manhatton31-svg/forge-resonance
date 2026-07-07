# Serverless API Examples

Replace `<your-app>` with your Vercel deployment URL. Set `FORGE_API_KEY` and `ARCLY_API_KEY` in the Vercel dashboard when auth is enabled.

## Health

```bash
# Liveness (public)
curl https://<your-app>.vercel.app/api/health

# Deep checks (requires FORGE_API_KEY when configured)
curl -H "Authorization: Bearer $FORGE_API_KEY" \
  "https://<your-app>.vercel.app/api/health?deep=1"

# Fabric reputation snapshot
curl https://<your-app>.vercel.app/api/fabric_health
```

## Swarm route (lightweight, serverless-safe)

Returns ranked agent assignments without running full resonance cycles.

```bash
curl -X POST https://<your-app>.vercel.app/api/swarm \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $FORGE_API_KEY" \
  -d '{
    "mode": "route",
    "intent": {
      "matched_intent": "purchase_intent",
      "text": "I want analytics pricing for enterprise",
      "confidence": 0.85
    },
    "agents": [
      {"agent_id": "atlas", "name": "atlas-analytics", "specialties": ["commercial", "purchase"]},
      {"agent_id": "nova", "name": "nova-research", "specialties": ["research"]}
    ],
    "strategy": "best_single"
  }'
```

## Swarm execute (ephemeral stubs)

For demos and tests on Vercel, pass `bound_agents` with lightweight outcome stubs instead of full `ResonanceAgent` instances.

```bash
curl -X POST https://<your-app>.vercel.app/api/swarm \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $FORGE_API_KEY" \
  -d '{
    "mode": "execute",
    "intent": {"matched_intent": "purchase_intent", "confidence": 0.9},
    "agents": [{"agent_id": "atlas", "name": "atlas-analytics", "specialties": ["purchase"]}],
    "bound_agents": [{"agent_id": "atlas", "outcome": "success", "quality": 0.8}],
    "strategy": "best_single",
    "timeout_s": 20
  }'
```

## Arcly feedback webhook

Arcly reports conversion outcomes to update Resonance Scores.

```bash
curl -X POST https://<your-app>.vercel.app/api/arcly_feedback \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ARCLY_API_KEY" \
  -d '{
    "agent_id": "atlas-demo",
    "outcome": "success",
    "quality": 0.9,
    "resonance_id": "res-123",
    "metadata": {"source": "arcly"}
  }'
```

## Local development

```bash
pip install -r requirements-dev.txt
vercel dev
curl http://localhost:3000/api/health
```

Full deployment guide: [docs/deployment.md](../docs/deployment.md)