#!/usr/bin/env python3
"""
Single-agent resonance cycle — the simplest ForgeResonance integration.

Run from repository root:
    python examples/single_agent.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from demo.bootstrap import (  # noqa: E402
    SINGLE_AGENT_INTENTS,
    create_demo_agent,
    create_demo_stack,
    print_reputation_stats,
    run_agent_cycles_compact,
    section,
)

DATA_DIR = Path("data/examples/single-agent")


def main() -> int:
    manager, _ = create_demo_stack(data_dir=DATA_DIR)
    agent = create_demo_agent(
        "example-agent",
        ["deliver contextual value at the moment of intent"],
        data_dir=DATA_DIR,
        score_manager=manager,
    )

    print("ForgeResonance — single agent example")
    print("Pipeline: Harvest → Generate → Inject → Handoff → Reflect\n")

    result = run_agent_cycles_compact(agent, list(SINGLE_AGENT_INTENTS), print_fn=print)
    section("Reputation", print_fn=print)
    if result.analytics:
        print_reputation_stats(agent.name, result.analytics, print_fn=print)

    print("\nDone. Try: python examples/swarm_execute.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())