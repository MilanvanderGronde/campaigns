"""PytrendsProvider — Milestone 4 (not yet implemented).

Will use the unofficial pytrends library with: max 5 terms per request,
2-5s jittered sleeps, one retry on 429 then skip-and-log, and a 12h JSON
cache under cache/trends/. The pipeline must degrade to ManualProvider if
this provider fails entirely.
"""

from __future__ import annotations

from src.providers.base import TrendScore, TrendsProvider


class PytrendsProvider(TrendsProvider):
    name = "pytrends"

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("PytrendsProvider arrives in Milestone 4.")

    def get_scores(self, terms: list[str], timeframe: str = "now 7-d") -> dict[str, TrendScore]:
        raise NotImplementedError("PytrendsProvider arrives in Milestone 4.")
