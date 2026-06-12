"""Milestone 4 tests — PytrendsProvider: batching, caching, 429 retry, fallback.

pytrends is NOT installed (by design — it's optional). These tests inject a
fake `pytrends.request.TrendReq` into sys.modules to exercise the provider
logic, and verify the factory degrades to manual when pytrends is absent.

Run with:  python -m tests.test_milestone4   (also works under pytest)
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


class FakeTrendReq:
    """Stand-in for pytrends.request.TrendReq with scriptable behaviour."""

    # class-level script, reset per test
    interest: dict[str, list[float]] = {}
    rising: dict[str, list[str]] = {}
    fail_with: Exception | None = None
    fail_times: int = 0  # how many build_payload calls raise before succeeding
    calls: list[list[str]] = []

    def __init__(self, hl="en-US", tz=0):
        self._batch: list[str] = []

    def build_payload(self, terms, timeframe="now 7-d", **kwargs):
        FakeTrendReq.calls.append(list(terms))
        if FakeTrendReq.fail_with is not None and FakeTrendReq.fail_times != 0:
            if FakeTrendReq.fail_times > 0:
                FakeTrendReq.fail_times -= 1
            raise FakeTrendReq.fail_with
        self._batch = list(terms)

    def interest_over_time(self):
        data = {t: FakeTrendReq.interest.get(t, [0] * 8) for t in self._batch}
        return pd.DataFrame(data)

    def related_queries(self):
        out = {}
        for t in self._batch:
            queries = FakeTrendReq.rising.get(t, [])
            out[t] = {"rising": pd.DataFrame({"query": queries}) if queries else None}
        return out

    @classmethod
    def reset(cls, interest=None, rising=None, fail_with=None, fail_times=0):
        cls.interest = interest or {}
        cls.rising = rising or {}
        cls.fail_with = fail_with
        cls.fail_times = fail_times
        cls.calls = []


class Fake429(Exception):
    """Mimics pytrends' TooManyRequestsError by name detection via response."""

    def __init__(self):
        super().__init__("429 rate limited")
        self.response = types.SimpleNamespace(status_code=429)


def _install_fake_pytrends():
    pytrends_mod = types.ModuleType("pytrends")
    request_mod = types.ModuleType("pytrends.request")
    request_mod.TrendReq = FakeTrendReq
    pytrends_mod.request = request_mod
    sys.modules["pytrends"] = pytrends_mod
    sys.modules["pytrends.request"] = request_mod


def _uninstall_fake_pytrends():
    sys.modules.pop("pytrends", None)
    sys.modules.pop("pytrends.request", None)


def _provider(cache_dir=None):
    from src.providers.pytrends_provider import PytrendsProvider
    return PytrendsProvider(cache_dir=cache_dir or tempfile.mkdtemp(),
                            sleep_fn=lambda s: None)


def test_scores_baseline_and_delta():
    _install_fake_pytrends()
    try:
        # 8 points: baseline = first 6 (avg 50), now = last quarter = 2 points (avg 80)
        FakeTrendReq.reset(interest={"nvidia stock": [50, 50, 50, 50, 50, 50, 80, 80]},
                           rising={"nvidia stock": ["nvidia earnings", "nvidia split"]})
        scores = _provider().get_scores(["nvidia stock"])
        s = scores["nvidia stock"]
        assert s.interest_now == 80.0, s
        assert s.interest_baseline == 50.0, s
        assert s.delta_pct == 60.0, s
        assert s.rising_related_queries == ["nvidia earnings", "nvidia split"]
        assert s.source == "pytrends"
    finally:
        _uninstall_fake_pytrends()


def test_batches_of_five():
    _install_fake_pytrends()
    try:
        terms = [f"term {i}" for i in range(12)]
        FakeTrendReq.reset(interest={t: [10] * 8 for t in terms})
        scores = _provider().get_scores(terms)
        assert len(scores) == 12
        assert [len(b) for b in FakeTrendReq.calls] == [5, 5, 2]
    finally:
        _uninstall_fake_pytrends()


def test_cache_hit_and_ttl():
    _install_fake_pytrends()
    try:
        cache_dir = tempfile.mkdtemp()
        FakeTrendReq.reset(interest={"tesla stock": [40] * 8})
        p = _provider(cache_dir)
        p.get_scores(["tesla stock"])
        assert len(FakeTrendReq.calls) == 1

        # Second call: served from cache, no new request.
        p2 = _provider(cache_dir)
        scores = p2.get_scores(["tesla stock"])
        assert len(FakeTrendReq.calls) == 1, "expected cache hit, got a fetch"
        assert scores["tesla stock"].interest_now == 40.0

        # Expire the cache entry -> refetch.
        cache_file = next(Path(cache_dir, "trends").glob("*.json"))
        data = json.loads(cache_file.read_text())
        data["fetched_at"] = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        cache_file.write_text(json.dumps(data))
        p2.get_scores(["tesla stock"])
        assert len(FakeTrendReq.calls) == 2, "expected refetch after TTL expiry"
    finally:
        _uninstall_fake_pytrends()


def test_429_retries_once_then_succeeds():
    _install_fake_pytrends()
    try:
        FakeTrendReq.reset(interest={"gme stock": [30] * 8}, fail_with=Fake429(), fail_times=1)
        slept = []
        from src.providers.pytrends_provider import PytrendsProvider
        p = PytrendsProvider(cache_dir=tempfile.mkdtemp(), sleep_fn=slept.append)
        scores = p.get_scores(["gme stock"])
        assert scores["gme stock"].interest_now == 30.0
        assert len(FakeTrendReq.calls) == 2, "expected exactly one retry"
        assert any(s >= 30 for s in slept), "expected the retry backoff sleep"
    finally:
        _uninstall_fake_pytrends()


def test_persistent_failure_yields_none_not_raise():
    _install_fake_pytrends()
    try:
        FakeTrendReq.reset(fail_with=RuntimeError("pytrends broke again"), fail_times=-1)
        scores = _provider().get_scores(["a stock", "b stock"])
        assert all(s.interest_now is None for s in scores.values())
        assert set(scores) == {"a stock", "b stock"}
    finally:
        _uninstall_fake_pytrends()


def test_factory_falls_back_to_manual_when_pytrends_missing():
    _uninstall_fake_pytrends()
    import yaml
    config = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    from src.providers import get_provider
    provider = get_provider("pytrends", config)
    assert provider.name == "manual", f"expected manual fallback, got {provider.name}"


def test_runtime_fallback_when_pytrends_returns_nothing():
    _install_fake_pytrends()
    try:
        FakeTrendReq.reset(fail_with=RuntimeError("dead"), fail_times=-1)
        import yaml
        config = yaml.safe_load(open("config.yaml", encoding="utf-8"))
        from src.providers import get_provider
        provider = get_provider("pytrends", config)
        assert provider.name == "pytrends"
        scores = provider.get_scores(["nvidia stock", "nvda stock"])
        # ManualProvider takes over: hot list has NVDA -> usable scores appear.
        assert any(s.interest_now is not None for s in scores.values())
        assert "fallback" in provider.name
    finally:
        _uninstall_fake_pytrends()


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
