# DEGIRO — Stock Trend → Ad Group Pipeline

## What this project is

A pipeline that (1) identifies single-company stocks currently in demand using search-trend signals, (2) diffs them against the stock ad groups already live in Google Ads, and (3) generates ready-to-import ad copy and keywords for the gaps — output as CSV for Google Ads Editor plus an HTML insights report. Phase 2 adds markdown landing pages per stock.

The operator is a Google Ads marketer at DEGIRO (online broker). They have **no access to internal demand data** — all signals must come from public sources. Ads are **English only** for now. The list of currently live ad groups is provided **manually** (pasted into a file).

## Core design decision: pluggable trend providers

Google Trends has no stable official API yet (the operator has requested access to the Alpha API). Therefore: **all trend data flows through a single `TrendsProvider` interface.** Implementations are swappable; nothing downstream may import a provider directly.

```python
class TrendsProvider(ABC):
    def get_scores(self, terms: list[str], timeframe: str = "now 7-d") -> dict[str, TrendScore]:
        """Return a TrendScore per term. Must never raise on a single bad term —
        return score=None for failures and keep going."""
```

`TrendScore` fields: `term`, `interest_now` (0–100), `interest_baseline` (avg of prior period), `delta_pct`, `rising_related_queries` (list, may be empty), `fetched_at`, `source`.

Providers to implement, in this order:

1. **`ManualProvider`** — reads `data/manual_hot_list.txt` (one stock name or ticker per line, optional `,score` suffix). Always works. This is the fallback and the first thing built, so the pipeline is end-to-end testable on day one.
2. **`PytrendsProvider`** — uses the `pytrends` library (unofficial). Constraints to respect: max 5 terms per request, sleep 2–5s between requests with jitter, retry once on 429 then skip and log. Cache responses to `cache/trends/{term}_{timeframe}.json` with a 12h TTL so re-runs don't re-fetch. Wrap everything in try/except — this library breaks; the pipeline must degrade, not die.
3. **`GoogleTrendsApiProvider`** — **stub now, implement when Alpha access arrives.** Create the class with the correct interface, a `NotImplementedError` body, and a docstring describing what to fill in (auth, endpoint, mapping response → `TrendScore`). When access is granted, only this file changes.
4. *(Optional, later)* `YahooTrendingProvider` — scrape Yahoo Finance trending tickers as a discovery signal (stocks *outside* the universe worth adding to it). Nice-to-have; do not block on it.

Provider selection via `config.yaml` (`provider: manual | pytrends | google_api`), with `pytrends` allowed to silently fall back to `manual` if it fails entirely.

## Repository structure

```
degiro-stock-ads/
├── PROJECT.md                  # this file
├── config.yaml                 # provider choice, thresholds, paths, brand name
├── data/
│   ├── stock_universe.csv      # the curated universe (see schema)
│   ├── live_adgroups.txt       # operator-pasted list of live stock ad groups
│   ├── manual_hot_list.txt     # fallback/manual trend input
│   └── reference/RSA_Example.xlsx  # operator's golden example (upload at project start)
├── templates/
│   ├── ads_en.yaml             # RSA headline/description templates
│   └── keywords_en.yaml        # keyword pattern templates
├── src/
│   ├── providers/              # base.py + one file per provider
│   ├── universe.py             # load/validate stock_universe.csv
│   ├── scoring.py              # provider scores → ranked candidates
│   ├── diff.py                 # candidates minus live ad groups
│   ├── generate.py             # ads + keywords from templates
│   ├── shorten.py              # name-shortening fallback chain
│   ├── validate.py             # char limits + compliance lint
│   ├── report.py               # insights.html
│   └── run.py                  # CLI entry point, orchestrates everything
├── cache/                      # gitignored
└── output/                     # gitignored; one timestamped folder per run
```

Python 3.11+, dependencies kept minimal: `pandas`, `pyyaml`, `jinja2` (HTML report), `pytrends` (optional import — pipeline must run without it installed).

