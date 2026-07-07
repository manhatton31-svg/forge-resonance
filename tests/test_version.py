"""Tests for package versioning."""

from __future__ import annotations


def test_version_import() -> None:
    from forge_resonance import __version__, __version_info__

    assert __version__ == "0.1.0"
    assert __version_info__ == (0, 1, 0)


def test_api_service_version_matches_package() -> None:
    from api.runtime import SERVICE_VERSION
    from forge_resonance import __version__

    assert SERVICE_VERSION == __version__