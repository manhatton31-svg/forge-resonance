#!/usr/bin/env python3
"""
ForgeResonance interactive demo.

Run from project root:
    python demo/run_demo.py
    python -m demo
    python -m demo --multi-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path when invoked as a script.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from demo.bootstrap import (  # noqa: E402
    run_full_demo,
    run_multi_agent_ranking_demo,
    run_single_agent_demo,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ForgeResonance — live demo of the resonance pipeline",
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
        help="Run only the single-agent demo",
    )
    parser.add_argument(
        "--multi-only",
        action="store_true",
        help="Run only the multi-agent ranking demo",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress banner output (still prints cycle results)",
    )
    args = parser.parse_args(argv)

    print_fn = print if not args.quiet else lambda _msg: None

    if args.single_only:
        run_single_agent_demo(data_dir=args.data_dir, print_fn=print)
    elif args.multi_only:
        run_multi_agent_ranking_demo(data_dir=args.data_dir, print_fn=print)
    else:
        run_full_demo(
            data_dir=args.data_dir,
            print_fn=print,
            skip_multi=False,
        )

    print("\nDemo complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())