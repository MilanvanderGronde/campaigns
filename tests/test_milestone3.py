"""Milestone 3 tests — insights.html rendering.

Run with:  python -m tests.test_milestone3   (also works under pytest)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from src.report import render_report


def _context(**overrides) -> dict:
    ctx = dict(
        date="2026-06-12 10:00",
        provider_requested="manual",
        provider_used="manual",
        universe_size=48,
        n_live=2,
        n_selected=1,
        threshold=50.0,
        candidates=[
            {"ticker": "PLTR", "name": "Palantir", "score": 92.0, "delta_pct": None,
             "already_live": False, "selected": True},
            {"ticker": "NVDA", "name": "NVIDIA", "score": 100.0, "delta_pct": 12.5,
             "already_live": True, "selected": False},
        ],
        cards=[{
            "ad_group": "Palantir", "ticker": "PLTR", "score": 92.0, "delta_pct": None,
            "best_term": "palantir stock", "final_url": "https://www.degiro.nl/lp/beleggen",
            "path1": "stocks", "path2": "palantir",
            "headlines": [{"slot": 1, "text": "DEGIRO: Everyone’s an investor",
                           "chars": 30, "limit": 30, "position": ""},
                          {"slot": 5, "text": "", "chars": 0, "limit": 30, "position": ""}],
            "descriptions": [{"slot": 1,
                              "text": "Investing involves risk of loss. This is not investment advice.",
                              "chars": 63, "limit": 90, "position": 1}],
            "keywords": ["palantir stock", "buy pltr"],
            "warnings": ["[Palantir] lint (superlative) -> compliance review: 'demo'"],
            "dropped": ["PLTR: headline template dropped — demo"],
        }],
        errors=[],
        unmatched=["Saab"],
        no_signal=["apple stock"],
    )
    ctx.update(overrides)
    return ctx


def _render(ctx) -> str:
    path = Path(tempfile.mkdtemp()) / "insights.html"
    render_report(path, ctx)
    return path.read_text(encoding="utf-8")


def test_report_sections_present():
    html = _render(_context())
    for needle in ("Run summary", "Ranked candidates", "Generated ads (1)",
                   "Operator hygiene", "SELECTED", "LIVE", "Saab",
                   "30/30", "63/90", "palantir stock", "compliance review",
                   "(dropped)", "+12%"):
        assert needle in html, f"missing in report: {needle!r}"
    assert "Build failed" not in html


def test_report_shows_validation_errors():
    html = _render(_context(errors=["[X] HARD FAIL: Description 1 is not the risk disclaimer"]))
    assert "Build failed" in html and "HARD FAIL" in html


def test_report_shows_provider_fallback():
    html = _render(_context(provider_requested="pytrends"))
    assert "Fallback triggered" in html


def test_report_is_self_contained():
    html = _render(_context())
    stripped = html.replace("https://www.degiro.nl/lp/beleggen", "")
    for marker in ("<script src", "<link rel", "url(", "@import"):
        assert marker not in stripped, f"external asset reference: {marker}"


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
