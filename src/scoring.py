"""Turn provider TrendScores into ranked stock candidates."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.providers.base import TrendsProvider
from src.universe import Stock

log = logging.getLogger(__name__)


@dataclass
class Candidate:
    ticker: str
    name: str  # short_name
    score: float
    delta_pct: float | None
    best_term: str


def score_universe(stocks: list[Stock], provider: TrendsProvider,
                   timeframe: str = "now 7-d") -> tuple[list[Candidate], list[str]]:
    """Score every active stock; rank by score descending.

    A stock's score is the best interest_now across its search_terms.
    Stocks with no signal (all terms None) are not candidates.
    Returns (ranked candidates, terms with no signal/failed) for the run log.
    """
    all_terms: list[str] = []
    for stock in stocks:
        for term in stock.search_terms:
            if term not in all_terms:
                all_terms.append(term)

    scores = provider.get_scores(all_terms, timeframe=timeframe)

    candidates: list[Candidate] = []
    for stock in stocks:
        best = None
        for term in stock.search_terms:
            ts = scores.get(term)
            if ts is None or ts.interest_now is None:
                continue
            if best is None or ts.interest_now > best.interest_now:
                best = ts
        if best is not None:
            candidates.append(Candidate(
                ticker=stock.ticker,
                name=stock.short_name,
                score=best.interest_now,
                delta_pct=best.delta_pct,
                best_term=best.term,
            ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    no_signal = sorted(t for t in all_terms
                       if scores.get(t) is None or scores[t].interest_now is None)
    log.info("Scored %d terms across %d stocks — %d candidates with a signal.",
             len(all_terms), len(stocks), len(candidates))
    return candidates, no_signal
