"""PytrendsProvider — Google Trends via the unofficial pytrends library.

Constraints honoured (this library breaks; the pipeline degrades, never dies):
  - pytrends is an OPTIONAL import, resolved lazily in __init__ — if it isn't
    installed, construction raises and the factory falls back to manual
  - max 5 terms per request
  - 2-5s jittered sleep between requests
  - one retry on 429, then skip the batch and log
  - successful responses cached to cache/trends/{term}_{timeframe}.json, 12h TTL
  - any per-batch failure yields interest_now=None for those terms

Score derivation from interest_over_time (e.g. hourly points for "now 7-d"):
interest_now = mean of the most recent quarter of points, interest_baseline =
mean of the preceding points, delta_pct = relative change between the two.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from src.providers.base import TrendScore, TrendsProvider

log = logging.getLogger(__name__)

BATCH_SIZE = 5
CACHE_TTL = timedelta(hours=12)
SLEEP_RANGE = (2.0, 5.0)
RETRY_SLEEP = 30.0
MAX_RISING_QUERIES = 10


class PytrendsProvider(TrendsProvider):
    name = "pytrends"

    def __init__(self, cache_dir: str | Path = "cache", hl: str = "en-US", tz: int = 0,
                 sleep_range: tuple[float, float] = SLEEP_RANGE,
                 retry_sleep: float = RETRY_SLEEP,
                 sleep_fn: Callable[[float], None] = time.sleep):
        from pytrends.request import TrendReq  # optional dep — ImportError triggers factory fallback

        self.client = TrendReq(hl=hl, tz=tz)
        self.cache_dir = Path(cache_dir) / "trends"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.sleep_range = sleep_range
        self.retry_sleep = retry_sleep
        self.sleep_fn = sleep_fn

    # -- public ----------------------------------------------------------

    def get_scores(self, terms: list[str], timeframe: str = "now 7-d") -> dict[str, TrendScore]:
        out: dict[str, TrendScore] = {}
        to_fetch: list[str] = []
        for term in terms:
            cached = self._read_cache(term, timeframe)
            if cached is not None:
                out[term] = cached
            else:
                to_fetch.append(term)
        if to_fetch:
            log.info("pytrends: %d term(s) cached, fetching %d in batches of %d.",
                     len(out), len(to_fetch), BATCH_SIZE)

        for i in range(0, len(to_fetch), BATCH_SIZE):
            if i > 0:
                self.sleep_fn(random.uniform(*self.sleep_range))
            batch = to_fetch[i:i + BATCH_SIZE]
            out.update(self._fetch_batch(batch, timeframe))

        for term in terms:  # interface guarantee: a TrendScore per term, always
            out.setdefault(term, TrendScore(term=term, interest_now=None, source=self.name))
        return out

    # -- fetching ---------------------------------------------------------

    def _fetch_batch(self, batch: list[str], timeframe: str) -> dict[str, TrendScore]:
        for attempt in (1, 2):
            try:
                self.client.build_payload(batch, timeframe=timeframe)
                df = self.client.interest_over_time()
                rising = self._rising_queries(batch)
                return {t: self._to_score(t, df, rising.get(t, []), timeframe) for t in batch}
            except Exception as exc:
                if attempt == 1 and self._is_429(exc):
                    log.warning("pytrends 429 on batch %s — retrying once in %.0fs.",
                                batch, self.retry_sleep)
                    self.sleep_fn(self.retry_sleep)
                    continue
                log.warning("pytrends batch %s failed (%s: %s) — skipped, scores=None.",
                            batch, type(exc).__name__, exc)
                return {t: TrendScore(term=t, interest_now=None, source=self.name) for t in batch}
        return {}  # unreachable

    def _rising_queries(self, batch: list[str]) -> dict[str, list[str]]:
        try:
            related = self.client.related_queries()
            out = {}
            for term in batch:
                df = (related.get(term) or {}).get("rising")
                out[term] = (df["query"].head(MAX_RISING_QUERIES).tolist()
                             if df is not None and not df.empty else [])
            return out
        except Exception as exc:
            log.debug("pytrends related_queries failed (%s) — continuing without.", exc)
            return {term: [] for term in batch}

    def _to_score(self, term: str, df, rising: list[str], timeframe: str) -> TrendScore:
        if df is None or df.empty or term not in df.columns:
            return TrendScore(term=term, interest_now=None, source=self.name)
        series = df[term].astype(float)
        recent = max(1, len(series) // 4)
        now = float(series.iloc[-recent:].mean())
        baseline = float(series.iloc[:-recent].mean()) if len(series) > recent else None
        delta = round((now - baseline) / baseline * 100, 1) if baseline else None
        score = TrendScore(
            term=term,
            interest_now=round(now, 1),
            interest_baseline=round(baseline, 1) if baseline is not None else None,
            delta_pct=delta,
            rising_related_queries=rising,
            fetched_at=datetime.now(timezone.utc),
            source=self.name,
        )
        self._write_cache(score, timeframe)
        return score

    @staticmethod
    def _is_429(exc: Exception) -> bool:
        if type(exc).__name__ == "TooManyRequestsError":
            return True
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None) == 429

    # -- cache --------------------------------------------------------------

    def _cache_path(self, term: str, timeframe: str) -> Path:
        key = re.sub(r"[^a-z0-9]+", "_", f"{term}_{timeframe}".lower()).strip("_")
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, term: str, timeframe: str) -> TrendScore | None:
        path = self._cache_path(term, timeframe)
        try:
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(data["fetched_at"])
            if datetime.now(timezone.utc) - fetched_at > CACHE_TTL:
                return None
            return TrendScore(
                term=data["term"],
                interest_now=data["interest_now"],
                interest_baseline=data.get("interest_baseline"),
                delta_pct=data.get("delta_pct"),
                rising_related_queries=data.get("rising_related_queries", []),
                fetched_at=fetched_at,
                source=self.name,
            )
        except Exception as exc:
            log.debug("trends cache read failed for %r (%s) — refetching.", term, exc)
            return None

    def _write_cache(self, score: TrendScore, timeframe: str) -> None:
        try:
            payload = {
                "term": score.term,
                "interest_now": score.interest_now,
                "interest_baseline": score.interest_baseline,
                "delta_pct": score.delta_pct,
                "rising_related_queries": score.rising_related_queries,
                "fetched_at": score.fetched_at.isoformat(),
            }
            self._cache_path(score.term, timeframe).write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as exc:
            log.debug("trends cache write failed for %r (%s) — continuing.", score.term, exc)
