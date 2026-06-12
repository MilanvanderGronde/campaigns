"""Provider factory — the only place concrete providers are imported.

Everything downstream resolves its provider through get_provider(), driven by
config.yaml (provider: manual | pytrends | google_api).
"""

from __future__ import annotations

import logging
from typing import Any

from src.providers.base import TrendScore, TrendsProvider

log = logging.getLogger(__name__)

PROVIDER_NAMES = ("manual", "pytrends", "google_api")


class PytrendsWithFallback(TrendsProvider):
    """Runs pytrends, but degrades to manual if it fails entirely —
    raises, or returns no usable score for ANY term. `name` reflects the
    provider that actually produced the scores (surfaced in the report)."""

    name = "pytrends"

    def __init__(self, primary: TrendsProvider, fallback: TrendsProvider):
        self.primary = primary
        self.fallback = fallback

    def get_scores(self, terms: list[str], timeframe: str = "now 7-d") -> dict[str, TrendScore]:
        try:
            scores = self.primary.get_scores(terms, timeframe=timeframe)
            if any(s.interest_now is not None for s in scores.values()):
                return scores
            log.warning("pytrends returned no usable score for any of %d terms — "
                        "falling back to manual.", len(terms))
        except Exception as exc:
            log.warning("pytrends failed entirely (%s: %s) — falling back to manual.",
                        type(exc).__name__, exc)
        self.name = f"{self.fallback.name} (pytrends fallback)"
        return self.fallback.get_scores(terms, timeframe=timeframe)


def get_provider(name: str, config: dict[str, Any]) -> TrendsProvider:
    """Resolve a provider by name. pytrends falls back to manual on total failure."""
    paths = config.get("paths", {})
    default_score = float(config.get("manual_default_score", 100))

    def _manual() -> TrendsProvider:
        from src.providers.manual import ManualProvider

        return ManualProvider(paths.get("manual_hot_list", "data/manual_hot_list.txt"),
                              default_score=default_score)

    if name == "manual":
        return _manual()

    if name == "pytrends":
        try:
            from src.providers.pytrends_provider import PytrendsProvider

            primary = PytrendsProvider(cache_dir=paths.get("cache_dir", "cache"))
        except Exception as exc:
            log.warning("pytrends provider unavailable (%s) — falling back to manual.", exc)
            return _manual()
        return PytrendsWithFallback(primary, _manual())

    if name == "google_api":
        from src.providers.google_api import GoogleTrendsApiProvider

        return GoogleTrendsApiProvider()

    raise ValueError(f"Unknown provider {name!r}; expected one of {PROVIDER_NAMES}.")


__all__ = ["TrendScore", "TrendsProvider", "get_provider", "PROVIDER_NAMES"]
