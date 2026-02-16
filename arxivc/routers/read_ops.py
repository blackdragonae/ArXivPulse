from datetime import datetime, timedelta
from queue import Queue
from threading import Lock
from typing import Any, Callable, Dict, Mapping, Optional

from fastapi import APIRouter


def create_read_ops_router(
    *,
    storage: Any,
    api_cache_get: Callable[[str, int, str], Optional[Any]],
    api_cache_set: Callable[[str, Any, str], None],
    scheduler_leader_payload: Callable[[], Dict[str, Any]],
    scheduler_agent_ops: Callable[[], Dict[str, Any]],
    job_queue_ops: Callable[[], Dict[str, Any]],
    parse_iso_datetime: Callable[[Optional[str]], Optional[datetime]],
    job_lock: Lock,
    jobs_ref: Mapping[str, Dict[str, Any]],
    job_queue: Queue,
    fetch_pipeline_state: Callable[[], Dict[str, Any]],
) -> APIRouter:
    """
    Read-only/diagnostic routes extracted from server.py.
    Keep behavior stable while reducing the main module surface area.
    """
    router = APIRouter()

    @router.get("/api/daily-fetch/runs")
    def list_daily_fetch_runs(limit: int = 30, date_from: Optional[str] = None, date_to: Optional[str] = None):
        storage.init_db()
        return storage.list_daily_fetch_runs(limit=limit, date_from=date_from, date_to=date_to)

    @router.get("/api/system/scheduler-leader")
    def get_scheduler_leader():
        """
        Debug endpoint: returns current scheduler leader lock state.
        Useful when running multiple API workers/processes.
        """
        storage.init_db()
        return scheduler_leader_payload()

    @router.get("/api/system/scheduler-ops")
    def get_scheduler_ops():
        """Ops dashboard payload: leader health + due agents + queue stats."""
        storage.init_db()
        leader = scheduler_leader_payload()
        return {
            "leader": leader,
            "agents": scheduler_agent_ops(),
            "jobs": job_queue_ops(),
        }

    @router.get("/api/stats")
    def get_stats():
        storage.init_db()
        cached = api_cache_get("stats", ttl_seconds=60, epoch_key="stats")
        if cached is not None:
            return cached
        data = storage.get_daily_stats()
        api_cache_set("stats", data, epoch_key="stats")
        return data

    @router.get("/api/graph")
    async def get_graph():
        storage.init_db()
        cached = api_cache_get("graph", ttl_seconds=60, epoch_key="graph")
        if cached is not None:
            return cached
        data = storage.get_graph_data()
        api_cache_set("graph", data, epoch_key="graph")
        return data

    @router.get("/health")
    def health():
        db_status = storage.db_healthcheck()
        embedding_status = storage.get_embedding_status()
        fts_status = storage.get_fts_status()
        with job_lock:
            jobs = list(jobs_ref.values())
        queued = sum(1 for j in jobs if j.get("status") == "queued")
        running = sum(1 for j in jobs if j.get("status") == "running")
        failed = sum(1 for j in jobs if j.get("status") == "failed")
        completed = sum(1 for j in jobs if j.get("status") == "completed")
        payload = {
            "status": "ok" if db_status.get("ok") else "degraded",
            "db": db_status,
            "embeddings": embedding_status,
            "fts": fts_status,
            "jobs": {
                "queued": queued,
                "running": running,
                "failed": failed,
                "completed": completed,
                "queue_size": job_queue.qsize(),
            },
            "fetch_pipeline": fetch_pipeline_state(),
        }
        return payload

    @router.get("/api/changes")
    def get_change_summary(since: Optional[str] = None):
        storage.init_db()
        now = datetime.now()
        since_dt = parse_iso_datetime(since) if since else None
        if not since_dt:
            since_dt = now - timedelta(days=1)
        payload = storage.get_changes_since(since_dt.isoformat())
        payload["since"] = since_dt.isoformat()
        payload["as_of"] = now.isoformat()
        return payload

    return router

