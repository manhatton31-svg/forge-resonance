#!/usr/bin/env python3
"""
ForgeResonance interactive demo.

Run from project root:
    python -m demo
    python demo/run_demo.py
    python -m demo --help
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Suppress forge.* INFO logs during demo for cleaner terminal output.
os.environ.setdefault("LOG_LEVEL", "WARNING")

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from demo.bootstrap import (  # noqa: E402
    run_full_demo,
    run_multi_agent_ranking_demo,
    run_single_agent_demo,
    run_swarm_routing_demo,
)

DEMO_EPILOG = """
Demo phases
───────────
  Default (no flags)
    Runs both phases below in sequence.

  Single-agent phase (--single-only)
    Agent: atlas-demo
    Intents: purchase, comparison, research, support (4 cycles)
    Pipeline per cycle:
      Harvest   — EmbeddingIntentHarvester detects intent type + confidence
      Generate  — ResonanceEngine builds payload (template mode, no API key)
      Inject    — ValueInjector delivers formatted resonant value
      Handoff   — ArclyHandoff dry-run with reputation context
      Reflect   — ResonanceScoreManager updates score and analytics

  Multi-agent phase (--multi-only or second half of default)
    Agents: atlas-analytics, nova-research, echo-support
    Competing on overlapping commercial intents with different cycle counts.
    Demonstrates ReputationLayer.rank_agents() and selection weight
    (visibility × score/100) — the primitive for Fabric swarm routing.

  Swarm routing phase (--swarm-only)
    Routes purchase, research, and support intents via IntentRouter +
    SwarmCoordinator. Shows capability matching + edge-aware reputation.

Output modes
────────────
  Default     — compact cycle summaries + reputation stats + ranking table
  --verbose   — full formatted resonant messages for each cycle
  --quiet     — suppress banners only (cycle results still print)

No API keys required. Uses template generation and in-memory reputation.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ForgeResonance — live demo of the resonance pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=DEMO_EPILOG,
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/demo"),
        help="Directory for demo agent memory (default: data/demo)",
    )
    parser.add_argument(
        "--single-only",
        action="store_true",
        help="Run only the single-agent demo (4 intent cycles)",
    )
    parser.add_argument(
        "--multi-only",
        action="store_true",
        help="Run only the multi-agent ranking demo",
    )
    parser.add_argument(
        "--swarm-only",
        action="store_true",
        help="Run swarm intent routing demo (capability + reputation)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full formatted resonant messages per cycle",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress banner headers (cycle output still prints)",
    )
    args = parser.parse_args(argv)

    verbose = args.verbose
    print_fn = print if not args.quiet else lambda _msg: None

    if args.single_only:
        run_single_agent_demo(
            data_dir=args.data_dir,
            print_fn=print,
            verbose=verbose,
            show_banners=not args.quiet,
        )
    elif args.multi_only:
        run_multi_agent_ranking_demo(
            data_dir=args.data_dir,
            print_fn=print,
            verbose=verbose,
            show_banners=not args.quiet,
        )
    elif args.swarm_only:
        run_swarm_routing_demo(
            data_dir=args.data_dir,
            print_fn=print,
            show_banners=not args.quiet,
        )
    else:
        run_full_demo(
            data_dir=args.data_dir,
            print_fn=print_fn if args.quiet else print,
            skip_multi=False,
            verbose=verbose,
            show_banners=not args.quiet,
        )

    print("\nDemo complete. Run with --help to see what each phase demonstrates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())