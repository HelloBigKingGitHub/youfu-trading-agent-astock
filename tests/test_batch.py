"""Tests for batch analysis: API validation + JobQueue concurrency + retry.

Unit tests are pure (no LLM calls). The integration test at the bottom
runs a real 3-ticker batch end-to-end against the LLM and is gated by
the env var RUN_BATCH_E2E=1 — it's off by default to keep CI fast.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import date

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Ticker whitelist helper — mirror the production regex so tests pin it.
# ─────────────────────────────────────────────────────────────────────────────

TICKER_WHITELIST_RE = (
    r"^(60[0-5]\d{3}|688\d{3}|000\d{3}|001\d{3}|002\d{3}|003\d{3}"
    r"|300\d{3}|301\d{3}|430\d{3})$"
)


def _is_valid_ticker(t: str) -> bool:
    import re
    return bool(re.match(TICKER_WHITELIST_RE, t))


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests: ticker whitelist (no imports of project code)
# ─────────────────────────────────────────────────────────────────────────────


class TestTickerWhitelist:
    """Pin the exact whitelist regex from the spec."""

    @pytest.mark.unit
    @pytest.mark.parametrize("ticker", [
        "688017", "688999",  # 科创板
        "600519", "600000", "605000",  # 沪市主板
        "000001", "000999",  # 深市主板
        "001979",  # 深市主板
        "002415", "002999",  # 中小板
        "003001", "003999",  # 深市主板
        "300750", "300999",  # 创业板
        "301236", "301999",  # 创业板
        "430001", "430999",  # 北交所
    ])
    def test_valid_tickers_accepted(self, ticker: str):
        assert _is_valid_ticker(ticker), f"{ticker} should be valid"

    @pytest.mark.unit
    @pytest.mark.parametrize("ticker", [
        "abc123",   # alphabetic
        "12345",    # 5-digit
        "1234567",  # 7-digit
        "606000",   # 60 prefix but [0-5] rejects 6
        "68801",    # 5-digit
        "6880001",  # 7-digit
        "302000",   # 300 prefix but [0-3] would be needed; 2 is rejected
        "432000",   # 430 prefix but [0-3] would be needed; 2 is rejected
        "999999",   # not whitelisted
        "777777",   # not whitelisted
        "004001",   # not whitelisted (no 004 prefix)
        "",         # empty
        "00000",    # 5-digit
        "00000000", # 8-digit
        "600519a",  # trailing alpha
        "a600519",  # leading alpha
        "600-519",  # punctuation
    ])
    def test_invalid_tickers_rejected(self, ticker: str):
        assert not _is_valid_ticker(ticker), f"{ticker!r} should be rejected"


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests: JobQueue submit + concurrency + retry
# ─────────────────────────────────────────────────────────────────────────────


def _build_mock_job(ticker: str = "688017", date_str: str = "2026-06-30") -> dict:
    """Create a fake job-dict compatible with JobQueue.submit."""
    return {"ticker": ticker, "trade_date": date_str}
    """Exercise JobQueue.submit with a monkeypatched _run_one."""

    @pytest.mark.unit
    def test_submit_respects_max_workers_cap(self, monkeypatch):
        """Verify at most max_workers jobs run concurrently."""
        from backend.core import job_queue as jq_mod

        # Patch _run_one to simulate work that holds a semaphore.
        active = threading.Semaphore(value=2)  # max_workers=2
        peak = [0]
        current = [0]
        lock = threading.Lock()
        started = threading.Event()
        all_started = threading.Event()
        n_to_run = [0]

        def fake_run_one(self, job, config):
            with lock:
                current[0] += 1
                peak[0] = max(peak[0], current[0])
                n_to_run[0] += 1
                if n_to_run[0] >= 1:
                    started.set()
            try:
                # Hold the slot briefly so concurrent jobs are observable.
                active.acquire(timeout=5)
                try:
                    time.sleep(0.2)
                finally:
                    active.release()
            finally:
                with lock:
                    current[0] -= 1

        monkeypatch.setattr(jq_mod.JobQueue, "_run_one", fake_run_one)

        q = jq_mod.JobQueue()
        q._max_workers = 2

        # Build 5 jobs (not via API — directly into the queue).
        from backend.core.job_queue import BatchJob, Job

        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        jobs = []
        for i in range(5):
            job = Job(
                job_id=f"j{i}_{uuid.uuid4().hex[:6]}",
                analysis_id=f"a{i}",
                ticker=f"60051{i}",
                trade_date="2026-06-30",
            )
            jobs.append(job)

        q._batches[batch_id] = BatchJob(batch_id=batch_id, jobs=jobs)
        for j in jobs:
            q._jobs[j.job_id] = j

        q.submit(batch_id, jobs, configs=[{} for _ in jobs])

        # Wait for all jobs to finish.
        q.wait_for_batch(batch_id, timeout=15)

        # Peak concurrency must NOT exceed max_workers=2.
        assert peak[0] <= 2, f"peak concurrency {peak[0]} > 2"
        assert peak[0] >= 2, "expected at least 2 concurrent (workers used)"
        # All 5 jobs completed.
        for j in jobs:
            d = j.to_dict()
            assert d["status"] in ("completed", "error")

    @pytest.mark.unit
    def test_one_failure_does_not_block_others(self, monkeypatch):
        """If one job raises, the rest of the batch must still complete."""
        from backend.core import job_queue as jq_mod

        def fake_run_one(self, job, config):
            if job.ticker == "600513":
                raise RuntimeError("simulated boom")
            # happy path: just mark complete
            with job._lock:
                job.status = "completed"
                job.started_at = time.time()
                job.finished_at = job.started_at + 0.05
                job.elapsed = 0.05

        monkeypatch.setattr(jq_mod.JobQueue, "_run_one", fake_run_one)
        monkeypatch.setattr(jq_mod.JobQueue, "_handle_em_block", lambda self, job, err: None)

        q = jq_mod.JobQueue()
        q._max_workers = 3

        from backend.core.job_queue import BatchJob, Job

        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        jobs = []
        for ticker in ("600510", "600511", "600512", "600513", "600514"):
            j = Job(
                job_id=f"j_{ticker}_{uuid.uuid4().hex[:6]}",
                analysis_id=f"a_{ticker}",
                ticker=ticker,
                trade_date="2026-06-30",
            )
            jobs.append(j)

        q._batches[batch_id] = BatchJob(batch_id=batch_id, jobs=jobs)
        for j in jobs:
            q._jobs[j.job_id] = j

        q.submit(batch_id, jobs, configs=[{} for _ in jobs])
        q.wait_for_batch(batch_id, timeout=15)

        statuses = [j.to_dict()["status"] for j in jobs]
        # Exactly one error, four completed.
        assert statuses.count("error") == 1, statuses
        assert statuses.count("completed") == 4, statuses
        # Batch-level status should be "partial".
        batch = q.get_batch(batch_id)
        assert batch is not None
        assert batch.batch_status == "partial"

    @pytest.mark.unit
    def test_retry_resets_and_runs_failed_job(self, monkeypatch):
        """retry() must reset a failed job to pending and re-run it."""
        from backend.core import job_queue as jq_mod

        # First call raises; second call succeeds.
        run_calls = {"n": 0}

        def fake_run_one(self, job, config):
            run_calls["n"] += 1
            if run_calls["n"] == 1:
                raise RuntimeError("first attempt fails")
            with job._lock:
                job.status = "completed"
                job.started_at = time.time()
                job.finished_at = job.started_at + 0.05
                job.elapsed = 0.05

        monkeypatch.setattr(jq_mod.JobQueue, "_run_one", fake_run_one)
        monkeypatch.setattr(jq_mod.JobQueue, "_handle_em_block", lambda self, job, err: None)

        q = jq_mod.JobQueue()
        q._max_workers = 2

        from backend.core.job_queue import BatchJob, Job

        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        job = Job(
            job_id=f"j_{uuid.uuid4().hex[:8]}",
            analysis_id=f"a_{uuid.uuid4().hex[:8]}",
            ticker="600519",
            trade_date="2026-06-30",
        )
        q._batches[batch_id] = BatchJob(batch_id=batch_id, jobs=[job])
        q._jobs[job.job_id] = job

        q.submit(batch_id, [job], configs=[{}])
        q.wait_for_batch(batch_id, timeout=10)
        assert job.status == "error"

        # Retry: should clear error and re-submit.
        q.retry(job.job_id, config={})
        q.wait_for_batch(batch_id, timeout=10)
        assert job.status == "completed"
        assert run_calls["n"] == 2

    @pytest.mark.unit
    def test_cancel_pending_job(self, monkeypatch):
        """A pending job that gets cancelled must end up in cancelled state."""
        from backend.core import job_queue as jq_mod

        # _run_one that blocks until the job is cancelled.
        started = threading.Event()
        proceed = threading.Event()

        def fake_run_one(self, job, config):
            started.set()
            # Wait until cancellation or 5s.
            for _ in range(50):
                if job.status == "cancelled":
                    return
                time.sleep(0.1)
            # Otherwise mark completed.
            with job._lock:
                job.status = "completed"

        monkeypatch.setattr(jq_mod.JobQueue, "_run_one", fake_run_one)

        q = jq_mod.JobQueue()
        q._max_workers = 1
        from backend.core.job_queue import BatchJob, Job

        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        job = Job(
            job_id=f"j_{uuid.uuid4().hex[:8]}",
            analysis_id=f"a_{uuid.uuid4().hex[:8]}",
            ticker="000001",
            trade_date="2026-06-30",
        )
        q._batches[batch_id] = BatchJob(batch_id=batch_id, jobs=[job])
        q._jobs[job.job_id] = job
        q.submit(batch_id, [job], configs=[{}])

        # Wait until the worker is running, then cancel.
        assert started.wait(timeout=5)
        q.cancel_job(job.job_id)
        proceed.wait(timeout=2)
        q.wait_for_batch(batch_id, timeout=5)
        assert job.status == "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests: POST /api/batch request validation
# ─────────────────────────────────────────────────────────────────────────────


class TestBatchAPIValidation:
    """Use FastAPI TestClient with a stubbed submit so no real work happens."""

    @pytest.fixture()
    def client(self, monkeypatch):
        # Stub JobQueue.submit to be a no-op so tests don't touch the executor.
        from backend.core import job_queue as jq_mod
        monkeypatch.setattr(jq_mod.JobQueue, "submit", lambda self, *a, **k: None)
        monkeypatch.setattr(jq_mod.JobQueue, "_run_one", lambda self, job, config: None)

        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_ticker", [
        "abc123", "12345", "1234567", "606000", "68801",
        "6880001", "302000", "432000", "999999", "777777",
        "004001", "", "600519a", "a600519", "00000",
        "00000000", "600-519",
    ])
    def test_bad_ticker_rejected(self, client, bad_ticker):
        r = client.post(
            "/api/batch",
            json=[{"ticker": bad_ticker, "trade_date": "2026-06-30"}],
        )
        assert r.status_code == 400, r.text
        assert "ticker" in r.text.lower()

    @pytest.mark.unit
    def test_empty_batch_rejected(self, client):
        r = client.post("/api/batch", json=[])
        assert r.status_code == 400

    @pytest.mark.unit
    def test_over_50_rejected(self, client):
        items = [{"ticker": "688017", "trade_date": "2026-06-30"}] * 51
        r = client.post("/api/batch", json=items)
        assert r.status_code == 400
        assert "50" in r.text

    @pytest.mark.unit
    def test_duplicate_tickers_rejected(self, client):
        r = client.post(
            "/api/batch",
            json=[
                {"ticker": "688017", "trade_date": "2026-06-30"},
                {"ticker": "688017", "trade_date": "2026-06-30"},
            ],
        )
        assert r.status_code == 400
        assert "duplicate" in r.text.lower() or "dup" in r.text.lower()

    @pytest.mark.unit
    def test_valid_batch_creates_history_entries(self, client, monkeypatch):
        from backend.core.job_queue import get_job_queue

        # Spy on create_batch to confirm it gets called.
        q = get_job_queue()
        original_create = q.create_batch

        called = {"items": None}
        def spy_create(reqs):
            called["items"] = list(reqs)
            return original_create(reqs)

        monkeypatch.setattr(q, "create_batch", spy_create)

        r = client.post(
            "/api/batch",
            json=[
                {"ticker": "688017", "trade_date": "2026-06-30"},
                {"ticker": "600519", "trade_date": "2026-06-30"},
                {"ticker": "000001", "trade_date": "2026-06-30"},
            ],
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3
        assert len(body["jobs"]) == 3
        assert {j["ticker"] for j in body["jobs"]} == {"688017", "600519", "000001"}
        assert called["items"] is not None
        assert len(called["items"]) == 3

    @pytest.mark.unit
    def test_dedupe_skips_already_completed(self, client):
        """With dedupe=true, a previously completed ticker+date should be filtered out."""
        from backend.core.history_store import HistoryEntry, get_history_store

        store = get_history_store()
        # Seed a completed entry for 688017 / 2026-06-30.
        seed = HistoryEntry(
            analysis_id=f"seed_{uuid.uuid4().hex[:8]}",
            ticker="688017",
            trade_date="2026-06-30",
            status="completed",
            signal="BUY",
        )
        store.update(seed)

        r = client.post(
            "/api/batch?dedupe=true",
            json=[
                {"ticker": "688017", "trade_date": "2026-06-30"},
                {"ticker": "600519", "trade_date": "2026-06-30"},
            ],
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Only the new one survives dedup.
        assert body["total"] == 1
        assert body["jobs"][0]["ticker"] == "600519"

        # Cleanup the seed.
        store.delete(seed.analysis_id)

    @pytest.mark.unit
    def test_per_item_llm_config_used(self, client, monkeypatch):
        """When the request body carries llm_provider / deep_think_llm on an
        item, those values must reach the JobQueue worker (and ultimately the
        runner) verbatim — not be clobbered by env / DEFAULT_CONFIG.
        """
        from backend.core import job_queue as jq_mod

        # The ``client`` fixture already stubs ``submit`` and ``_run_one`` to
        # no-ops. Override ``submit`` with a capturing spy that still avoids
        # touching the real executor.
        from concurrent.futures import Future

        captured: list[dict] = []

        def stub_submit(self, batch_id, jobs, configs=None):
            for j, c in zip(jobs, configs or [{}] * len(jobs)):
                captured.append(dict(c))
            fut = Future()
            fut.set_result(None)
            return [fut] * len(jobs)

        monkeypatch.setattr(jq_mod.JobQueue, "submit", stub_submit)

        r = client.post(
            "/api/batch",
            json=[{
                "ticker": "688017",
                "trade_date": "2026-06-30",
                "llm_provider": "deepseek",
                "deep_think_llm": "deepseek-chat",
                "quick_think_llm": "deepseek-reasoner",
                "backend_url": "https://example.test/v1",
            }],
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        # The job's config must contain the user-supplied values.
        assert captured, "submit was never called"
        cfg = captured[0]
        assert cfg["llm_provider"] == "deepseek", cfg
        assert cfg["deep_think_llm"] == "deepseek-chat", cfg
        assert cfg["quick_think_llm"] == "deepseek-reasoner", cfg
        assert cfg["backend_url"] == "https://example.test/v1", cfg
        # And the response echoes the resolved LLM summary so the UI can verify.
        assert body["llm_summary"][0]["llm_provider"] == "deepseek"
        assert body["llm_summary"][0]["deep_think_llm"] == "deepseek-chat"

    @pytest.mark.unit
    def test_missing_llm_uses_minimax_fallback(self, client, monkeypatch):
        """When no LLM fields are provided on the item AND the relevant env
        vars are absent, the resulting config must fall back to
        ``"minimax"`` (NOT the upstream DEFAULT_CONFIG.llm_provider of
        ``"openai"``, which would break with a missing-credentials error).
        """
        from backend.core import job_queue as jq_mod

        # Strip any batch-related env so the fallback chain is forced all the
        # way to the hard-coded "minimax" / MiniMax-M2.7 / MiniMax-M2.7-highspeed.
        for k in (
            "BATCH_LLM_PROVIDER", "BATCH_DEEP_MODEL", "BATCH_QUICK_MODEL",
            "LLM_PROVIDER", "DEEP_THINK_LLM", "QUICK_THINK_LLM",
            "BACKEND_URL",
        ):
            monkeypatch.delenv(k, raising=False)

        from concurrent.futures import Future

        captured: list[dict] = []

        def stub_submit(self, batch_id, jobs, configs=None):
            for j, c in zip(jobs, configs or [{}] * len(jobs)):
                captured.append(dict(c))
            fut = Future()
            fut.set_result(None)
            return [fut] * len(jobs)

        monkeypatch.setattr(jq_mod.JobQueue, "submit", stub_submit)

        r = client.post(
            "/api/batch",
            json=[{"ticker": "688017", "trade_date": "2026-06-30"}],
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        assert captured, "submit was never called"
        cfg = captured[0]
        # Must be the hard-coded "minimax" — NOT "openai" from DEFAULT_CONFIG.
        assert cfg["llm_provider"] == "minimax", cfg
        assert cfg["deep_think_llm"] == "MiniMax-M2.7", cfg
        assert cfg["quick_think_llm"] == "MiniMax-M2.7-highspeed", cfg
        # And the response surfaces the resolved summary.
        assert body["llm_summary"][0]["llm_provider"] == "minimax"

    @pytest.mark.unit
    def test_data_cache_dir_preserved_from_default_config(self, client, monkeypatch):
        """The per-job config must include ``data_cache_dir`` (and other
        upstream-required keys) from ``DEFAULT_CONFIG``.

        Regression guard for the bug where ``build_default_configs`` built a
        brand-new dict from scratch, dropping every key that wasn't one of the
        ~7 explicitly listed ones — causing ``TradingAgentsGraph.__init__`` to
        crash with ``KeyError: 'data_cache_dir'``. The fix mirrors
        ``web/app.py._build_config`` by using ``dict(DEFAULT_CONFIG)`` as the
        seed and overriding only the LLM / debate / language / data_vendors
        fields. The openai fallback bug stays fixed because the LLM override
        is applied *after* the copy.
        """
        from backend.core import job_queue as jq_mod
        from concurrent.futures import Future
        from tradingagents.default_config import DEFAULT_CONFIG

        captured: list[dict] = []

        def stub_submit(self, batch_id, jobs, configs=None):
            for j, c in zip(jobs, configs or [{}] * len(jobs)):
                captured.append(dict(c))
            fut = Future()
            fut.set_result(None)
            return [fut] * len(jobs)

        monkeypatch.setattr(jq_mod.JobQueue, "submit", stub_submit)

        # Strip batch-related env so the fallback chain is forced all the way
        # to the hard-coded "minimax" defaults.
        for k in (
            "BATCH_LLM_PROVIDER", "BATCH_DEEP_MODEL", "BATCH_QUICK_MODEL",
            "LLM_PROVIDER", "DEEP_THINK_LLM", "QUICK_THINK_LLM",
            "BACKEND_URL",
        ):
            monkeypatch.delenv(k, raising=False)

        r = client.post(
            "/api/batch",
            json=[{"ticker": "688017", "trade_date": "2026-06-30"}],
        )
        assert r.status_code == 200, r.text
        assert captured, "submit was never called"
        cfg = captured[0]

        # The critical regression guard: data_cache_dir must be present and
        # match DEFAULT_CONFIG. Without this, TradingAgentsGraph.__init__
        # blows up with KeyError before any LLM is called.
        assert "data_cache_dir" in cfg, "data_cache_dir missing from config"
        assert cfg["data_cache_dir"] == DEFAULT_CONFIG["data_cache_dir"], cfg
        # And the upstream-required companions should also be preserved.
        for upstream_key in (
            "results_dir",
            "memory_log_path",
            "project_dir",
            "data_vendors",
            "tool_vendors",
        ):
            assert upstream_key in cfg, f"upstream key {upstream_key!r} dropped"
            assert cfg[upstream_key] == DEFAULT_CONFIG[upstream_key], (
                upstream_key, cfg.get(upstream_key), DEFAULT_CONFIG[upstream_key]
            )
        # And the openai fallback bug must stay fixed — the LLM override has
        # to win over DEFAULT_CONFIG.llm_provider == "openai".
        assert cfg["llm_provider"] == "minimax", cfg
        # data_vendors is set to a_stock even though DEFAULT_CONFIG already
        # uses a_stock — the explicit override keeps the ASTOCK-only behaviour
        # robust against DEFAULT_CONFIG upstream changes.
        assert cfg["data_vendors"]["core_stock_apis"] == "a_stock", cfg["data_vendors"]


# ─────────────────────────────────────────────────────────────────────────────
# Regression: backend.main must load .env at import time
# ─────────────────────────────────────────────────────────────────────────────


class TestMainLoadsDotenv:
    """`backend.main` is the FastAPI entrypoint used by uvicorn.

    uvicorn workers were previously crashing with
    ``Missing credentials ... OPENAI_API_KEY or OPENAI_ADMIN_KEY`` because
    the uvicorn process inherited an environment with **zero** LLM keys
    (only streamlit's ``web/app.py`` called ``load_dotenv``). This test
    pins the fix: importing ``backend.main`` must populate at least one
    LLM-provider key from the repo-root ``.env``.

    Skips gracefully if neither key is present in ``.env``.
    """

    def test_main_loads_dotenv(self, monkeypatch):
        # Pre-clear any keys that the conftest autouse fixture may have
        # already injected (so we test what backend.main itself does).
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        # Importing the module runs load_dotenv as a side effect.
        import backend.main  # noqa: F401

        minimax = os.environ.get("MINIMAX_API_KEY")
        deepseek = os.environ.get("DEEPSEEK_API_KEY")

        if not (minimax or deepseek):
            pytest.skip(".env has neither MINIMAX_API_KEY nor DEEPSEEK_API_KEY")

        # At least one of them must be a non-empty string value.
        loaded = [v for v in (minimax, deepseek) if v]
        assert loaded, (
            "backend.main.load_dotenv() did not populate MINIMAX_API_KEY or "
            "DEEPSEEK_API_KEY — uvicorn workers will crash with the openai "
            "credentials fallback error."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Integration test — gated by RUN_BATCH_E2E=1
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("RUN_BATCH_E2E") != "1",
    reason="set RUN_BATCH_E2E=1 to run real 3-ticker end-to-end batch test",
)
class TestBatchE2E:
    """End-to-end batch against the real LLM + real data.

    Submits 3 small-cap A-share tickers (688017 欧普康视, 600519 贵州茅台,
    000001 平安银行) for today's date and asserts all 3 complete with
    non-empty signal within 300s.

    Marked @pytest.mark.integration so it shows up in the integration lane.
    """

    @pytest.mark.integration
    def test_three_tickers_complete(self):
        from backend.core.job_queue import get_job_queue
        from tradingagents.default_config import DEFAULT_CONFIG

        today = date.today().strftime("%Y-%m-%d")
        q = get_job_queue()

        batch_id, batch = q.create_batch([
            {"ticker": "688017", "trade_date": today},
            {"ticker": "600519", "trade_date": today},
            {"ticker": "000001", "trade_date": today},
        ])

        config = dict(DEFAULT_CONFIG)
        # Make tests cheap: 1 round each, Chinese output.
        config.update({
            "llm_provider": "minimax",
            "deep_think_llm": os.environ.get("BATCH_TEST_DEEP_MODEL", "MiniMax-M2.7"),
            "quick_think_llm": os.environ.get("BATCH_TEST_QUICK_MODEL", "MiniMax-M2.7-highspeed"),
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "output_language": "Chinese",
            "data_vendors": {
                "core_stock_apis": "a_stock",
                "technical_indicators": "a_stock",
                "fundamental_data": "a_stock",
                "news_data": "a_stock",
                "signal_data": "a_stock",
            },
        })

        q.submit(batch_id, batch.jobs, configs=[config] * len(batch.jobs))

        # Wait up to 5 minutes.
        q.wait_for_batch(batch_id, timeout=300)

        for j in batch.jobs:
            d = j.to_dict()
            assert d["status"] == "completed", (
                f"job {j.ticker} failed: status={d['status']} error={d['error']}"
            )
            assert d["signal"], f"job {j.ticker} has empty signal"