## Data schemas

### `data/stock_universe.csv`
The curated universe: ~100–300 stocks tradable on DEGIRO, seeded initially with well-known US + EU large caps and meme-prone names. The operator extends it over time.

| column | example | notes |
|---|---|---|
| `ticker` | `NVDA` | uppercase, unique key |
| `company_name` | `NVIDIA Corporation` | full legal-ish name |
| `short_name` | `NVIDIA` | the name people actually search; **must be ≤ 20 chars** so templates fit |
| `exchange` | `NASDAQ` | informational |
| `search_terms` | `nvidia stock\|nvda stock` | pipe-separated terms sent to the trend provider; first term is primary |
| `slug` | `nvidia` | for landing-page URLs, lowercase-hyphenated |
| `active` | `true` | allows soft-removal without deleting rows |

`universe.py` validates on load: unique tickers, `short_name` ≤ 20 chars, no empty `search_terms`. Fail loudly with row numbers.

### `data/live_adgroups.txt`
One entry per line, free-form (the operator pastes from memory or from Editor). Matching against the universe must be forgiving: normalize case, strip "stock"/"shares"/"buy", match on ticker OR short_name OR fuzzy company name (e.g. `difflib` ratio ≥ 0.85). Print the resolved matches at run time so the operator can spot bad matches, and list any lines that matched nothing.

### Run output (`output/run_YYYY-MM-DD_HHMM/`)
- `candidates.csv` — ranked: ticker, name, score, delta_pct, already_live (bool), selected (bool, = not live and score ≥ threshold)
- `ads_import.csv` — Google Ads Editor format (below)
- `keywords_import.csv` — Google Ads Editor format (below)
- `insights.html` — human-readable report
- `run_log.txt` — provider used, fallbacks triggered, terms that failed, validation warnings

## Ad & keyword generation

### RSA hard limits (validate, never trust the template)
- Headlines: **30 chars** max, exactly **15 per ad** in the fixed structure below
- Descriptions: **90 chars** max, exactly 4
- Path 1 / Path 2: **15 chars** each
- No duplicate headlines/descriptions within an ad

### Name shortening — the fallback chain
Every template renders with the **longest variant that fits**:

1. `company_name` with legal suffixes stripped (` Inc.`, ` Corp.`, ` Corporation`, ` PLC`, ` N.V.`, ` SE`, ` AG`, ` S.A.`, ` Ltd.`, ` Holdings` — case-insensitive, end-of-string)
2. `short_name`
3. `ticker`

If even the ticker doesn't fit a given template, **drop that template for that stock** and log it — never truncate mid-word, never emit an over-limit asset. `validate.py` re-checks every rendered asset against the hard limits as a final gate; a limit violation is a build failure, not a warning.

### `templates/ads_en.yaml` — based on `RSA_Example.xlsx` (the operator's reference file — commit it to `data/reference/`)
Placeholders: `{name}` (runs the fallback chain), `{ticker}`, `{slug}`. Every ad has exactly 15 headlines in three fixed blocks:

**Block A — brand headlines (slots 1–4, fixed strings, pre-approved):**
```
DEGIRO: Everyone's an investor
Start investing with DEGIRO
DEGIRO: Enjoy low fees
DEGIRO: Financial power to you
```

**Block B — stock-specific headlines (slots 5–10, templated):**
```
Invest in {name} with DEGIRO      # fixed part = 22 chars → name must be ≤ 8, expect ticker fallback often
Buy {name} shares                 # name ≤ 19
Buy {name} stock                  # name ≤ 20
Invest in {name} stock            # name ≤ 14
DEGIRO: {name} Shares             # name ≤ 15
DEGIRO: {name} Stock              # name ≤ 16
```
Each template runs the shortening chain independently — one headline may use `NVIDIA` while another falls back to the ticker. The per-template name budgets above show why: short fixed parts tolerate long names, long fixed parts don't.

