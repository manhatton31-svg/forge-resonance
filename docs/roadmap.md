# ForgeResonance Roadmap

## M1: Foundation (Current — Q3 2026)

**Status: In Progress**

| Deliverable | Status |
|-------------|--------|
| Project structure and core modules | Done |
| ResonanceAgent lifecycle skeleton | Done |
| File + SQLite + Neon memory backends | Done |
| Resonance Score engine with ledger | Done |
| Arcly handoff contract | Done |
| Neon database schema (via MCP) | Done |
| GitHub repository | Done |
| Linear project + issues | Done |
| Notion documentation hub | Done |
| Unit test suite | Done |
| Vercel deployment config | Done |

**Next steps:**
- Wire real IntentHarvester into agent loop
- Implement Grok API calls in ResonanceEngine
- End-to-end test with Arcly staging

---

## M2: Intent Harvesting (Q4 2026)

- Local embedding pipeline for intent vectors
- Browser extension signal adapter (opt-in)
- Firecrawl integration for opt-in web enrichment
- Zero-knowledge intent attestation prototype
- Privacy audit and consent management UI

**Linear:** ARC-23

---

## M3: Resonance Engine (Q4 2026)

- Full Grok prompt engineering with episodic memory
- Offer catalog and score-weighted matching
- Quality estimation model
- A/B resonance variant generation
- Contextual value templates

---

## M4: Fabric & Reputation (Q1 2027)

- Cloudflare Workers deployment for edge agents
- KV-backed reputation cache with Neon sync
- Multi-agent collaboration protocol
- Fabric-wide health dashboard (Axiom)
- Decentralized score consensus (research)

---

## M5: Production Launch (Q1 2027)

- Sentry error monitoring in production
- Axiom telemetry pipeline
- Vercel serverless API for agent management
- Operator dashboard
- Arcly production handoff
- Documentation and onboarding

---

## MCP Integration Roadmap

| MCP | Current Use | Future Use |
|-----|-------------|------------|
| GitHub | Source control | CI/CD, release automation |
| Neon | Agent memory + scoring | Branch-per-agent dev environments |
| Vercel | API deployment | Serverless agent endpoints |
| Cloudflare | Documented | Edge reputation, Workers agents |
| Linear | Task tracking | Sprint automation |
| Notion | Project docs | Archivist agent knowledge base |
| Firecrawl | Documented hook | Intent enrichment |
| Sentry | Logging hook | Production error monitoring |
| Axiom | Event emission hook | Full telemetry pipeline |
| Figma | — | Architecture diagrams |
| MongoDB | — | Alternative document store if needed |