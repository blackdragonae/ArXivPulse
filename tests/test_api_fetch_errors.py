from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from arxivc.routers.workflow_actions import create_workflow_actions_router


class FetchRequest(BaseModel):
    max_results: int = 20
    date: Optional[str] = None


class DayRunRequest(BaseModel):
    date: Optional[str] = None
    force: bool = False


class DayRunPresetRequest(BaseModel):
    name: str = "preset"
    description: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


class DayRunPresetUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


class InboxActionRequest(BaseModel):
    kind: str = "alert"
    action: str = "seen"
    alert_id: Optional[int] = None
    follow_id: Optional[str] = None
    digest_id: Optional[int] = None
    paper_id: Optional[str] = None
    arxiv_base_id: Optional[str] = None
    snooze_days: int = 3
    note: Optional[str] = None


class InboxBulkActionItem(BaseModel):
    kind: str
    action: Optional[str] = None
    alert_id: Optional[int] = None
    follow_id: Optional[str] = None
    digest_id: Optional[int] = None
    paper_id: Optional[str] = None
    arxiv_base_id: Optional[str] = None
    snooze_days: Optional[int] = None
    note: Optional[str] = None


class InboxBulkActionRequest(BaseModel):
    action: Optional[str] = None
    snooze_days: int = 3
    note: Optional[str] = None
    items: List[InboxBulkActionItem] = Field(default_factory=list)


class StubRateLimitError(RuntimeError):
    def __init__(self, message: str, retry_after_seconds: int = 60):
        self.retry_after_seconds = int(retry_after_seconds)
        super().__init__(message)


class StubClientModule:
    ArxivRateLimitError = StubRateLimitError

    def __init__(self, mode: str = "ok"):
        self.mode = mode

    def fetch_latest_daily_batch(self):
        if self.mode == "ok":
            return ([{"id": "http://arxiv.org/abs/2602.99991v1"}], "2026-02-12")
        if self.mode == "rate_limit":
            raise self.ArxivRateLimitError("arXiv API returned HTTP 429 (rate limit).", retry_after_seconds=17)
        if self.mode == "timeout":
            raise RuntimeError("arXiv request timed out after 20s (retries=1).")
        raise RuntimeError("unexpected fetch failure")

    def fetch_papers_by_date(self, date_str: str):
        if self.mode == "ok":
            return [{"id": f"http://arxiv.org/abs/{date_str.replace('-', '')}.00001v1"}]
        if self.mode == "rate_limit":
            raise self.ArxivRateLimitError("arXiv API returned HTTP 429 (rate limit).", retry_after_seconds=17)
        if self.mode == "timeout":
            raise RuntimeError("arXiv request timed out after 20s (retries=1).")
        raise RuntimeError("unexpected fetch failure")


class StubStorage:
    def __init__(self):
        self.init_calls = 0

    def init_db(self):
        self.init_calls += 1

    def create_day_run_preset(self, **kwargs):
        return {"id": 1, **kwargs}

    def update_day_run_preset(self, preset_id: int, updates: Dict[str, Any]):
        return {"id": preset_id, **updates}

    def delete_day_run_preset(self, preset_id: int):
        return True

    def get_day_run_preset(self, preset_id: int):
        return {"id": preset_id, "options": {}}

    def mark_day_run_preset_used(self, preset_id: int):
        return True

    def get_day_run_history(self, run_id: int):
        return {"id": run_id, "options": {}}


def _build_test_client(
    *,
    client_mode: str = "ok",
    start_locked: bool = False,
    started_at: Optional[str] = None,
    daily_result: Optional[Dict[str, Any]] = None,
    scheduled_retry_response: Optional[Dict[str, Any]] = None,
    fetch_status_response: Optional[Dict[str, Any]] = None,
):
    storage = StubStorage()
    client_module = StubClientModule(mode=client_mode)
    call_log: List[Dict[str, Any]] = []

    state = {
        "active": bool(start_locked),
        "tasks": 0,
        "started_at": started_at or ("2026-02-16T10:15:00" if start_locked else None),
        "end_calls": 0,
    }

    def fetch_pipeline_state():
        return {
            "active": bool(state["active"]),
            "tasks": int(state["tasks"]),
            "started_at": state["started_at"],
        }

    def start_fetch_pipeline():
        if state["active"]:
            return False
        state["active"] = True
        state["started_at"] = state["started_at"] or "2026-02-16T10:15:00"
        return True

    def end_fetch_pipeline():
        state["active"] = False
        state["tasks"] = 0
        state["started_at"] = None
        state["end_calls"] += 1

    def handle_fetched_papers(papers, batch_date):
        # Keep tests deterministic: release lock immediately after handling.
        end_fetch_pipeline()
        return {"fetched": len(papers), "new": len(papers), "date": batch_date}

    def log_request_timing(event_name, start_ts, **kwargs):
        call_log.append({"event": event_name, "kwargs": kwargs})

    def run_daily_fetch_internal(date_str=None, force=False):
        if daily_result is not None:
            return dict(daily_result)
        return {
            "skipped": False,
            "fetched": 1,
            "new": 1,
            "date": date_str or "2026-02-12",
        }

    def sanitize_day_run_options(options):
        return dict(options or {})

    def run_day_with_idempotency(payload, source):
        return {
            "status": "ok",
            "fetch": {"fetched": 1, "new": 1, "skipped": False},
            "inbox": {"total": 0},
            "date": "2026-02-12",
            "run_id": 1,
            "source": source,
        }

    def apply_inbox_action_internal(req):
        return {"ok": True, "kind": req.kind, "action": req.action}

    def normalize_inbox_kind(kind):
        return str(kind or "").strip().lower()

    def default_inbox_action_for_kind(kind):
        return "seen"

    def schedule_fetch_retry(event: Dict[str, Any]):
        _ = event
        if isinstance(scheduled_retry_response, dict):
            return dict(scheduled_retry_response)
        return None

    def fetch_status_payload():
        if isinstance(fetch_status_response, dict):
            return dict(fetch_status_response)
        return {
            "pipeline": fetch_pipeline_state(),
            "cooldown": {"active": False, "retry_after_seconds": 0, "until": None},
            "retry": {"status": "idle", "active": False, "remaining_seconds": 0},
        }

    app = FastAPI()
    app.include_router(
        create_workflow_actions_router(
            storage=storage,
            client_module=client_module,
            fetch_pipeline_state=fetch_pipeline_state,
            start_fetch_pipeline=start_fetch_pipeline,
            end_fetch_pipeline=end_fetch_pipeline,
            handle_fetched_papers=handle_fetched_papers,
            log_request_timing=log_request_timing,
            run_daily_fetch_internal=run_daily_fetch_internal,
            sanitize_day_run_options=sanitize_day_run_options,
            run_day_with_idempotency=run_day_with_idempotency,
            apply_inbox_action_internal=apply_inbox_action_internal,
            normalize_inbox_kind=normalize_inbox_kind,
            default_inbox_action_for_kind=default_inbox_action_for_kind,
            FetchRequestModel=FetchRequest,
            DayRunRequestModel=DayRunRequest,
            DayRunPresetRequestModel=DayRunPresetRequest,
            DayRunPresetUpdateRequestModel=DayRunPresetUpdateRequest,
            InboxActionRequestModel=InboxActionRequest,
            InboxBulkActionRequestModel=InboxBulkActionRequest,
            schedule_fetch_retry=schedule_fetch_retry,
            fetch_status_payload=fetch_status_payload,
        )
    )

    return TestClient(app), state, client_module, call_log


