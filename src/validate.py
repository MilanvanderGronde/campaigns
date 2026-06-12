"""Char-limit and compliance lint gate — the final check on every rendered asset.

Hard failures (build fails, no import files written):
  - any asset over its char limit
  - duplicate headlines/descriptions within an ad
  - missing/unpinned risk disclaimer (Description 1, position 1)
  - `guaranteed` / `risk-free` anywhere
Everything else that trips the lint is a warning, reported per-asset in
run_log.txt (and the HTML report from Milestone 3) for compliance review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.generate import DESCRIPTION_LIMIT, HEADLINE_LIMIT, PATH_LIMIT, GeneratedAd

DISCLAIMER = "Investing involves risk of loss. This is not investment advice."
KEYWORD_LIMIT = 80  # Google Ads keyword length cap

# Rule 2 — performance/return figures.
PERFORMANCE_PATTERNS = (
    re.compile(r"%\s*(returns?|yields?|gains?)\b", re.I),
    re.compile(r"\d\s*%?\s*(returns?|profits?|gains?|yields?)\b", re.I),
    re.compile(r"\b(returns?|profits?|earn(s|ed|ings)?)\b[^a-z0-9]{0,3}\d", re.I),
)
# Rule 3 — superlatives (exempt for exact-string whitelisted assets).
SUPERLATIVE_PATTERN = re.compile(
    r"(\#1\b|\b(best|top|leading|cheapest|guaranteed)\b|\bsafe investment\b|\brisk[- ]free\b)", re.I)
# Rule 4 — implied advice / prediction.
ADVICE_PATTERN = re.compile(
    r"\b(will rise|set to soar|expected to|target price|buy now before)\b", re.I)
# Hard subset of rule 3.
HARD_PATTERN = re.compile(r"\b(guaranteed|risk[- ]free)\b", re.I)


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_approved_claims(path: str | Path) -> set[str]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return set(data.get("approved", []))


def validate_ads(ads: list[GeneratedAd], approved: set[str]) -> ValidationResult:
    result = ValidationResult()
    for ad in ads:
        _validate_ad(ad, approved, result)
    return result


def _validate_ad(ad: GeneratedAd, approved: set[str], r: ValidationResult) -> None:
    tag = f"[{ad.ad_group}]"

    headlines = [h for h in ad.headlines if h]
    if len(ad.headlines) != 15:
        r.errors.append(f"{tag} expected 15 headline slots, got {len(ad.headlines)}")
    if len(headlines) < 15:
        r.warnings.append(f"{tag} only {len(headlines)}/15 headlines rendered "
                          f"(templates dropped by the shortening chain)")

    for i, h in enumerate(ad.headlines, 1):
        if len(h) > HEADLINE_LIMIT:
            r.errors.append(f"{tag} Headline {i} over {HEADLINE_LIMIT} chars ({len(h)}): {h!r}")
    seen: dict[str, int] = {}
    for i, h in enumerate(ad.headlines, 1):
        if h and h.lower() in seen:
            r.errors.append(f"{tag} duplicate headline (slots {seen[h.lower()]} and {i}): {h!r}")
        elif h:
            seen[h.lower()] = i

    if len(ad.descriptions) != 4:
        r.errors.append(f"{tag} expected exactly 4 descriptions, got {len(ad.descriptions)}")
    for i, (text, _) in enumerate(ad.descriptions, 1):
        if len(text) > DESCRIPTION_LIMIT:
            r.errors.append(f"{tag} Description {i} over {DESCRIPTION_LIMIT} chars ({len(text)}): {text!r}")
    desc_seen: dict[str, int] = {}
    for i, (text, _) in enumerate(ad.descriptions, 1):
        if text and text.lower() in desc_seen:
            r.errors.append(f"{tag} duplicate description (slots {desc_seen[text.lower()]} and {i}): {text!r}")
        elif text:
            desc_seen[text.lower()] = i

    # Rule 1 — mandatory risk disclaimer: Description 1, pinned to position 1.
    if not ad.descriptions or ad.descriptions[0][0] != DISCLAIMER:
        r.errors.append(f"{tag} HARD FAIL: Description 1 is not the risk disclaimer")
    elif str(ad.descriptions[0][1]) != "1":
        r.errors.append(f"{tag} HARD FAIL: risk disclaimer present but not pinned to position 1 "
                        f"(position={ad.descriptions[0][1]!r})")

    for label, text in (
        [(f"Headline {i}", h) for i, h in enumerate(ad.headlines, 1) if h]
        + [(f"Description {i}", t) for i, (t, _) in enumerate(ad.descriptions, 1) if t]
    ):
        _lint_asset(f"{tag} {label}", text, approved, r)

    if len(ad.path1) > PATH_LIMIT:
        r.errors.append(f"{tag} Path 1 over {PATH_LIMIT} chars: {ad.path1!r}")
    if len(ad.path2) > PATH_LIMIT:
        r.errors.append(f"{tag} Path 2 over {PATH_LIMIT} chars: {ad.path2!r}")
    if not ad.final_url:
        r.errors.append(f"{tag} missing Final URL")


def _lint_asset(label: str, text: str, approved: set[str], r: ValidationResult) -> None:
    if HARD_PATTERN.search(text):
        r.errors.append(f"{label} HARD FAIL: contains guaranteed/risk-free: {text!r}")
        return
    for pattern in PERFORMANCE_PATTERNS:
        if pattern.search(text):
            r.warnings.append(f"{label} lint (performance figure) -> compliance review: {text!r}")
            break
    if text not in approved and SUPERLATIVE_PATTERN.search(text):
        r.warnings.append(f"{label} lint (superlative, not whitelisted) -> compliance review: {text!r}")
    if ADVICE_PATTERN.search(text):
        r.warnings.append(f"{label} lint (implied advice/prediction) -> compliance review: {text!r}")


def validate_keywords(keyword_rows: list[dict[str, str]]) -> ValidationResult:
    result = ValidationResult()
    for row in keyword_rows:
        kw = row["Keyword"]
        if len(kw) > KEYWORD_LIMIT:
            result.errors.append(f"[{row['Ad group']}] keyword over {KEYWORD_LIMIT} chars: {kw!r}")
    return result
