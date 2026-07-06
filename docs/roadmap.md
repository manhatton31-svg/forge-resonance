# ForgeResonance Roadmap

Last updated: July 2026

---

## Milestone Summary

| Milestone | Status | Theme |
|-----------|--------|-------|
| M1 Foundation | **Complete** | Agent runtime, memory, scoring, Arcly contract |
| M2 Intent Harvesting | **Complete** | Embedding harvester, multi-turn, Firecrawl hook |
| M3 Resonance Engine | **Complete** | Grok prompts, templates, injection, reputation layer |
| M4 Fabric & Edge | **In Progress** | KV reputation (initial), Workers, swarm routing |
| M5 Production Launch | Planned | Dashboard, full observability, operator tooling |

---

## M1: Foundation — Complete

| Deliverable | Status |
|-------------|--------|
| Project structure and core modules | Done |
| ResonanceAgent lifecycle | Done |
| File + SQLite + Neon memory backends | Done |
| Resonance Score engine with ledger | Done |
| Arcly handoff contract | Done |
| Neon database schema | Done |
| GitHub repository | Done |
| Unit test suite (~110 tests) | Done |
| Vercel deployment config | Done |
| Interactive demo (`python -m demo`) | Done |

---

## M2: Intent Harvesting — Complete

| Deliverable | Status |
|-------------|--------|
| `EmbeddingIntentHarvester` with keyword + embedding scoring | Done |
| Multi-turn context boost | Done |
| `ingest_text`, `ingest_from_chat`, `ingest_from_webhook` APIs | Done |
| Firecrawl enrichment hook (`FIRECRAWL_ENABLED`) | Done |
| Privacy boundary (hashed signals) | Done |

**Remaining (M4+):**

- Browser extension signal adapter
- Zero-knowledge intent attestation prototype
- Consent management UI

---

## M3: Resonance Engine — Complete

| Deliverable | Status |
|-------------|--------|
| Grok prompt engineering with episodic memory | Done |
| Context-aware template fallback (no API key) | Done |
| Quality estimation model | Done |
| `ValueInjector` delivery modes | Done |
| `OfferFramer` for commercial intents | Done |
| `ResonanceScoreManager` + `rank_agents()` | Done |
| Multi-agent demo ranking | Done |
| Arcly two-way feedback (`/api/arcly_feedback`) | Done |

**Remaining (M5):**

- A/B resonance variant generation
- Offer catalog UI for operators

---

## M4: Fabric & Edge — In Progress (Q3–Q4 2026)

| Deliverable | Status |
|-------------|--------|
| `CloudflareKVClient` (`reputation/edge_kv.py`) | Done |
| Edge sync after `record_outcome()` | Done |
| `resolve_score()` KV cold-read fallback | Done |
| `EDGE_REPUTATION_ENABLED` config flag | Done |

Remaining:

- [ ] Cloudflare Workers deployment for edge agents
- [ ] Fabric router: weighted random selection via `selection_weight`
- [ ] Multi-agent collaboration protocol
- [ ] Fabric-wide health dashboard (Axiom)
- [ ] Decentralized score consensus (research)

**Success criteria:** Route intent across 100+ edge agents using KV-cached reputation with Neon as source of truth.

---

## M5: Production Launch (Q1 2027)

- [ ] Sentry error monitoring in production
- [ ] Axiom telemetry pipeline (full event stream)
- [ ] Vercel serverless API for agent management
- [ ] Operator dashboard
- [ ] Arcly production handoff hardening
- [ ] Public onboarding and documentation site

---

## MCP Integration Roadmap

| MCP | Current Use | Future Use |
|-----|-------------|------------|
| GitHub | Source control, commits | CI/CD, release automation |
| Neon | Agent memory + scoring | Branch-per-agent dev environments |
| Vercel | API deployment | Serverless agent endpoints |
| Cloudflare | Documented | Edge reputation, Workers agents |
| Linear | Task tracking | Sprint automation |
| Notion | Project docs | Archivist knowledge base |
| Firecrawl | Intent enrichment hook | Production enrichment pipeline |
| Sentry | Logging hook | Production error monitoring |
| Axiom | Event emission hook | Full telemetry pipeline |

---

## Immediate Next Steps

1. **Edge Workers prototype** — single Worker agent + KV reputation read at edge
2. **Swarm router** — weighted selection over `rank_agents()` output
3. **KV backfill job** — bulk sync from Neon to KV for existing agents
4. **Operator API** — `/api/agents` CRUD on Vercel

See [getting-started.md](getting-started.md) to run what exists today.