#!/usr/bin/env python3
"""
Swarm routing only — rank and assign agents without running resonance cycles.

Use this when you need lightweight Fabric routing (e.g. serverless ``mode=route``).

Run from repository root:
    python examples/swarm_route.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.registry import AgentRegistry, RegisteredAgent  # noqa: E402
from core.resonance_agent import IntentSignal  # noqa: E402
from demo.bootstrap import SWARM_AGENT_SPECS, SWARM_ROUTING_INTENTS, create_demo_stack  # noqa: E402
from fabric.router import IntentRouter  # noqa: E402

DATA_DIR = Path("data/examples/swarm-route")


def main() -> int:
    _, reputation = create_demo_stack(data_dir=DATA_DIR)

    registry = AgentRegistry()
    for name, goals, specialties in SWARM_AGENT_SPECS:
        registry.register(
            RegisteredAgent(
                agent_id=f"demo-{name}",
                name=name,
                goals=goals,
                specialties=specialties,
            )
        )

    router = IntentRouter(registry, reputation)

    print("ForgeResonance — swarm routing example")
    print("Routes intents by capability + reputation (no agent execution)\n")

    for intent_label, text in SWARM_ROUTING_INTENTS:
        signal = IntentSignal.from_context(
            {"matched_intent": intent_label, "text": text},
            confidence=0.85,
        )
        ranked = router.route(signal, top_n=3)

        print(f"Intent: {intent_label}")
        if not ranked:
            print("  No matching agents")
            print()
            continue
        print(f"  Primary: {ranked[0].agent_name}")
        for row in ranked:
            print(
                f"  • #{row.rank} {row.agent_name}: combined={row.combined_score:.3f}  "
                f"weight={row.selection_weight:.3f}  capability={row.capability_score:.2f}"
            )
        print()

    print("Done. For full execution: python examples/swarm_execute.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())