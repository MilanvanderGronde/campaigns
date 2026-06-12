"""GoogleTrendsApiProvider — STUB awaiting Google Trends API (Alpha) access.

The operator has requested access to Google's official Trends API alpha.
When access is granted, ONLY THIS FILE changes — the factory already
constructs this class from config.yaml (`provider: google_api`, with the
optional `google_api:` config block passed as constructor kwargs), and
everything downstream consumes the TrendsProvider interface.

See UPGRADING.md at the repo root for the full step-by-step guide.

What to implement (mirror pytrends_provider.py, which is the reference
implementation for batching/caching/degradation):

1. AUTH — in __init__:
   - Accept credentials via the `google_api` block in config.yaml
     (e.g. `api_key: ...` or `credentials_file: path/to/service-account.json`).
   - Build the client (google-api-python-client / plain HTTPS — whatever the
     alpha docs prescribe). Raise on missing/invalid credentials so the
     factory's construction guard surfaces a clear error.

2. FETCH — in get_scores():
   - Map our timeframe strings ("now 7-d") to the API's time-range parameters.
   - Respect whatever quota the alpha grants; batch terms accordingly and
     reuse the 12h JSON cache pattern (cache/trends/{term}_{timeframe}.json)
     from pytrends_provider so re-runs are free.

3. MAP RESPONSE -> TrendScore, one per requested term:
   - interest_now:        current scaled interest (0-100)
   - interest_baseline:   average over the prior comparison period
   - delta_pct:           (now - baseline) / baseline * 100
   - rising_related_queries: from the related/rising endpoint if exposed,
                             else [] — never omit the field
   - fetched_at:          datetime.now(timezone.utc)
   - source:              self.name  ("google_api")
   Interface guarantees to keep: return a TrendScore for EVERY requested
   term; per-term/batch failures yield interest_now=None — never raise out
   of get_scores for a single bad term.
"""

from __future__ import annotations

from src.providers.base import TrendScore, TrendsProvider


class GoogleTrendsApiProvider(TrendsProvider):
    name = "google_api"

    def __init__(self, **config):
        # `config` receives the `google_api:` block from config.yaml verbatim
        # (api_key / credentials_file / endpoint overrides — to be defined by
        # the alpha docs). Keep accepting **config so config.yaml stays the
        # single source of provider settings.
        raise NotImplementedError(
            "Google Trends API access not yet granted. See UPGRADING.md — "
            "implement auth, fetching, and the response->TrendScore mapping "
            "in this file only.")

    def get_scores(self, terms: list[str], timeframe: str = "now 7-d") -> dict[str, TrendScore]:
        raise NotImplementedError("See UPGRADING.md.")
