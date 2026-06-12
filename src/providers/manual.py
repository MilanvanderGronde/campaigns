"""ManualProvider — reads data/manual_hot_list.txt.

One stock name or ticker per line, optional ",score" suffix (0-100).
Always works; this is the fallback provider and the end-to-end test path.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.matching import contains_word, fuzzy_match, normalize
from src.providers.base import TrendScore, TrendsProvider

log = logging.getLogger(__name__)


class ManualProvider(TrendsProvider):
    name = "manual"

    def __init__(self, hot_list_path: str | Path, default_score: float = 100.0):
        self.hot_list_path = Path(hot_list_path)
        self.default_score = default_score
        self.entries: list[tuple[str, str, float]] = []  # (raw, normalized, score)
        self._load()

    def _load(self) -> None:
        if not self.hot_list_path.exists():
            log.warning("Manual hot list not found: %s — no terms will score.", self.hot_list_path)
            return
        for lineno, raw_line in enumerate(self.hot_list_path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            raw, score = line, self.default_score
            if "," in line:
                head, _, tail = line.rpartition(",")
                try:
                    score = float(tail.strip())
                    raw = head.strip()
                except ValueError:
                    log.warning("manual_hot_list.txt line %d: bad score %r — using default %s.",
                                lineno, tail.strip(), self.default_score)
            norm = normalize(raw)
            if not norm:
                log.warning("manual_hot_list.txt line %d: empty after normalization, skipped.", lineno)
                continue
            self.entries.append((raw, norm, score))
        log.info("ManualProvider loaded %d hot-list entries from %s.", len(self.entries), self.hot_list_path)

    def _match_entry(self, term_norm: str) -> float | None:
        """Best score among hot-list entries matching this normalized term."""
        best: float | None = None
        for _, entry_norm, score in self.entries:
            hit = (
                term_norm == entry_norm
                or contains_word(term_norm, entry_norm)
                or contains_word(entry_norm, term_norm)
                or fuzzy_match(term_norm, entry_norm)
            )
            if hit and (best is None or score > best):
                best = score
        return best

    def get_scores(self, terms: list[str], timeframe: str = "now 7-d") -> dict[str, TrendScore]:
        out: dict[str, TrendScore] = {}
        for term in terms:
            try:
                score = self._match_entry(normalize(term))
            except Exception:
                log.exception("ManualProvider failed on term %r — scoring None.", term)
                score = None
            out[term] = TrendScore(term=term, interest_now=score, source=self.name)
        return out
