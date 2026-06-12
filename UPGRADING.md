# Upgrading to the official Google Trends API (Alpha)

When Google grants Alpha access, the switch is deliberately small: **one file
to implement, one config block to fill in.** Nothing downstream changes —
scoring, diffing, generation, validation and the report all consume the
`TrendsProvider` interface and never import a concrete provider.

## The contract you are implementing

`src/providers/base.py` defines it:

```python
def get_scores(self, terms: list[str], timeframe: str = "now 7-d") -> dict[str, TrendScore]
```

Hard guarantees the rest of the pipeline relies on:

1. **Every requested term gets a `TrendScore` back**, keyed exactly by the
   term as passed in.
2. **A single bad term never raises.** Failures return
   `interest_now=None` for that term; the pipeline treats it as "no signal".
3. `TrendScore` fields: `term`, `interest_now` (0–100), `interest_baseline`
   (avg of the prior period), `delta_pct`, `rising_related_queries` (list,
   may be empty), `fetched_at` (timezone-aware UTC), `source` (`"google_api"`).

## Step by step

1. **Credentials.** Add a `google_api:` block to `config.yaml`; the factory
   passes it verbatim to the constructor as kwargs:

   ```yaml
   provider: google_api
   google_api:
     api_key: "..."            # or credentials_file: secrets/trends-sa.json
   ```

   Do **not** commit secrets — point `credentials_file` at a gitignored path.

2. **Implement `src/providers/google_api.py`** (the only file that changes):
   - `__init__(**config)`: validate credentials, build the HTTP/SDK client.
     Raise a clear error on missing credentials — the factory will surface it.
   - `get_scores()`: map our `timeframe` strings (`"now 7-d"`) to the API's
     time-range parameters, fetch interest over time per term (batch to
     whatever the alpha quota allows), and map the response to `TrendScore`:
     `interest_now` = current scaled interest, `interest_baseline` = average
     of the prior comparison period, `delta_pct` = relative change. Pull
     rising related queries if the API exposes them, else `[]`.
   - **Reuse the cache pattern** from `pytrends_provider.py`:
     `cache/trends/{term}_{timeframe}.json`, 12h TTL, never cache failures.
     Copying `_read_cache`/`_write_cache`/`_cache_path` verbatim is fine.

3. **Wire-up is already done.** `src/providers/__init__.py` constructs
   `GoogleTrendsApiProvider(**config["google_api"])` when
   `provider: google_api` is set (or `--provider google_api` is passed).
   There is deliberately **no automatic fallback to manual** for this
   provider (unlike pytrends): an official API failing is something you want
   to see, not paper over. Add a `PytrendsWithFallback`-style wrapper in the
   factory if you decide otherwise.

4. **Test before trusting it** (mirror `tests/test_milestone4.py`, which
   fakes pytrends — fake the HTTP client the same way):
   - score math: now / baseline / delta from a known response payload
   - every term returns a `TrendScore`; a failing term returns `None` score
   - cache hit, TTL expiry
   - quota/429-equivalent handling
   Then run the full gate: all `python -m tests.test_milestone*` suites must
   stay green — the golden test (`test_milestone2`) is unaffected by provider
   changes by design.

5. **First real run:**

   ```bash
   python -m src.run --provider google_api --threshold 50
   ```

   Check `run_log.txt` and `insights.html` for failed terms, then compare a
   few scores against trends.google.com by hand before importing any ads.

## Reference implementation

`src/providers/pytrends_provider.py` is the working template for batching,
caching, rate-limit handling, and graceful degradation. Match its structure
and logging style; replace the transport.
