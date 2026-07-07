#!/usr/bin/env python3
"""
Swarm execution — route, run resonance cycles, and aggregate outcomes.

Run from repository root:
    python examples/swarm_execute.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.registry import AgentRegistry, RegisteredAgent  # noqa: E402
from core.resonance_agent import IntentSignal  # noqa: E402
from demo.bootstrap import (  # noqa: E402
    MULTI_AGENT_SCENARIOS,
    SWARM_AGENT_SPECS,
    SWARM_ROUTING_INTENTS,
    create_demo_agent,
    create_demo_stack,
    run_agent_cycles_compact,
)
from fabric.swarm import ConsensusStrategy, SwarmCoordinator, SwarmStrategy  # noqa: E402

DATA_DIR = Path("data/examples/swarm-execute")


def main() -> int:
    manager, reputation = create_demo_stack(data_dir=DATA_DIR)

    registry = AgentRegistry()
    agents = []
    for name, goals, specialties in SWARM_AGENT_SPECS:
        agent = create_demo_agent(name, goals, data_dir=DATA_DIR, score_manager=manager)
        agents.append(agent)
        registry.register(
            RegisteredAgent(
                agent_id=agent.agent_id,
                name=agent.name,
                goals=goals,
                specialties=specialties,
            )
        )

    swarm = SwarmCoordinator(registry, reputation)
    swarm.bind_agents(agents)

    print("ForgeResonance — swarm execution example")
    print("Warm-up cycles build reputation, then swarm.execute() runs live resonances\n")

    for agent in agents:
        intents = list(MULTI_AGENT_SCENARIOS.get(agent.name, [])[:2])
        if intents:
            run_agent_cycles_compact(agent, intents, print_fn=lambda _: None)

    for intent_label, text in SWARM_ROUTING_INTENTS:
        signal = IntentSignal.from_context(
            {"matched_intent": intent_label, "text": text},
            confidence=0.85,
        )
        result = swarm.execute(signal, strategy=SwarmStrategy.BEST_SINGLE)
        best = result.best_result
        print(f"Intent: {intent_label}")
        if best:
            print(
                f"  Best: {best.agent_name} → {best.outcome.value}  "
                f"(quality={best.quality:.2f}, swarm_quality={result.swarm_quality:.2f})"
            )
        else:
            print(f"  No successful agent (failures={result.metrics.failure_count})")
        print()

    purchase = IntentSignal.from_context(
        {"matched_intent": "purchase_intent", "text": SWARM_ROUTING_INTENTS[0][1]},
        confidence=0.9,
    )
    broadcast = swarm.execute(
        purchase,
        strategy=SwarmStrategy.BROADCAST_TOP_N,
        top_n=3,
        consensus_strategy=ConsensusStrategy.QUALITY_WEIGHTED,
    )
    print("Broadcast top 3 (purchase_intent):")
    for agent_result in broadcast.agent_results:
        status = agent_result.outcome.value if agent_result.outcome else "unknown"
        print(f"  • {agent_result.agent_name}: {status}  (quality={agent_result.quality:.2f})")
    if broadcast.consensus_outcome:
        print(f"  Consensus: {broadcast.consensus_outcome.value}")

    print("\nDone. Deploy API: see examples/api_calls.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())