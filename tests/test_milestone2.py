"""Milestone 2 tests — golden test against RSA_Example.xlsx, shortening chain,
and validator hard-failure gates.

Run with:  python -m tests.test_milestone2   (also works under pytest)
"""

from __future__ import annotations

import sys

import openpyxl
import yaml

from src.generate import (GeneratedAd, ads_to_dataframe, generate_ad,
                          generate_keywords, load_ad_templates,
                          load_keyword_templates)
from src.shorten import render_with_chain, strip_legal_suffixes
from src.universe import Stock, load_universe
from src.validate import DISCLAIMER, load_approved_claims, validate_ads

REFERENCE_XLSX = "data/reference/RSA_Example.xlsx"
ADS_TEMPLATE = "templates/ads_en.yaml"
KEYWORDS_TEMPLATE = "templates/keywords_en.yaml"
APPROVED_CLAIMS = "templates/approved_claims.yaml"
UNIVERSE = "data/stock_universe.csv"


def _stock(ticker: str) -> Stock:
    for s in load_universe(UNIVERSE):
        if s.ticker == ticker:
            return s
    raise AssertionError(f"{ticker} not in universe")


def _config_final_url() -> str:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["final_url"]


def test_golden_nvidia_matches_reference():
    """Generating for NVIDIA must reproduce the RSA_Example.xlsx row exactly."""
    wb = openpyxl.load_workbook(REFERENCE_XLSX)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    ref_header, ref_row = list(rows[0]), list(rows[1])

    ad = generate_ad(_stock("NVDA"), load_ad_templates(ADS_TEMPLATE), _config_final_url())
    df = ads_to_dataframe([ad])

    assert list(df.columns) == ref_header, (
        f"column mismatch:\n  generated: {list(df.columns)}\n  reference: {ref_header}")
    generated_row = list(df.iloc[0])
    for col, gen, ref in zip(ref_header, generated_row, ref_row):
        assert gen == ref, f"cell mismatch in {col!r}: generated {gen!r} != reference {ref!r}"
    assert not ad.dropped, f"NVIDIA must render all templates, dropped: {ad.dropped}"


def test_shortening_chain_long_names():
    templates = load_ad_templates(ADS_TEMPLATE)

    # Taiwan Semiconductor Manufacturing Company must fall back to TSMC.
    tsm = generate_ad(_stock("TSM"), templates, "https://example.com")
    assert "Invest in TSMC with DEGIRO" in tsm.headlines
    assert "Buy TSMC shares" in tsm.headlines
    assert all(len(h) <= 30 for h in tsm.headlines)

    # Berkshire Hathaway: long fixed parts force the ticker, short ones fit the name.
    brk = generate_ad(_stock("BRK.B"), templates, "https://example.com")
    assert "Buy Berkshire Hathaway shares" in brk.headlines  # 29 chars — name fits
    assert "Invest in BRK.B with DEGIRO" in brk.headlines    # 8-char budget — ticker
    assert all(len(h) <= 30 for h in brk.headlines)
    assert brk.path2 == "brk.b", "18-char slug must fall back to lowercased ticker"

    # LVMH Moët Hennessy Louis Vuitton must fall back to LVMH everywhere.
    mc = generate_ad(_stock("MC"), templates, "https://example.com")
    assert "Buy LVMH stock" in mc.headlines
    assert all("Moët" not in h for h in mc.headlines)
    assert all(len(h) <= 30 for h in mc.headlines)


def test_legal_suffix_stripping():
    assert strip_legal_suffixes("NVIDIA Corporation") == "NVIDIA"
    assert strip_legal_suffixes("Tesla, Inc.") == "Tesla"
    assert strip_legal_suffixes("AMC Entertainment Holdings, Inc.") == "AMC Entertainment"
    assert strip_legal_suffixes("Novo Nordisk A/S") == "Novo Nordisk"
    assert strip_legal_suffixes("The Walt Disney Company") == "Walt Disney"
    assert strip_legal_suffixes("ASML Holding N.V.") == "ASML"


