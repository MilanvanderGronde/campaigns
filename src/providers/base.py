"""Provider interface — ALL trend data flows through TrendsProvider.

Nothing downstream of src/providers/ may import a concrete provider directly;
providers are resolved through the factory in src/providers/__init__.py, driven
by config.yaml.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TrendScore:
    """Trend signal for a single search term.

    ``interest_now`` is None when the term failed or produced no signal —
    providers must degrade per-term, never raise on a single bad term.
    """

    term: str
    interest_now: float | None
    interest_baseline: float | None = None
    delta_pct: float | None = None
    rising_related_queries: list[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""


class TrendsProvider(ABC):
    """Swappable trend-signal source."""

    name: str = "base"

    @abstractmethod
    def get_scores(self, terms: list[str], timeframe: str = "now 7-d") -> dict[str, TrendScore]:
        """Return a TrendScore per term, keyed by the term as passed in.

        Must never raise on a single bad term — return interest_now=None for
        failures and keep going.
        """
