"""Load and validate data/stock_universe.csv. Fails loudly with row numbers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

SHORT_NAME_MAX = 20
REQUIRED_COLUMNS = ["ticker", "company_name", "short_name", "exchange", "search_terms", "slug", "active"]


class UniverseError(ValueError):
    """Raised when stock_universe.csv fails validation."""


@dataclass(frozen=True)
class Stock:
    ticker: str
    company_name: str
    short_name: str
    exchange: str
    search_terms: tuple[str, ...]  # first term is primary
    slug: str
    active: bool


def load_universe(path: str | Path) -> list[Stock]:
    path = Path(path)
    if not path.exists():
        raise UniverseError(f"Universe file not found: {path}")

    df = pd.read_csv(path, dtype=str).fillna("")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise UniverseError(f"{path}: missing columns {missing}")

    errors: list[str] = []
    seen: dict[str, int] = {}
    stocks: list[Stock] = []

    for idx, row in df.iterrows():
        line = idx + 2  # 1-based, +1 for header — matches the file as opened in an editor
        ticker = row["ticker"].strip()
        short_name = row["short_name"].strip()
        terms = tuple(t.strip() for t in row["search_terms"].split("|") if t.strip())

        if not ticker:
            errors.append(f"line {line}: empty ticker")
        elif ticker != ticker.upper():
            errors.append(f"line {line}: ticker {ticker!r} must be uppercase")
        elif ticker in seen:
            errors.append(f"line {line}: duplicate ticker {ticker!r} (first seen line {seen[ticker]})")
        else:
            seen[ticker] = line
        if not short_name:
            errors.append(f"line {line}: empty short_name")
        elif len(short_name) > SHORT_NAME_MAX:
            errors.append(f"line {line}: short_name {short_name!r} is {len(short_name)} chars (max {SHORT_NAME_MAX})")
        if not terms:
            errors.append(f"line {line}: empty search_terms")

        stocks.append(Stock(
            ticker=ticker,
            company_name=row["company_name"].strip(),
            short_name=short_name,
            exchange=row["exchange"].strip(),
            search_terms=terms,
            slug=row["slug"].strip(),
            active=row["active"].strip().lower() in ("true", "1", "yes"),
        ))

    if errors:
        raise UniverseError(f"{path} failed validation:\n  " + "\n  ".join(errors))
    return stocks


def active_stocks(stocks: list[Stock]) -> list[Stock]:
    return [s for s in stocks if s.active]