**Block C — proof points (slots 11–15, fixed strings, pre-approved, position column = `--`):**
```
100+ international awards
Very low trading fees
Invest with low costs
3M investors trust DEGIRO
Award-winning platform
```

**Descriptions (exactly 4):**
```
Investing involves risk of loss. This is not investment advice.    # PINNED: position 1
Start investing in {name} stock with low costs at DEGIRO.          # templated, position --
Open your account free and access 45+ markets in 30 countries.     # fixed, position --
See why 3M investors use our award-winning platform.               # fixed, position --
```
The **risk disclaimer is Description 1, pinned to position 1** — this is mandatory in every ad and a build failure if absent or unpinned.

Paths: Path 1 = `stocks`, Path 2 = `{slug}` (validate ≤ 15 chars; fall back to lowercased ticker if the slug is too long).

Final URL: from config `final_url`. Default per the example: `https://www.degiro.nl/lp/beleggen` (one generic LP for all ad groups). Support an optional `final_url_pattern` with `{slug}` for when per-stock landing pages exist (Phase 2).

### `templates/keywords_en.yaml` — starter set
Patterns rendered with `{name_lower}` (short_name lowercased) and `{ticker_lower}`:
```
{name_lower} stock
buy {name_lower} stock
{name_lower} shares
buy {name_lower} shares
{name_lower} share price
invest in {name_lower}
{ticker_lower} stock
buy {ticker_lower}
```
Match types: generate each pattern as **exact** and **phrase** (two rows). Include a shared negative list in the output (separate `negatives.csv`): `free`, `reddit`, `forecast`, `prediction`, `price target`, `should i buy` — terms that attract advice-seeking rather than trading intent. Operator-editable in the YAML.

### Output CSV format — matches `RSA_Example.xlsx` exactly
`ads_import.csv` (also write an `.xlsx` copy with the same sheet, since the operator works in Excel) — exact column order:

```
Ad group | Theme | Final URL |
Headline 1 … Headline 10 |                      (no position columns for slots 1–10)
Headline 11 | Headline 11 position | … | Headline 15 | Headline 15 position |
Description 1 | Description 1 position | … | Description 4 | Description 4 position |
Path 1 | Path 2
```

Conventions from the example:
- Position value is `--` for unpinned, a digit for pinned. Only `Description 1 position` = `1`; everything else `--`.
- `Ad group` = `short_name` only (e.g. `NVIDIA`, not `NVIDIA Stock`).
- `Theme` = `short_name` (used by the operator for organization).
- No `Campaign` column — the operator places ad groups into the right campaign in Editor/Excel themselves.

`keywords_import.csv` columns: `Ad group, Keyword, Match type` (`Exact` / `Phrase`), with `Ad group` matching the ads sheet exactly so the two files line up. `negatives.csv`: `Keyword, Match type`.

The reference file lives at `data/reference/RSA_Example.xlsx`; the generator's output for NVIDIA must reproduce that row byte-for-byte (modulo the trend-driven stock selection) — use it as the golden test in Milestone 2.

## Compliance guardrails (DEGIRO posture)

These stocks are direct equities, not funds, so the ESMA fund-marketing regime doesn't strictly apply — but DEGIRO's house rules do, and `validate.py` must lint every rendered asset:

1. **Risk disclaimer is mandatory**: every ad carries `Investing involves risk of loss. This is not investment advice.` as **Description 1, pinned to position 1**. Build fails if the text or the pin is missing.
2. **No performance or return figures** anywhere in templates or rendered output: lint for `%` followed by `return/yield/gain`, and for digits adjacent to `return`, `profit`, `earn`.
3. **No superlatives without substantiation**: lint for `best`, `top`, `#1`, `leading`, `cheapest`, `guaranteed`, `safe investment`, `risk-free` — **except** an exact-string whitelist of pre-approved brand assets (the Block A/C headlines and fixed descriptions above: `100+ international awards`, `3M investors trust DEGIRO`, `Award-winning platform`, `Very low trading fees`, etc.). The whitelist lives in `templates/approved_claims.yaml`; anything new that trips the lint goes to compliance, not into the output.
4. **No implied advice or prediction**: lint for `will rise`, `set to soar`, `expected to`, `target price`, `buy now before`.
5. **If a fund/ETF ever enters the universe** (ticker resolves to a UCITS/ETF), flag it and exclude it from generation — fund ads have a stricter regime and go through a separate compliance review.

