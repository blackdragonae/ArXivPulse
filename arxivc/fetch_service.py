import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


class FetchService:
    """
    Coordinates fetch pipeline state and daily fetch execution.
    """

    def __init__(
        self,
        *,
        storage: Any,
        client_module: Any,
        handle_fetched_papers: Callable[[List[Dict[str, Any]], str], Dict[str, Any]],
    ) -> None:
        self._storage = storage
        self._client = client_module
        self._handle_fetched_papers = handle_fetched_papers
        self._pipeline_lock = threading.Lock()
        self._pipeline_active = False
        self._pipeline_tasks = 0
        self._pipeline_started_at: Optional[str] = None

    def start_pipeline(self) -> bool:
        with self._pipeline_lock:
            if self._pipeline_active:
                return False
            self._pipeline_active = True
            self._pipeline_tasks = 0
            self._pipeline_started_at = datetime.now().isoformat()
            return True

    def end_pipeline(self) -> None:
        with self._pipeline_lock:
            self._pipeline_active = False
            self._pipeline_tasks = 0
            self._pipeline_started_at = None

    def is_pipeline_active(self) -> bool:
        with self._pipeline_lock:
            return bool(self._pipeline_active)

    def get_pipeline_state(self) -> Dict[str, Any]:
        with self._pipeline_lock:
            return {
                "active": bool(self._pipeline_active),
                "tasks": int(self._pipeline_tasks or 0),
                "started_at": self._pipeline_started_at,
            }

    def track_task(self, fn: Callable[..., Any], *args: Any) -> None:
        with self._pipeline_lock:
            self._pipeline_tasks += 1

        def _runner() -> None:
            try:
                fn(*args)
            finally:
                self._task_done()

        threading.Thread(target=_runner, daemon=True).start()

    def _task_done(self) -> None:
        with self._pipeline_lock:
            self._pipeline_tasks = max(0, self._pipeline_tasks - 1)
            if self._pipeline_tasks <= 0:
                self._pipeline_active = False
                self._pipeline_started_at = None

    def run_daily_fetch(
        self, date_str: Optional[str] = None, force: bool = False
    ) -> Dict[str, Any]:
        self._storage.init_db()
        if not date_str:
            date_str = datetime.now().date().isoformat()
        if not force:
            run = self._storage.get_daily_fetch_run(date_str)
            if run and run.get("status") == "success":
                return {"skipped": True, "reason": "already_fetched", "date": date_str}
        if not self.start_pipeline():
            return {"skipped": True, "reason": "fetch_in_progress", "date": date_str}
        try:
            papers = self._client.fetch_papers_by_date(date_str)
            result = self._handle_fetched_papers(papers, date_str)
            self._storage.record_daily_fetch_run(
                date_str,
                status="success",
                fetched=int(result.get("fetched") or 0),
                new_count=int(result.get("new") or 0),
                forced=bool(force),
            )
            result["skipped"] = False
            return result
        except self._client.ArxivRateLimitError as e:
            retry_after = max(1, int(getattr(e, "retry_after_seconds", 60) or 60))
            self._storage.record_daily_fetch_run(
                date_str,
                status="error",
                reason=str(e),
                forced=bool(force),
            )
            self.end_pipeline()
            return {
                "skipped": False,
                "error": str(e),
                "status_code": 429,
                "retry_after_seconds": retry_after,
                "date": date_str,
            }
        except Exception as e:
            self._storage.record_daily_fetch_run(
                date_str,
                status="error",
                reason=str(e),
                forced=bool(force),
            )
            self.end_pipeline()
            return {"skipped": False, "error": str(e), "date": date_str}
