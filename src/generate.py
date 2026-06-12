"""Ad + keyword generation from templates/ads_en.yaml and templates/keywords_en.yaml.

Output column structure matches data/reference/RSA_Example.xlsx exactly:
Ad group | Theme | Final URL | Headline 1-10 (no position columns) |
Headline 11-15 (each with position column) | Description 1-4 (each with
position column) | Path 1 | Path 2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.shorten import render_with_chain
from src.universe import Stock

log = logging.getLogger(__name__)

HEADLINE_LIMIT = 30
DESCRIPTION_LIMIT = 90
PATH_LIMIT = 15

UNPINNED = "--"

COLUMNS = (
    ["Ad group", "Theme", "Final URL"]
    + [f"Headline {i}" for i in range(1, 11)]
    + [c for i in range(11, 16) for c in (f"Headline {i}", f"Headline {i} position")]
    + [c for i in range(1, 5) for c in (f"Description {i}", f"Description {i} position")]
    + ["Path 1", "Path 2"]
)


@dataclass
class GeneratedAd:
    ad_group: str
    theme: str
    final_url: str
    headlines: list[str]  # 15 slots; "" = slot left empty by a dropped template
    descriptions: list[tuple[str, Any]]  # (text, position) — position int or "--"
    path1: str
    path2: str
    dropped: list[str] = field(default_factory=list)  # log lines about dropped assets


def load_ad_templates(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_keyword_templates(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def generate_ad(stock: Stock, templates: dict, final_url: str) -> GeneratedAd:
    """Render one RSA for a stock: brand block (1-4), stock block (5-10), proof block (11-15)."""
    h = templates["headlines"]
    dropped: list[str] = []

    brand: list[str] = list(h["brand"])
    proof: list[str] = list(h["proof"])

    stock_lines: list[str] = []
    seen = {s.lower() for s in brand + proof}
    for template in h["stock"]:
        text = render_with_chain(template, stock, HEADLINE_LIMIT)
        if text is None:
            dropped.append(f"{stock.ticker}: headline template {template!r} dropped — "
                           f"even ticker exceeds {HEADLINE_LIMIT} chars")
            continue
        if text.lower() in seen:
            dropped.append(f"{stock.ticker}: headline {text!r} dropped — duplicate within ad")
            continue
        seen.add(text.lower())
        stock_lines.append(text)

    headlines = brand + stock_lines + [""] * (6 - len(stock_lines)) + proof

    descriptions: list[tuple[str, Any]] = []
    for d in templates["descriptions"]:
        text = render_with_chain(d["text"], stock, DESCRIPTION_LIMIT)
        if text is None:
            dropped.append(f"{stock.ticker}: description template {d['text']!r} dropped — "
                           f"even ticker exceeds {DESCRIPTION_LIMIT} chars")
            continue
        descriptions.append((text, d["position"]))

    path1 = templates["paths"]["path1"]
    path2 = templates["paths"]["path2"].format(slug=stock.slug, ticker=stock.ticker)
    if len(path2) > PATH_LIMIT:
        fallback = stock.ticker.lower()
        dropped.append(f"{stock.ticker}: path2 {path2!r} exceeds {PATH_LIMIT} chars — "
                       f"falling back to ticker {fallback!r}")
        path2 = fallback

    for line in dropped:
        log.warning("%s", line)

    return GeneratedAd(
        ad_group=stock.short_name,
        theme=stock.short_name,
        final_url=final_url,
        headlines=headlines,
        descriptions=descriptions,
        path1=path1,
        path2=path2,
        dropped=dropped,
    )


def generate_keywords(stock: Stock, templates: dict) -> list[dict[str, str]]:
    """Render keyword patterns x match types; duplicates (e.g. AMD/amd) removed."""
    rendered: list[str] = []
    for pattern in templates["patterns"]:
        kw = pattern.format(name_lower=stock.short_name.lower(),
                            ticker_lower=stock.ticker.lower())
        if kw not in rendered:
            rendered.append(kw)
    return [
        {"Ad group": stock.short_name, "Keyword": kw, "Match type": match_type}
        for kw in rendered
        for match_type in templates["match_types"]
    ]


def ads_to_dataframe(ads: list[GeneratedAd]) -> pd.DataFrame:
    rows = []
    for ad in ads:
        row: dict[str, Any] = {"Ad group": ad.ad_group, "Theme": ad.theme, "Final URL": ad.final_url}
        for i in range(10):
            row[f"Headline {i + 1}"] = ad.headlines[i]
        for i in range(10, 15):
            row[f"Headline {i + 1}"] = ad.headlines[i]
            row[f"Headline {i + 1} position"] = UNPINNED if ad.headlines[i] else ""
        for i in range(4):
            if i < len(ad.descriptions):
                text, position = ad.descriptions[i]
            else:
                text, position = "", ""
            row[f"Description {i + 1}"] = text
            row[f"Description {i + 1} position"] = position
        row["Path 1"] = ad.path1
        row["Path 2"] = ad.path2
        rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS)


def write_import_files(run_dir: str | Path, ads: list[GeneratedAd],
                       keyword_rows: list[dict[str, str]], kw_templates: dict) -> list[Path]:
    """Write ads_import.csv/.xlsx, keywords_import.csv, negatives.csv. Returns paths."""
    run_dir = Path(run_dir)
    df = ads_to_dataframe(ads)

    ads_csv = run_dir / "ads_import.csv"
    ads_xlsx = run_dir / "ads_import.xlsx"
    kw_csv = run_dir / "keywords_import.csv"
    neg_csv = run_dir / "negatives.csv"

    df.to_csv(ads_csv, index=False)
    df.to_excel(ads_xlsx, index=False, sheet_name="Sheet1")
    pd.DataFrame(keyword_rows, columns=["Ad group", "Keyword", "Match type"]).to_csv(kw_csv, index=False)
    negative_match = kw_templates.get("negative_match_type", "Phrase")
    pd.DataFrame(
        [{"Keyword": kw, "Match type": negative_match} for kw in kw_templates.get("negatives", [])],
        columns=["Keyword", "Match type"],
    ).to_csv(neg_csv, index=False)

    return [ads_csv, ads_xlsx, kw_csv, neg_csv]