def test_api_fetch_returns_409_with_started_at_context():
    client, state, _, _ = _build_test_client(
        start_locked=True,
        started_at="2026-02-16T11:22:33",
    )

    response = client.post("/api/fetch", json={"max_results": 20})

    assert response.status_code == 409
    assert "Fetch already running" in response.json()["detail"]
    assert "2026-02-16T11:22:33" in response.json()["detail"]
    assert state["active"] is True


def test_api_fetch_timeout_releases_lock_and_allows_next_request():
    client, state, client_module, _ = _build_test_client(client_mode="timeout")

    first = client.post("/api/fetch", json={"max_results": 20})

    assert first.status_code == 500
    assert "timed out" in first.json()["detail"]
    assert state["active"] is False
    assert state["end_calls"] == 1

    client_module.mode = "ok"
    second = client.post("/api/fetch", json={"max_results": 20})

    assert second.status_code == 200
    assert second.json()["fetched"] == 1


def test_api_fetch_429_includes_retry_after_and_releases_lock():
    client, state, _, _ = _build_test_client(client_mode="rate_limit")

    response = client.post("/api/fetch", json={"max_results": 20})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "17"
    payload = response.json()
    assert payload["retry_after_seconds"] == 17
    assert "429" in payload["detail"]
    assert state["active"] is False
    assert state["end_calls"] == 1


def test_api_fetch_daily_429_passthrough_includes_retry_after_header():
    client, _, _, _ = _build_test_client(
        daily_result={
            "error": "arXiv API returned HTTP 429 (rate limit). Retry in about 33s.",
            "status_code": 429,
            "retry_after_seconds": 33,
            "date": "2026-02-12",
        }
    )

    response = client.post("/api/fetch/daily?force=true")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "33"
    payload = response.json()
    assert payload["retry_after_seconds"] == 33
    assert "429" in payload["detail"]


def test_api_fetch_daily_409_message_is_preserved():
    client, _, _, _ = _build_test_client(
        daily_result={
            "error": "Fetch already running (started at 2026-02-16T10:15:00).",
            "status_code": 409,
            "date": "2026-02-16",
        }
    )

    response = client.post("/api/fetch/daily?force=true")

    assert response.status_code == 409
    assert "Fetch already running" in response.json()["detail"]
    assert "2026-02-16T10:15:00" in response.json()["detail"]


def test_fetch_status_endpoint_exposes_pipeline_and_retry_payload():
    client, _, _, _ = _build_test_client(
        fetch_status_response={
            "pipeline": {"active": False, "tasks": 0, "started_at": None},
            "cooldown": {"active": True, "retry_after_seconds": 12, "until": "2026-02-16T12:00:00"},
            "retry": {"status": "scheduled", "active": True, "remaining_seconds": 17},
        }
    )

    response = client.get("/api/fetch/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cooldown"]["active"] is True
    assert payload["cooldown"]["retry_after_seconds"] == 12
    assert payload["retry"]["status"] == "scheduled"
    assert payload["retry"]["remaining_seconds"] == 17


def test_api_fetch_429_includes_retry_schedule_payload_when_available():
    client, _, _, _ = _build_test_client(
        client_mode="rate_limit",
        scheduled_retry_response={
            "status": "scheduled",
            "active": True,
            "remaining_seconds": 21,
        },
    )

    response = client.post("/api/fetch", json={"max_results": 20})

    assert response.status_code == 429
    payload = response.json()
    assert payload["retry_after_seconds"] == 17
    assert payload["retry_scheduled"] is True
    assert payload["retry"]["status"] == "scheduled"
    assert payload["retry"]["remaining_seconds"] == 21
