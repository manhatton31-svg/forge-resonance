# ForgeResonance Deployment Guide

This guide covers deploying the ForgeResonance API layer to **Vercel** while keeping **Cloudflare KV** edge reputation working via the REST API (no Workers binding required).

## Architecture on Vercel

| Component | Deployment target | Notes |
|-----------|-------------------|-------|
| API (`/api/*`) | Vercel Serverless Functions (Python) | Health, Arcly feedback, swarm routing |
| Neon Postgres | External (Neon) | Source of truth for scores + history |
| Cloudflare KV | External (REST API) | Edge cache for `rank_agents()` reads |
| Full agent runtime | Local / Cloudflare Workers (planned) | Long-running resonance cycles |

The Vercel deployment is optimized for **webhooks**, **health checks**, **fabric reputation queries**, and **lightweight swarm routing** — not continuous agent loops.

## Prerequisites

1. [Vercel account](https://vercel.com) with CLI installed: `npm i -g vercel`
2. [Neon](https://neon.tech) project with `DATABASE_URL` connection string
3. (Optional) Cloudflare account with Workers KV namespace + API token
4. (Optional) Arcly instance for conversion feedback

## Quick deploy

```bash
# From repository root
vercel link          # first time only
vercel env pull .env.local   # optional: sync dashboard vars locally

# Deploy preview
vercel

# Deploy production
vercel --prod
```

## API endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/health` | GET | Liveness + config snapshot (`?deep=1` runs DB/KV checks) |
| `/api/fabric_health` | GET | Fabric reputation + edge sync status |
| `/api/arcly_feedback` | POST | Arcly outcome webhook → Resonance Score |
| `/api/swarm` | GET | Endpoint metadata |
| `/api/swarm` | POST | Swarm route or execute (`mode=route\|execute`) |

### Health check

```bash
curl https://<your-app>.vercel.app/api/health
curl "https://<your-app>.vercel.app/api/health?deep=1"
```

### Swarm routing (serverless-safe)

```bash
curl -X POST https://<your-app>.vercel.app/api/swarm \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "route",
    "intent": {
      "matched_intent": "purchase_intent",
      "text": "I want analytics pricing",
      "confidence": 0.85
    },
    "agents": [
      {
        "agent_id": "atlas",
        "name": "atlas-analytics",
        "specialties": ["commercial", "purchase"]
      },
      {
        "agent_id": "nova",
        "name": "nova-research",
        "specialties": ["research"]
      }
    ],
    "strategy": "best_single"
  }'
```

### Swarm execute (ephemeral agents)

For serverless demos/tests, pass `bound_agents` with lightweight stubs:

```bash
curl -X POST https://<your-app>.vercel.app/api/swarm \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "execute",
    "intent": {"matched_intent": "purchase_intent", "confidence": 0.9},
    "agents": [{"agent_id": "atlas", "name": "atlas-analytics", "specialties": ["purchase"]}],
    "bound_agents": [{"agent_id": "atlas", "outcome": "success", "quality": 0.8}],
    "strategy": "best_single",
    "timeout_s": 20
  }'
```

Set `FORGE_API_KEY` in Vercel and pass `Authorization: Bearer <key>` when configured.

## Required environment variables

Set these in the **Vercel dashboard** (Settings → Environment Variables). Never commit secrets.

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Recommended | Neon Postgres for scores + outcome history |
| `FORGE_STORAGE_BACKEND` | Optional | `neon` or `hybrid` on Vercel |
| `EDGE_REPUTATION_ENABLED` | Optional | `true` to enable KV sync/reads |
| `CLOUDFLARE_API_TOKEN` | If edge enabled | KV REST API auth |
| `CLOUDFLARE_ACCOUNT_ID` | If edge enabled | Cloudflare account |
| `CLOUDFLARE_KV_NAMESPACE` | If edge enabled | KV namespace ID |
| `ARCLY_API_KEY` | If using feedback | Webhook auth (`Bearer` token) |
| `FORGE_API_KEY` | Optional | Protects `/api/swarm` |
| `XAI_API_KEY` | Optional | Grok generation (not needed for routing) |

See [.env.example](../.env.example) for the full list.

## Cloudflare KV setup

1. Create a Workers KV namespace in the Cloudflare dashboard.
2. Create an API token with **Workers KV Storage → Edit** permission.
3. Set `EDGE_REPUTATION_ENABLED=true` plus the three `CLOUDFLARE_*` variables in Vercel.
4. Deploy and verify: `GET /api/fabric_health` should show `edge_reachable: true`.

KV uses the REST API (`reputation/edge_kv.py`) — compatible with Vercel cold starts. A module-level client singleton reuses reachability cache across warm invocations.

## Serverless swarm limitations

| Constraint | Default on Vercel | Mitigation |
|------------|-------------------|------------|
| Function timeout | 60s (`vercel.json`) | `SWARM_SERVERLESS_TIMEOUT=25` |
| Cold starts | New Python process | Cached `ReputationLayer` + KV client |
| No local disk | `/tmp` only, ephemeral | Use Neon; avoid file-backed agents |
| Full agent cycles | Too heavy for default | Use `mode=route` or Workers for full runtime |
| Broadcast fan-out | Limited parallelism | `SWARM_SERVERLESS_MAX_PARALLEL=2` |

When `VERCEL=1`, `load_swarm_config()` automatically caps agent timeout and parallelism.

**Recommended patterns:**

- **Vercel:** routing, reputation updates, Arcly feedback, health
- **Local / Workers:** full `SwarmCoordinator.execute()` with bound `ResonanceAgent` instances

## `vercel.json` summary

- `installCommand`: `pip install -r requirements.txt`
- Per-function `maxDuration` and `memory` tuned per endpoint
- Swarm function: 60s / 1024 MB
- Health endpoints: 15–30s / 512 MB

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `edge_reachable: false` | Token permissions, namespace ID, `EDGE_REPUTATION_ENABLED` |
| Database unreachable | `DATABASE_URL` SSL mode, Neon IP allowlist |
| Swarm timeouts | Lower `SWARM_SERVERLESS_TIMEOUT`, use `mode=route` |
| 401 on swarm | Set `FORGE_API_KEY` or omit Authorization if unset |
| Import errors on deploy | Ensure `requirements.txt` includes `psycopg2-binary` |

## Local development with Vercel dev

```bash
pip install -r requirements-dev.txt
vercel dev
# API available at http://localhost:3000/api/health
```

## Next steps (M4+)

- Cloudflare Workers for edge agent runners
- Neon-backed agent registry (persistent bound agents)
- Axiom/Sentry integration in serverless handlers