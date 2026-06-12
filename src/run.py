"""CLI entry point — orchestrates the pipeline.

Milestone 1 scope: universe -> provider scores -> diff against live ad groups
-> output/run_*/candidates.csv + run_log.txt. Ad/keyword generation, validation
and the HTML report attach here in Milestones 2-3.

Usage: python -m src.run [--provider NAME] [--threshold N] [--top N] [--config PATH]
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from src.diff import resolve_live_adgroups
from src.generate import (generate_ad, generate_keywords, load_ad_templates,
                          load_keyword_templates, write_import_files)
from src.providers import get_provider
from src.report import render_report
from src.scoring import score_universe
from src.universe import UniverseError, active_stocks, load_universe
from src.validate import load_approved_claims, validate_ads, validate_keywords

log = logging.getLogger("run")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DEGIRO stock trend -> ad group pipeline")
    p.add_argument("--config", default="config.yaml", help="path to config.yaml")
    p.add_argument("--provider", choices=("manual", "pytrends", "google_api"),
                   help="override config provider")
    p.add_argument("--threshold", type=float, help="override selection threshold")
    p.add_argument("--top", type=int, help="override max selected candidates")
    return p.parse_args(argv)


def setup_logging() -> logging.Handler:
    """Console logging plus a memory buffer that becomes run_log.txt."""
    fmt = logging.Formatter("%(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    buffer = logging.handlers.MemoryHandler(capacity=10_000, flushLevel=logging.CRITICAL)
    buffer.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[console, buffer])
    return buffer


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    buffer = setup_logging()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    paths = config["paths"]
    provider_name = args.provider or config.get("provider", "manual")
    threshold = args.threshold if args.threshold is not None else float(config.get("threshold", 50))
    top_n = args.top if args.top is not None else int(config.get("top_n", 20))
    timeframe = config.get("timeframe", "now 7-d")

    log.info("Run started %s | provider=%s threshold=%s top=%s timeframe=%s",
             datetime.now().strftime("%Y-%m-%d %H:%M"), provider_name, threshold, top_n, timeframe)

    try:
        stocks = active_stocks(load_universe(paths["universe"]))
    except UniverseError as exc:
        log.error("%s", exc)
        return 1
    log.info("Universe: %d active stocks.", len(stocks))

    provider = get_provider(provider_name, config)
    if provider.name != provider_name:
        log.warning("Provider fallback: requested %r, using %r.", provider_name, provider.name)

    candidates, no_signal = score_universe(stocks, provider, timeframe=timeframe)

    live_tickers, resolved, unmatched = resolve_live_adgroups(paths["live_adgroups"], stocks)
    print("\nLive ad group matches (verify these are right):")
    for r in resolved:
        print(f"  {r.line!r:30} -> {r.ticker} (via {r.matched_on})")
    if unmatched:
        print("Live ad group lines that matched NOTHING in the universe:")
        for line in unmatched:
            print(f"  {line!r}")
        log.warning("%d live ad group line(s) unmatched: %s", len(unmatched), ", ".join(unmatched))
    print()

    rows = []
    selected_count = 0
    for c in candidates:
        already_live = c.ticker in live_tickers
        selected = (not already_live) and c.score >= threshold and selected_count < top_n
        if selected:
            selected_count += 1
        rows.append({
            "ticker": c.ticker,
            "name": c.name,
            "score": c.score,
            "delta_pct": c.delta_pct,
            "already_live": already_live,
            "selected": selected,
        })

    run_dir = Path(paths.get("output_dir", "output")) / f"run_{datetime.now():%Y-%m-%d_%H%M}"
    run_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = run_dir / "candidates.csv"
    pd.DataFrame(rows, columns=["ticker", "name", "score", "delta_pct",
                                "already_live", "selected"]).to_csv(candidates_path, index=False)

    log.info("Candidates: %d | already live: %d | selected: %d (threshold=%s, top=%s)",
             len(rows), sum(r["already_live"] for r in rows), selected_count, threshold, top_n)
    if no_signal:
        log.info("Terms with no signal/failed: %d", len(no_signal))
    log.info("Wrote %s", candidates_path)

    # Milestone 2: generate ads + keywords for selected stocks, gated by the validator.
    build_failed = False
    ads, keyword_rows = [], []
    validation_errors: list[str] = []
    validation_warnings: list[str] = []
    stock_by_ticker = {s.ticker: s for s in stocks}
    selected_stocks = [stock_by_ticker[r["ticker"]] for r in rows if r["selected"]]
    if selected_stocks:
        ad_templates = load_ad_templates(paths.get("ads_template", "templates/ads_en.yaml"))
        kw_templates = load_keyword_templates(paths.get("keywords_template", "templates/keywords_en.yaml"))
        approved = load_approved_claims(paths.get("approved_claims", "templates/approved_claims.yaml"))
        url_pattern = config.get("final_url_pattern")
        default_url = config.get("final_url", "")

        for stock in selected_stocks:
            final_url = url_pattern.format(slug=stock.slug) if url_pattern else default_url
            ads.append(generate_ad(stock, ad_templates, final_url))
            keyword_rows.extend(generate_keywords(stock, kw_templates))

        result = validate_ads(ads, approved)
        kw_result = validate_keywords(keyword_rows)
        validation_errors = result.errors + kw_result.errors
        validation_warnings = result.warnings + kw_result.warnings
        for w in validation_warnings:
            log.warning("validate: %s", w)
        if validation_errors:
            for e in validation_errors:
                log.error("validate: %s", e)
            log.error("BUILD FAILED: %d validation error(s) — import files NOT written.",
                      len(validation_errors))
            build_failed = True
        else:
            for written in write_import_files(run_dir, ads, keyword_rows, kw_templates):
                log.info("Wrote %s", written)
    else:
        log.info("No stocks selected — skipping ad/keyword generation.")

    # Milestone 3: insights.html (rendered even on build failure, so the
    # operator can see what tripped the validator).
    cand_by_ticker = {c.ticker: c for c in candidates}
    cards = []
    for ad, stock in zip(ads, selected_stocks):
        cand = cand_by_ticker[stock.ticker]
        prefix = f"[{ad.ad_group}]"
        cards.append({
            "ad_group": ad.ad_group, "ticker": stock.ticker,
            "score": cand.score, "delta_pct": cand.delta_pct, "best_term": cand.best_term,
            "final_url": ad.final_url, "path1": ad.path1, "path2": ad.path2,
            "headlines": [{"slot": i, "text": h, "chars": len(h), "limit": 30,
                           "position": "--" if (h and i >= 11) else ""}
                          for i, h in enumerate(ad.headlines, 1)],
            "descriptions": [{"slot": i, "text": t, "chars": len(t), "limit": 90, "position": p}
                             for i, (t, p) in enumerate(ad.descriptions, 1)],
            "keywords": sorted({k["Keyword"] for k in keyword_rows if k["Ad group"] == ad.ad_group}),
            "warnings": [w for w in validation_warnings if w.startswith(prefix)],
            "dropped": ad.dropped,
        })
    report_path = render_report(run_dir / "insights.html", {
        "date": f"{datetime.now():%Y-%m-%d %H:%M}",
        "provider_requested": provider_name,
        "provider_used": provider.name,
        "universe_size": len(stocks),
        "n_live": sum(r["already_live"] for r in rows),
        "n_selected": selected_count,
        "threshold": threshold,
        "candidates": rows,
        "cards": cards,
        "errors": validation_errors,
        "unmatched": unmatched,
        "no_signal": no_signal,
    })
    log.info("Wrote %s", report_path)

    run_log_lines = [
        f"run: {datetime.now():%Y-%m-%d %H:%M}",
        f"provider requested: {provider_name} | provider used: {provider.name}",
        f"universe: {len(stocks)} active stocks",
        f"candidates: {len(rows)} | selected: {selected_count} | threshold: {threshold} | top_n: {top_n}",
        "",
        "live ad group matches:",
        *[f"  {r.line!r} -> {r.ticker} (via {r.matched_on})" for r in resolved],
        "unmatched live ad group lines:",
        *([f"  {line!r}" for line in unmatched] or ["  (none)"]),
        "",
        "terms with no signal / failed:",
        *([f"  {t}" for t in no_signal] or ["  (none)"]),
        "",
        "log:",
        *["  " + buffer.format(rec) for rec in buffer.buffer],
    ]
    (run_dir / "run_log.txt").write_text("\n".join(run_log_lines) + "\n", encoding="utf-8")

    if build_failed:
        print(f"BUILD FAILED — see {run_dir}/run_log.txt")
        return 1
    print(f"Done. Output in {run_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
