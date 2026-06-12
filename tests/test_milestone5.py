"""Milestone 5 tests — Google Trends API stub behaves as documented.

Run with:  python -m tests.test_milestone5   (also works under pytest)
"""

from __future__ import annotations

import sys

import yaml

from src.providers import get_provider
from src.providers.base import TrendsProvider
from src.providers.google_api import GoogleTrendsApiProvider


def _config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_stub_raises_with_pointer_to_upgrading_doc():
    try:
        GoogleTrendsApiProvider()
    except NotImplementedError as exc:
        assert "UPGRADING.md" in str(exc)
    else:
        raise AssertionError("stub must raise NotImplementedError until implemented")


def test_factory_surfaces_stub_error_no_silent_fallback():
    """Unlike pytrends, google_api must NOT silently fall back to manual."""
    try:
        get_provider("google_api", _config())
    except NotImplementedError:
        pass
    else:
        raise AssertionError("factory must propagate the stub's NotImplementedError")


def test_stub_conforms_to_interface():
    assert issubclass(GoogleTrendsApiProvider, TrendsProvider)
    assert GoogleTrendsApiProvider.name == "google_api"


def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print(f"\n{failures} failure(s)" if failures else "\nAll tests passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
