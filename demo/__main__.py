"""Allow ``python -m demo`` from the project root."""

from demo.run_demo import main

raise SystemExit(main())