# ForgeResonance Roadmap

Last updated: July 2026 · **v0.1.0 released**

---

## Milestone Summary

| Milestone | Status | Theme |
|-----------|--------|-------|
| M1 Foundation | **Complete** | Agent runtime, memory, scoring, Arcly contract |
| M2 Intent Harvesting | **Complete** | Embedding harvester, multi-turn, Firecrawl hook |
| M3 Resonance Engine | **Complete** | Grok prompts, templates, injection, reputation layer |
| M4 Fabric & Edge | **Complete (v0.1)** | KV reputation, routing, swarm execution |
| M5 Production & API | **Complete (v0.1)** | Vercel deployment, API hardening, adoption polish |

**v0.1.0** (2026-07-06) is published on GitHub: [Initial Public Foundation release](https://github.com/manhatton31-svg/forge-resonance/releases/tag/v0.1.0) (`72ef29b`). See [CHANGELOG.md](../CHANGELOG.md) for full notes. Post-v0.1 work is tracked under `[Unreleased]` in the changelog.

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
| Unit test suite (174 tests) | Done |
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

**Post-v0.1:**

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

**Post-v0.1:**

- A/B resonance variant generation
- Offer catalog UI for operators

---

## M4: Fabric & Edge — Complete (v0.1)

| Deliverable | Status |
|-------------|--------|
| `CloudflareKVClient` (`reputation/edge_kv.py`) | Done |
| Edge sync after `record_outcome()` | Done |
| `resolve_score()` KV cold-read fallback | Done |
| `EDGE_REPUTATION_ENABLED` config flag | Done |
| `AgentRegistry` + `IntentRouter` + `SwarmCoordinator` | Done |
| Capability-based intent routing | Done |
| `SwarmCoordinator.execute()` with consensus and metrics | Done |
| Demo: `python -m demo --swarm-only` | Done |
| Examples: `examples/swarm_route.py`, `examples/swarm_execute.py` | Done |

**Post-v0.1:**

- [ ] Cloudflare Workers deployment for edge agents
- [ ] Weighted random selection (probabilistic routing via `selection_weight`)
- [ ] Multi-agent collaboration protocol
- [ ] Fabric-wide health dashboard (Axiom)
- [ ] Decentralized score consensus (research)

---

## M5: Production & API — Complete (v0.1)

| Deliverable | Status |
|-------------|--------|
| Vercel serverless API (`/api/health`, `/api/swarm`, etc.) | Done |
| Serverless swarm route and execute modes | Done |
| API auth, rate limits, validation, error envelope | Done |
| `docs/deployment.md` and deployment config | Done |
| README, examples, and `docs/extending.md` polish | Done |
| Package versioning (`forge_resonance.__version__`) | Done |
| `CHANGELOG.md` and v0.1 release tracking | Done |

**Post-v0.1:**

- [ ] Sentry error monitoring in production
- [ ] Axiom telemetry pipeline (full event stream)
- [ ] Operator dashboard
- [ ] Arcly production handoff hardening at scale
- [ ] Public onboarding and documentation site

---

## MCP Integration Roadmap

| MCP | Current Use | Future Use |
|-----|-------------|------------|
| GitHub | Source control, [v0.1.0 release](https://github.com/manhatton31-svg/forge-resonance/releases/tag/v0.1.0) | CI/CD, release automation |
| Neon | Agent memory + scoring | Branch-per-agent dev environments |
| Vercel | API deployment | Serverless agent endpoints |
| Cloudflare | KV edge reputation | Edge Workers agents |
| Linear | Task tracking | Sprint automation |
| Notion | Project docs | Archivist knowledge base |
| Firecrawl | Intent enrichment hook | Production enrichment pipeline |
| Sentry | Logging hook | Production error monitoring |
| Axiom | Event emission hook | Full telemetry pipeline |

---

## Immediate Next Steps (post-v0.1)

1. **Edge Workers prototype** — single Worker agent + KV reputation read at edge
2. **Probabilistic swarm router** — weighted random selection over `rank_agents()`
3. **KV backfill job** — bulk sync from Neon to KV for existing agents
4. **Operator API** — `/api/agents` CRUD on Vercel
5. **Edge KV on Vercel** — add Cloudflare credentials to production env

**Live deployment:** https://forge-resonance.vercel.app (v0.1.0 production)

See [getting-started.md](getting-started.md) to run what exists today.