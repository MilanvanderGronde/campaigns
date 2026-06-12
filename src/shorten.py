"""Name-shortening fallback chain.

Every template renders with the LONGEST variant that fits its char limit:
  1. company_name with legal suffixes stripped
  2. short_name
  3. ticker
If even the ticker doesn't fit, the template is dropped for that stock
(never truncate mid-word, never emit an over-limit asset).
"""

from __future__ import annotations

import logging

from src.universe import Stock

log = logging.getLogger(__name__)

# Spec list plus " Holding", " A/S", " Company", " Incorporated" — common on
# names in the seeded universe (ASML Holding N.V., Novo Nordisk A/S, The
# Coca-Cola Company). Checked end-of-string, case-insensitive, iteratively,
# with any preceding comma removed ("Tesla, Inc." -> "Tesla").
LEGAL_SUFFIXES = (
    " inc.", " inc", " corp.", " corp", " corporation", " incorporated",
    " plc", " n.v.", " se", " ag", " s.a.", " ltd.", " ltd",
    " holdings", " holding", " a/s", " company", " co.",
)


def strip_legal_suffixes(name: str) -> str:
    name = name.strip()
    if name.lower().startswith("the ") and len(name) > 4:
        name = name[4:]
    changed = True
    while changed:
        changed = False
        low = name.lower()
        for suffix in LEGAL_SUFFIXES:
            if low.endswith(suffix):
                name = name[: len(name) - len(suffix)].rstrip(" ,")
                changed = True
                break
    return name


def name_variants(stock: Stock) -> list[str]:
    """Ordered longest-preferred variants, deduplicated."""
    variants = [strip_legal_suffixes(stock.company_name), stock.short_name, stock.ticker]
    out: list[str] = []
    for v in variants:
        if v and v not in out:
            out.append(v)
    return out


def render_with_chain(template: str, stock: Stock, limit: int) -> str | None:
    """Render with the longest name variant that fits; None if none fits."""
    for variant in name_variants(stock):
        text = template.format(name=variant, ticker=stock.ticker, slug=stock.slug)
        if len(text) <= limit:
            return text
        if "{name}" not in template:
            break  # no variant changes the output; it simply doesn't fit
    return None
