"""Resolve data/live_adgroups.txt against the universe — candidates minus live.

Matching is forgiving: normalized case, intent words stripped, matched on
ticker OR short_name OR fuzzy company name (difflib ratio >= 0.85).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.matching import contains_word, fuzzy_match, normalize
from src.universe import Stock

log = logging.getLogger(__name__)


@dataclass
class ResolvedLine:
    line: str
    ticker: str
    matched_on: str  # ticker | short_name | company_name


def resolve_live_adgroups(path: str | Path, stocks: list[Stock]
                          ) -> tuple[set[str], list[ResolvedLine], list[str]]:
    """Returns (live tickers, resolved lines, unmatched lines)."""
    path = Path(path)
    resolved: list[ResolvedLine] = []
    unmatched: list[str] = []

    if not path.exists():
        log.warning("Live ad groups file not found: %s — treating all candidates as new.", path)
        return set(), resolved, unmatched

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _resolve_line(line, stocks)
        if match:
            resolved.append(ResolvedLine(line=line, ticker=match[0], matched_on=match[1]))
        else:
            unmatched.append(line)

    return {r.ticker for r in resolved}, resolved, unmatched


def _resolve_line(line: str, stocks: list[Stock]) -> tuple[str, str] | None:
    norm = normalize(line)
    if not norm:
        return None
    # Exact signals first so e.g. "META" never fuzzy-matches another name.
    for stock in stocks:
        if norm == stock.ticker.lower():
            return stock.ticker, "ticker"
    for stock in stocks:
        if norm == normalize(stock.short_name):
            return stock.ticker, "short_name"
    for stock in stocks:
        short_norm = normalize(stock.short_name)
        if contains_word(norm, short_norm) or contains_word(short_norm, norm):
            return stock.ticker, "short_name"
    for stock in stocks:
        if fuzzy_match(norm, normalize(stock.company_name)):
            return stock.ticker, "company_name"
    return None
