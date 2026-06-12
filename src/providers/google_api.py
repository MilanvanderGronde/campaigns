"""GoogleTrendsApiProvider — stub until Google Trends Alpha API access lands.

Milestone 5 fleshes out this docstring and adds UPGRADING.md. When access is
granted, only this file changes: implement auth, the endpoint call, and the
mapping from API response to TrendScore.
"""

from __future__ import annotations

from src.providers.base import TrendScore, TrendsProvider


class GoogleTrendsApiProvider(TrendsProvider):
    name = "google_api"

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Google Trends Alpha API access not yet granted.")

    def get_scores(self, terms: list[str], timeframe: str = "now 7-d") -> dict[str, TrendScore]:
        raise NotImplementedError("Google Trends Alpha API access not yet granted.")