Lint hits are reported per-asset in `run_log.txt` and the HTML report; hard rules (1, plus `guaranteed`/`risk-free`) fail the build.

## `insights.html` report

One self-contained HTML file (inline CSS, no external assets). Sections:
1. Run summary: date, provider used, universe size, candidates found, fallbacks triggered.
2. Ranked candidate table: ticker, name, score, delta vs baseline, already-live badge, selected badge.
3. Per-selected-stock card: trend score detail, the generated headlines/descriptions with live char counts, the keyword list, any lint warnings.
4. Skipped/failed terms and unmatched live-ad-group lines (operator hygiene list).

## Milestones — build in this order

Each milestone ends with something runnable. Do not start the next until the current one runs clean.

1. **Skeleton + manual end-to-end.** Repo structure, config, schemas, `ManualProvider`, scoring (trivial for manual), diff, and a `run.py` that produces `candidates.csv` from `manual_hot_list.txt` + `live_adgroups.txt`. Seed `stock_universe.csv` with ~40 well-known stocks to start.
2. **Generation + validation.** Templates, shortening chain, `ads_import.csv`/`.xlsx` + `keywords_import.csv`, full validator (char limits + compliance lint). **Golden test:** generating for NVIDIA must reproduce the row in `data/reference/RSA_Example.xlsx`. Then test the shortening chain with long names: `Taiwan Semiconductor Manufacturing Company` (must fall back to `TSMC`), `Berkshire Hathaway`, `LVMH Moët Hennessy Louis Vuitton`.
3. **HTML report.** `insights.html` as specified.
4. **Pytrends provider.** With caching, rate limiting, graceful fallback to manual. Accept that it may be flaky; the pipeline must finish regardless.
5. **Google API stub + docs.** `GoogleTrendsApiProvider` stub, plus a short `UPGRADING.md` explaining exactly what to implement when Alpha access lands.
6. **(Phase 2) Landing pages.** `templates/landing_en.md` — a markdown landing page template based on an example page the operator will supply (placeholder: hero with `{name}` + `{ticker}`, "How to buy {name} stock on DEGIRO" steps, fee section, risk disclaimer block, KID/document links section left as optional include). Generator writes one `output/.../landing/{slug}.md` per selected stock. **Do not start until the operator supplies the example page.**

## Operator workflow (the loop this enables)

1. Paste/refresh `live_adgroups.txt` and (if using manual mode) `manual_hot_list.txt`.
2. `python -m src.run` (flags: `--provider`, `--threshold`, `--top N`).
3. Open `insights.html`, sanity-check candidates and copy.
4. Import `ads_import.csv` + `keywords_import.csv` via Google Ads Editor, review, post.
5. After posting, add the new ad groups to `live_adgroups.txt` so the next run diffs correctly.

## Out of scope (for now)

- Direct Google Ads API write access (everything goes through Editor CSV on purpose — human review stays in the loop).
- Bid/budget logic, non-English markets, fund/ETF ad groups, automated scheduling.

## Open items for the operator (ask before assuming)

- Confirm `https://www.degiro.nl/lp/beleggen` is the Final URL to use for all new ad groups (it's a Dutch LP — for English ads, is there an EN equivalent?).
- Whether per-stock landing pages will get their own URL pattern in Phase 2.
- The example landing page for Phase 2.
- Any additional pre-approved claims for `approved_claims.yaml` beyond what's in `RSA_Example.xlsx`.
