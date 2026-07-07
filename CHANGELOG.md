# Changelog

All notable changes to ForgeResonance are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- Cloudflare Workers deployment for edge agent runners
- Probabilistic swarm routing (weighted random selection)
- Operator dashboard and full Axiom/Sentry observability pipeline
- Public documentation site and onboarding flow
- A/B resonance variant generation

---

## [0.1.0] - 2026-07-06

First foundation release — core agent pipeline, Fabric routing, edge reputation, serverless API, and adoption polish.

### Added

#### M1 — Foundation (`23fb308`, `c7a25f0`)

- `ResonanceAgent` lifecycle: Harvest → Generate → Inject → Handoff → Reflect
- File, SQLite, and Neon memory backends with hybrid storage mode
- Resonance Score engine with append-only reputation ledger
- Arcly handoff contract and conversion integration layer
- Neon Postgres schema (agents, memory, events, ledger)
- Project module layout (`core/`, `harvesting/`, `generation/`, `injection/`, `reputation/`, `integration/`)
- Initial unit test suite and Vercel deployment scaffolding

#### M2 — Intent Harvesting (`08a96a5`)

- `EmbeddingIntentHarvester` with keyword + embedding intent scoring
- Multi-turn context boost and privacy-preserving `IntentSignal` hashing
- Ingestion APIs: `ingest_text`, `ingest_from_chat`, `ingest_from_webhook`
- Optional Firecrawl URL enrichment hook (`FIRECRAWL_ENABLED`)

#### M3 — Resonance Engine (`4054d7b`, `6c7a3f1`, `be775b4`, `2318f19`)

- Grok-native `ResonanceEngine` with structured `ResonancePayload` output
- Template fallback generation (zero API keys required for demo)
- `ValueInjector` delivery modes and handoff preparation
- `OfferFramer` for commercial intent tagging and Arcly offer bundles
- `ResonanceScoreManager`, `ReputationLayer`, and `rank_agents()` multi-agent ranking
- Arcly two-way feedback via `report_outcome()` and `/api/arcly_feedback`
- Interactive demo (`python -m demo`) and multi-agent ranking showcase (`fd250cf`)

#### M4 — Fabric & Edge (`16cef59`, `fc147e9`, `788f720`, `019f3c2`, `22b193a`)

- `CloudflareKVClient` edge reputation replication (`reputation/edge_kv.py`)
- Automatic KV sync after `record_outcome()` with graceful local fallback
- `EDGE_REPUTATION_ENABLED` and `EDGE_READ_PREFERENCE` configuration
- `AgentRegistry`, `IntentRouter`, and capability-based intent routing
- `SwarmCoordinator` with `dispatch()` and `execute()` strategies
- Swarm execution: timeouts, partial failures, consensus strategies, metrics
- Demo swarm phase: `python -m demo --swarm-only`
- Config: `SWARM_AGENT_TIMEOUT`, `SWARM_MAX_PARALLEL`, `SWARM_CONSENSUS_STRATEGY`

#### M5 — Production & Serverless API (`982f928`, `a543ef6`)

- Vercel serverless API: `/api/health`, `/api/fabric_health`, `/api/swarm`, `/api/arcly_feedback`
- Serverless-aware swarm routing and ephemeral agent execution
- API hardening: Bearer auth, rate limits, validation, standardized JSON errors
- Correlation IDs on all API responses
- `docs/deployment.md`, `vercel.json`, and `.vercelignore`
- Serverless caps: `SWARM_SERVERLESS_TIMEOUT`, `SWARM_SERVERLESS_MAX_PARALLEL`

#### Polish & adoption (`225ba81`, `6da0535`)

- Restructured README with value proposition, when-to-use guide, and 2-minute quick start
- `examples/` folder: single agent, swarm route/execute, API curl reference
- `docs/extending.md` for agent, swarm, and API extension paths
- Module docstrings and demo `--help` improvements
- **174** passing tests (including version import tests)

### Changed

- API service version aligned to package version `0.1.0`
- Roadmap updated to reflect v0.1 milestone completion

---

[Unreleased]: https://github.com/manhatton31-svg/forge-resonance/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/manhatton31-svg/forge-resonance/releases/tag/v0.1.0