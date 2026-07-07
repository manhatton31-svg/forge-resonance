# Contributing to ForgeResonance

Thank you for your interest in ForgeResonance. This project is designed to be extended — you do not need to modify core modules to add agents, routes, or API handlers.

## Quick start

```bash
git clone https://github.com/manhatton31-svg/forge-resonance.git
cd forge-resonance
pip install -r requirements-dev.txt
python -m pytest tests/ -q
python -m demo
```

## How to contribute

1. **Fork** the repository and create a feature branch from `main`.
2. **Extend** using the patterns in [docs/extending.md](docs/extending.md) — prefer composition over modifying `core/`.
3. **Test** — add or update tests under `tests/`; all tests must pass (`python -m pytest tests/ -q`).
4. **Document** — update README, examples, or docs if your change affects public APIs or onboarding.
5. **Changelog** — add entries under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for user-facing changes.
6. **Pull request** — describe what changed, why, and how you verified it.

## Code style

- Match existing naming, imports, and module layout in the area you touch.
- Keep changes focused — one feature or fix per PR when possible.
- No secrets in code or commits; use `.env` (see `.env.example`).

## Reporting issues

Open a GitHub issue with:

- What you expected vs. what happened
- Steps to reproduce (commands, env vars, Python version)
- Relevant log output or test failures

## Versioning

ForgeResonance follows [Semantic Versioning](https://semver.org/). Release notes live in [CHANGELOG.md](CHANGELOG.md). Import the current version:

```python
from forge_resonance import __version__
```

## Questions

See [docs/getting-started.md](docs/getting-started.md) and [docs/architecture.md](docs/architecture.md) for design context.