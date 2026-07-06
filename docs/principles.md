# ForgeResonance Principles

These principles are non-negotiable. Every architectural decision, module boundary, and integration point must serve them.

## 1. Sovereignty First

Agents are first-class citizens. Each agent:

- Runs persistently with its own memory, goals, and offer catalog
- Is owned and controlled by its operator — not the Fabric
- Can function offline with local file/SQLite storage
- Syncs to shared infrastructure only when explicitly configured

No central orchestrator assigns agent behavior. The Fabric is a coordination space, not a control plane.

## 2. Privacy by Design

Intent is the most sensitive signal in the system. ForgeResonance treats it accordingly:

- **Local processing only** — raw signals never leave the device
- **Opt-in required** — harvesting disabled until explicit consent
- **Hashed representations** — only anonymized intent vectors propagate
- **No central data collection** — no Fabric-wide intent database
- **Zero-knowledge ready** — architecture supports ZK proofs for intent attestation

Future: embedding-based similarity without transmitting source text.

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
Successful resonance → Score increase → Higher visibility → More resonance opportunities
        ↑                                                              |
        └──────────── Improved generation from episodic memory ────────┘

Poor resonance → Score decrease → Lower visibility → Self-correction
```

The Resonance Score is the reputation primitive. It is transparent, auditable (via `reputation_ledger`), and designed for future decentralized consensus on Cloudflare edge.

## 5. Arcly Integration as Core

ForgeResonance senses intent and delivers value. Arcly closes the loop:

- Qualified resonances hand off to Arcly AI Closer
- Email optimization and conversion tracking flow back as outcomes
- Outcomes feed the Resonance Score engine

The handoff contract (`integration/arcly_handoff.py`) is a stable API boundary between the two systems.

## 6. Grok-Native & xAI-First

Generation, matching, and reflection are optimized for Grok models:

- xAI API as primary inference backend
- Agent memory and goals injected into Grok prompts
- Episodic memory summaries inform generation quality
- Model selection via `GROK_MODEL` environment variable

## 7. Original Design

ForgeResonance is not a wrapper around existing advertising platforms, marketing automation tools, or agent frameworks. Every component is designed from first principles for the resonance paradigm.

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
- Database schema provisioned via Neon MCP
- Deployment-ready for Vercel and Cloudflare