def test_template_dropped_when_even_ticker_too_long():
    stock = Stock(ticker="VERYLONGTICKER", company_name="Some Extremely Long Company Name Inc.",
                  short_name="Long Name Co", exchange="X",
                  search_terms=("long stock",), slug="long", active=True)
    # "Invest in {name} with DEGIRO" leaves an 8-char budget; nothing fits.
    assert render_with_chain("Invest in {name} with DEGIRO", stock, 30) is None
    ad = generate_ad(stock, load_ad_templates(ADS_TEMPLATE), "https://example.com")
    assert any("dropped" in d for d in ad.dropped)
    assert ad.headlines[4:10].count("") >= 1  # block B has empty slot(s), never truncated
    assert all(len(h) <= 30 for h in ad.headlines)


def test_validator_hard_failures():
    approved = load_approved_claims(APPROVED_CLAIMS)
    templates = load_ad_templates(ADS_TEMPLATE)
    good = generate_ad(_stock("PLTR"), templates, "https://example.com")
    assert validate_ads([good], approved).ok

    # Missing disclaimer -> hard fail.
    bad = generate_ad(_stock("PLTR"), templates, "https://example.com")
    bad.descriptions[0] = ("Totally fine text.", 1)
    res = validate_ads([bad], approved)
    assert any("not the risk disclaimer" in e for e in res.errors)

    # Disclaimer present but unpinned -> hard fail.
    bad2 = generate_ad(_stock("PLTR"), templates, "https://example.com")
    bad2.descriptions[0] = (DISCLAIMER, "--")
    res = validate_ads([bad2], approved)
    assert any("not pinned to position 1" in e for e in res.errors)

    # Over-limit asset -> hard fail.
    bad3 = generate_ad(_stock("PLTR"), templates, "https://example.com")
    bad3.headlines[5] = "X" * 31
    res = validate_ads([bad3], approved)
    assert any("over 30 chars" in e for e in res.errors)

    # guaranteed / risk-free -> hard fail.
    bad4 = generate_ad(_stock("PLTR"), templates, "https://example.com")
    bad4.headlines[5] = "Guaranteed gains with DEGIRO"
    res = validate_ads([bad4], approved)
    assert any("HARD FAIL" in e and "guaranteed" in e.lower() for e in res.errors)

    # Non-whitelisted superlative -> warning (compliance review), not error.
    bad5 = generate_ad(_stock("PLTR"), templates, "https://example.com")
    bad5.headlines[5] = "The best broker for Palantir"
    res = validate_ads([bad5], approved)
    assert res.ok and any("superlative" in w for w in res.warnings)


def test_whitelisted_claims_pass_lint():
    approved = load_approved_claims(APPROVED_CLAIMS)
    ad = generate_ad(_stock("GME"), load_ad_templates(ADS_TEMPLATE), "https://example.com")
    res = validate_ads([ad], approved)
    assert res.ok, res.errors
    assert not res.warnings, res.warnings


def test_keywords_generation():
    kw_templates = load_keyword_templates(KEYWORDS_TEMPLATE)
    rows = generate_keywords(_stock("PLTR"), kw_templates)
    keywords = {(r["Keyword"], r["Match type"]) for r in rows}
    assert ("palantir stock", "Exact") in keywords
    assert ("palantir stock", "Phrase") in keywords
    assert ("buy pltr", "Exact") in keywords
    assert all(r["Ad group"] == "Palantir" for r in rows)
    assert len(rows) == len(keywords), "no duplicate keyword rows"

    # AMD: name_lower == ticker_lower, overlapping patterns must dedupe.
    amd_rows = generate_keywords(_stock("AMD"), kw_templates)
    amd_keywords = [r["Keyword"] for r in amd_rows if r["Match type"] == "Exact"]
    assert len(amd_keywords) == len(set(amd_keywords))


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
