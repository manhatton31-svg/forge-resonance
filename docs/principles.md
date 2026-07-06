# ForgeResonance Principles

These principles are non-negotiable. Every architectural decision, module boundary, and integration point must serve them.

---

## 1. Sovereignty First

Agents are first-class citizens. Each agent:

- Runs persistently with its own memory, goals, and offer catalog
- Is owned and controlled by its operator — not the Fabric
- Can function offline with local file/SQLite storage
- Syncs to shared infrastructure only when explicitly configured

No central orchestrator assigns agent behavior. The Fabric is a coordination space, not a control plane.

## 2. Privacy by Design

Intent is the most sensitive signal in the system. ForgeResonance treats it accordingly:

- **Local processing only** — raw signals never leave the device unhashed
- **Opt-in required** — harvesting disabled until explicit consent
- **Hashed representations** — only anonymized intent vectors propagate
- **No central data collection** — no Fabric-wide intent database
- **Zero-knowledge ready** — architecture supports ZK proofs for intent attestation

## 3. Resonance Over Advertising

The system optimizes for demonstrated value, not attention extraction:

| Advertising | ForgeResonance |
|-------------|----------------|
| Impressions | Resonance quality |
| Clicks | Successful outcomes |
| Spend | Earned visibility |
| Central auction | Reputation-weighted matching |

An agent that consistently delivers contextual value earns more Fabric visibility. One that fails or annoys loses it.

## 4. Positive-Sum Flywheel

```
Successful resonance → Score increase → Higher visibility → More opportunities
        ↑                                                    |
        └──── Improved generation from episodic memory ──────┘

Poor resonance → Score decrease → Lower visibility → Self-correction
```

The Resonance Score is transparent and auditable via `reputation_ledger`. Future: decentralized consensus on Cloudflare edge.

## 5. Arcly Integration as Core

ForgeResonance senses intent and delivers value. Arcly closes the loop:

- Qualified resonances hand off to Arcly AI Closer
- Conversion outcomes flow back as score updates
- `OfferFramer` prepares commercial intents for conversion

The handoff contract (`integration/arcly_handoff.py`) is a stable API boundary.

## 6. Grok-Native & xAI-First

Generation is optimized for Grok models with template fallback for sovereignty:

- xAI API as primary inference backend
- Agent memory and goals injected into prompts
- Episodic summaries inform generation quality
- `GROK_MODEL` configurable via environment

## 7. Original Design

ForgeResonance is not a wrapper around advertising platforms or generic agent frameworks. Every component is designed for the resonance paradigm.

## 8. Modularity & Extensibility

Clean interfaces at every layer boundary:

- `IntentHarvesterProtocol` — plug in new signal sources
- `ResonanceEngineProtocol` — swap generation backends
- `ValueInjectorProtocol` — add delivery channels
- `ArclyHandoffProtocol` — extend conversion paths
- `MemoryStore` / `ScoreStore` — choose storage backends

Composition over inheritance. Small, focused modules.

## 9. Production Mindset

From day one:

- Typed dataclasses and enums
- Structured logging with Sentry/Axiom hooks
- Testable with dependency injection
- Environment-driven configuration
- Deployment-ready for Vercel and Cloudflare

---

## Glossary

### Resonance

A completed agent cycle: detect intent → generate value → inject → hand off (optional) → reflect on outcome. The unit of work that updates reputation.

### Resonance Score

Numeric reputation on a 0–100 scale (default 50). Increases on success/partial outcomes, decreases on failure/rejection. Stored in `reputation_ledger` with full audit trail.

**Outcome deltas:** success +2.5, partial +0.5, failure −1.5, rejection −3.0 (scaled by quality on positive outcomes).

### Visibility Multiplier

Derived from Resonance Score via `get_visibility_multiplier()`. Range **0.1 to 2.0**. Determines how prominently an agent appears when the Fabric routes intent across multiple agents.

| Score | Approx. visibility |
|-------|-------------------|
| 0 | 0.10 |
| 50 | 1.05 |
| 100 | 2.00 |

### Selection Weight

`visibility_multiplier × (resonance_score / 100)`. Used by `rank_agents()` to order agents for swarm routing. Higher weight → preferred for the next intent signal.

### ResonancePayload

Structured output from `ResonanceEngine`: `summary`, `recommended_action`, `value_proposition`, `resonance_type`, `quality_estimate`, and metadata. Consumed by `ValueInjector`.

### OfferFramer

`integration/offer_framer.py` — transforms commercial intents into `offer_ready` payloads with `offer_id`, `offer_url`, `cta_text`, and `value_prop` for Arcly handoff.

### IntentSignal

Privacy-preserving harvested intent: type label, confidence, hashed context vector. Never contains raw user text in downstream propagation.

### ResonanceScoreManager

Central reputation API in `reputation/score_layer.py`. Records outcomes, serves analytics, and backs `ReputationLayer.rank_agents()`.

---

## Related Docs

- [architecture.md](architecture.md) — technical layer design
- [getting-started.md](getting-started.md) — hands-on introduction
- [roadmap.md](roadmap.md) — what's built and what's next