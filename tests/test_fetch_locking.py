import time

from arxivc.fetch_service import FetchService


class FakeStorage:
    def __init__(self):
        self.inits = 0
        self.daily_runs = {}
        self.recorded = []

    def init_db(self):
        self.inits += 1

    def get_daily_fetch_run(self, date_str):
        return self.daily_runs.get(date_str)

    def record_daily_fetch_run(self, date_str, **kwargs):
        payload = {"date": date_str, **kwargs}
        self.recorded.append(payload)
        self.daily_runs[date_str] = payload


class FakeClient:
    class ArxivRateLimitError(RuntimeError):
        def __init__(self, message, retry_after_seconds=60):
            self.retry_after_seconds = retry_after_seconds
            super().__init__(message)

    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = []

    def fetch_papers_by_date(self, date_str):
        self.calls.append(date_str)
        if self.mode == "ok":
            return [{"id": "http://arxiv.org/abs/2602.90001v1"}]
        if self.mode == "rate_limit":
            raise self.ArxivRateLimitError("rate limited", retry_after_seconds=19)
        if self.mode == "error":
            raise RuntimeError("fetch failed")
        raise RuntimeError(f"unknown mode: {self.mode}")


def _build_service(mode="ok"):
    storage = FakeStorage()
    client = FakeClient(mode=mode)

    def handle_fetched_papers(papers, batch_date):
        return {"fetched": len(papers), "new": len(papers), "date": batch_date}

    svc = FetchService(
        storage=storage,
        client_module=client,
        handle_fetched_papers=handle_fetched_papers,
    )
    return svc, storage, client


def test_pipeline_start_and_end_state():
    svc, _, _ = _build_service()

    assert svc.start_pipeline() is True
    assert svc.start_pipeline() is False
    state = svc.get_pipeline_state()
    assert state["active"] is True
    assert isinstance(state["started_at"], str)

    svc.end_pipeline()
    state = svc.get_pipeline_state()
    assert state["active"] is False
    assert state["tasks"] == 0
    assert state["started_at"] is None


def test_track_task_releases_pipeline_when_last_task_finishes():
    svc, _, _ = _build_service()
    done = {"value": False}

    def task():
        time.sleep(0.02)
        done["value"] = True

    assert svc.start_pipeline() is True
    svc.track_task(task)
    assert svc.is_pipeline_active() is True

    deadline = time.time() + 1.0
    while time.time() < deadline:
        if done["value"] and not svc.is_pipeline_active():
            break
        time.sleep(0.01)

    assert done["value"] is True
    assert svc.is_pipeline_active() is False


def test_run_daily_fetch_skips_when_pipeline_already_active():
    svc, _, client = _build_service()
    assert svc.start_pipeline() is True

    result = svc.run_daily_fetch(date_str="2026-02-12", force=True)

    assert result["skipped"] is True
    assert result["reason"] == "fetch_in_progress"
    assert result["date"] == "2026-02-12"
    assert client.calls == []


def test_run_daily_fetch_releases_pipeline_on_generic_error():
    svc, storage, _ = _build_service(mode="error")

    result = svc.run_daily_fetch(date_str="2026-02-12", force=True)

    assert result["skipped"] is False
    assert "error" in result
    assert svc.is_pipeline_active() is False
    assert any(row.get("status") == "error" for row in storage.recorded)


def test_run_daily_fetch_rate_limit_sets_retry_and_releases_pipeline():
    svc, storage, _ = _build_service(mode="rate_limit")

    result = svc.run_daily_fetch(date_str="2026-02-12", force=True)

    assert result["skipped"] is False
    assert result["status_code"] == 429
    assert result["retry_after_seconds"] == 19
    assert svc.is_pipeline_active() is False
    assert any(row.get("status") == "error" for row in storage.recorded)


def test_run_daily_fetch_success_records_and_returns_counts():
    svc, storage, client = _build_service(mode="ok")

    result = svc.run_daily_fetch(date_str="2026-02-12", force=True)

    assert result["skipped"] is False
    assert result["fetched"] == 1
    assert result["new"] == 1
    assert result["date"] == "2026-02-12"
    assert client.calls == ["2026-02-12"]
    assert storage.recorded[-1]["status"] == "success"
