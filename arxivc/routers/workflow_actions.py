import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse


def create_workflow_actions_router(
    *,
    storage: Any,
    client_module: Any,
    fetch_pipeline_state: Callable[[], Dict[str, Any]],
    start_fetch_pipeline: Callable[[], bool],
    end_fetch_pipeline: Callable[[], None],
    handle_fetched_papers: Callable[[List[Dict[str, Any]], str], Dict[str, Any]],
    log_request_timing: Callable[..., None],
    run_daily_fetch_internal: Callable[[Optional[str], bool], Dict[str, Any]],
    sanitize_day_run_options: Callable[[Optional[Dict[str, Any]]], Dict[str, Any]],
    run_day_with_idempotency: Callable[[Any, str], Dict[str, Any]],
    apply_inbox_action_internal: Callable[[Any], Dict[str, Any]],
    normalize_inbox_kind: Callable[[Optional[str]], str],
    default_inbox_action_for_kind: Callable[[str], str],
    FetchRequestModel: Any,
    DayRunRequestModel: Any,
    DayRunPresetRequestModel: Any,
    DayRunPresetUpdateRequestModel: Any,
    InboxActionRequestModel: Any,
    InboxBulkActionRequestModel: Any,
    schedule_fetch_retry: Optional[
        Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]
    ] = None,
    fetch_status_payload: Optional[Callable[[], Dict[str, Any]]] = None,
) -> APIRouter:
    """
    Write/action workflow routes extracted from server.py.
    Behavior is intentionally preserved while reducing server.py size.
    """
    router = APIRouter()

    @router.get("/api/fetch/status")
    def get_fetch_status():
        payload = {
            "pipeline": fetch_pipeline_state(),
            "cooldown": {},
            "retry": {},
        }
        if fetch_status_payload:
            try:
                status_payload = fetch_status_payload() or {}
                if isinstance(status_payload, dict):
                    payload.update(status_payload)
            except Exception as e:
                payload["error"] = str(e)
        return payload

    @router.post("/api/fetch")
    def api_fetch(req: FetchRequestModel, background_tasks: BackgroundTasks):
        _ = background_tasks
        storage.init_db()
        start_ts = time.perf_counter()
        if not start_fetch_pipeline():
            started_at = (fetch_pipeline_state() or {}).get("started_at")
            detail = "Fetch already running."
            if started_at:
                detail = f"Fetch already running (started at {started_at})."
            raise HTTPException(status_code=409, detail=detail)
        try:
            if req.date:
                papers = client_module.fetch_papers_by_date(req.date)
                batch_date = req.date
            else:
                # Ignore req.max_results, we fetch the whole day day
                papers, batch_date = client_module.fetch_latest_daily_batch()
            result = handle_fetched_papers(papers, batch_date)
            if req.date:
                storage.record_daily_fetch_run(
                    batch_date,
                    status="success",
                    fetched=int(result.get("fetched") or 0),
                    new_count=int(result.get("new") or 0),
                    forced=True,
                )
            log_request_timing(
                "request.fetch",
                start_ts,
                status="ok",
                fetched=int(result.get("fetched") or 0),
                new_count=int(result.get("new") or 0),
                date=batch_date,
            )
            return result
        except client_module.ArxivRateLimitError as e:
            end_fetch_pipeline()
            retry_after = max(1, int(getattr(e, "retry_after_seconds", 60) or 60))
            retry_payload = None
            if schedule_fetch_retry:
                retry_payload = schedule_fetch_retry(
                    {
                        "mode": "date" if req.date else "latest",
                        "date": req.date,
                        "force": bool(req.date),
                        "status_code": 429,
                        "retry_after_seconds": retry_after,
                        "error": str(e),
                        "reason": "api_fetch_rate_limit",
                    }
                )
            log_request_timing(
                "request.fetch",
                start_ts,
                status="error",
                error=str(e),
                http_status=429,
                retry_after=retry_after,
                retry_scheduled=bool(retry_payload),
            )
            content: Dict[str, Any] = {
                "detail": str(e),
                "retry_after_seconds": retry_after,
            }
            if retry_payload is not None:
                content["retry"] = retry_payload
                content["retry_scheduled"] = bool(retry_payload.get("active"))
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content=content,
            )
        except Exception as e:
            end_fetch_pipeline()
            retry_payload = None
            if schedule_fetch_retry:
                retry_payload = schedule_fetch_retry(
                    {
                        "mode": "date" if req.date else "latest",
                        "date": req.date,
                        "force": bool(req.date),
                        "status_code": 500,
                        "error": str(e),
                        "reason": "api_fetch_error",
                    }
                )
            log_request_timing(
                "request.fetch",
                start_ts,
                status="error",
                error=str(e),
                retry_scheduled=bool(retry_payload),
            )
            if retry_payload is not None:
                return JSONResponse(
                    status_code=500,
                    content={
                        "detail": str(e),
                        "retry": retry_payload,
                        "retry_scheduled": bool(retry_payload.get("active")),
                        "retry_after_seconds": int(
                            retry_payload.get("remaining_seconds") or 0
                        ),
                    },
                )
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/fetch/daily")
    def run_daily_fetch(date: Optional[str] = None, force: bool = False):
        """
        Runs the daily fetch job for a specific date (YYYY-MM-DD).
        If no date is provided, uses today's date. Mon-Fri guard applies unless force=True.
        """
        start_ts = time.perf_counter()
        if date:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except Exception:
                raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

        if not force:
            if date:
                try:
                    date_dt = datetime.strptime(date, "%Y-%m-%d")
                    if date_dt.weekday() >= 5:
                        return {"skipped": True, "reason": "weekend"}
                except Exception:
                    raise HTTPException(
                        status_code=400, detail="date must be YYYY-MM-DD"
                    )
            else:
                now = datetime.now()
                if now.weekday() >= 5:
                    return {"skipped": True, "reason": "weekend"}

        result = run_daily_fetch_internal(date, force)
        if "error" in result:
            status_code = int(result.get("status_code") or 500)
            retry_after = int(result.get("retry_after_seconds") or 0)
            retry_payload = None
            if schedule_fetch_retry:
                retry_payload = schedule_fetch_retry(
                    {
                        "mode": "date",
                        "date": result.get("date") or date,
                        "force": bool(force),
                        "status_code": status_code,
                        "retry_after_seconds": retry_after,
                        "error": str(result.get("error") or ""),
                        "reason": "api_fetch_daily_error",
                    }
                )
            log_request_timing(
                "request.fetch_daily",
                start_ts,
                status="error",
                error=str(result.get("error")),
                date=result.get("date"),
                forced=bool(force),
                http_status=status_code,
                retry_after=retry_after or None,
                retry_scheduled=bool(retry_payload),
            )
            if status_code == 429 and retry_after > 0:
                content: Dict[str, Any] = {
                    "detail": result["error"],
                    "retry_after_seconds": retry_after,
                }
                if retry_payload is not None:
                    content["retry"] = retry_payload
                    content["retry_scheduled"] = bool(retry_payload.get("active"))
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    content=content,
                )
            if retry_payload is not None:
                return JSONResponse(
                    status_code=status_code,
                    content={
                        "detail": str(result["error"]),
                        "retry": retry_payload,
                        "retry_scheduled": bool(retry_payload.get("active")),
                        "retry_after_seconds": int(
                            retry_payload.get("remaining_seconds") or 0
                        ),
                    },
                )
            raise HTTPException(status_code=status_code, detail=result["error"])
        log_request_timing(
            "request.fetch_daily",
            start_ts,
            status="ok" if not result.get("skipped") else "skipped",
            fetched=int(result.get("fetched") or 0),
            new_count=int(result.get("new") or 0),
            date=result.get("date"),
            reason=result.get("reason"),
            forced=bool(force),
        )
        return result

    @router.post("/api/day/run")
    def run_day(req: Optional[DayRunRequestModel] = None):
        storage.init_db()
        start_ts = time.perf_counter()
        payload = req or DayRunRequestModel()
        response = run_day_with_idempotency(payload, "api")
        fetch_result = response.get("fetch") or {}
        log_request_timing(
            "request.day_run",
            start_ts,
            status=response.get("status")
            or ("skipped" if fetch_result.get("skipped") else "ok"),
            fetched=int(fetch_result.get("fetched") or 0),
            new_count=int(fetch_result.get("new") or 0),
            date=response.get("date"),
            inbox_total=int(response.get("inbox", {}).get("total") or 0),
            run_id=int(response.get("run_id") or 0),
        )
        return response

    @router.post("/api/day/presets")
    def create_day_run_preset(req: DayRunPresetRequestModel):
        storage.init_db()
        name = str(req.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        options = sanitize_day_run_options(req.options or {})
        created = storage.create_day_run_preset(
            name=name,
            description=(str(req.description or "").strip() or None),
            options=options,
        )
        if not created:
            raise HTTPException(status_code=500, detail="Failed to create preset")
        return created

    @router.put("/api/day/presets/{preset_id}")
    def update_day_run_preset(preset_id: int, req: DayRunPresetUpdateRequestModel):
        storage.init_db()
        updates: Dict[str, Any] = {}
        if req.name is not None:
            updates["name"] = str(req.name or "").strip() or "Preset"
        if req.description is not None:
            updates["description"] = str(req.description or "").strip()
        if req.options is not None:
            updates["options"] = sanitize_day_run_options(req.options)
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")
        updated = storage.update_day_run_preset(int(preset_id), updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Preset not found")
        return updated

    @router.delete("/api/day/presets/{preset_id}")
    def delete_day_run_preset(preset_id: int):
        storage.init_db()
        ok = storage.delete_day_run_preset(int(preset_id))
        return {"success": bool(ok)}

    @router.post("/api/day/presets/{preset_id}/run")
    def run_day_preset(preset_id: int):
        storage.init_db()
        preset = storage.get_day_run_preset(int(preset_id))
        if not preset:
            raise HTTPException(status_code=404, detail="Preset not found")
        options = preset.get("options") or {}
        payload = DayRunRequestModel(**sanitize_day_run_options(options))
        response = run_day_with_idempotency(payload, f"preset:{int(preset_id)}")
        storage.mark_day_run_preset_used(int(preset_id))
        response["preset_id"] = int(preset_id)
        return response

    @router.post("/api/day/run/{run_id}/retry")
    def retry_day_run(run_id: int):
        storage.init_db()
        record = storage.get_day_run_history(run_id)
        if not record:
            raise HTTPException(status_code=404, detail="Run history not found")
        options = record.get("options") or {}
        if not isinstance(options, dict):
            options = {}
        payload = DayRunRequestModel(**sanitize_day_run_options(options))
        response = run_day_with_idempotency(payload, f"retry:{int(run_id)}")
        response["retry_of"] = int(run_id)
        return response

    @router.post("/api/inbox/action")
    def apply_unified_inbox_action(req: InboxActionRequestModel):
        storage.init_db()
        start_ts = time.perf_counter()
        try:
            result = apply_inbox_action_internal(req)
            log_request_timing(
                "request.inbox.action",
                start_ts,
                status="ok",
                kind=str(getattr(req, "kind", "") or ""),
                action=str(getattr(req, "action", "") or ""),
            )
            return result
        except HTTPException as e:
            log_request_timing(
                "request.inbox.action",
                start_ts,
                status="error",
                error=str(e.detail),
                http_status=int(e.status_code),
                kind=str(getattr(req, "kind", "") or ""),
                action=str(getattr(req, "action", "") or ""),
            )
            raise
        except Exception as e:
            log_request_timing(
                "request.inbox.action",
                start_ts,
                status="error",
                error=str(e),
                http_status=500,
                kind=str(getattr(req, "kind", "") or ""),
                action=str(getattr(req, "action", "") or ""),
            )
            raise

    @router.post("/api/inbox/bulk-action")
    def apply_unified_inbox_bulk_action(req: InboxBulkActionRequestModel):
        storage.init_db()
        start_ts = time.perf_counter()
        items = list(req.items or [])
        if not items:
            log_request_timing(
                "request.inbox.bulk_action",
                start_ts,
                status="error",
                error="items is required",
                http_status=400,
            )
            raise HTTPException(status_code=400, detail="items is required")
        if len(items) > 500:
            log_request_timing(
                "request.inbox.bulk_action",
                start_ts,
                status="error",
                error="items max length is 500",
                http_status=400,
            )
            raise HTTPException(status_code=400, detail="items max length is 500")

        shared_action = str(req.action or "").strip().lower() or None
        shared_snooze = max(1, min(int(req.snooze_days or 3), 90))
        shared_note = req.note
        success_count = 0
        failure_count = 0
        results: List[Dict[str, Any]] = []

        for item in items:
            kind = normalize_inbox_kind(item.kind)
            action = (
                str(item.action or shared_action or default_inbox_action_for_kind(kind))
                .strip()
                .lower()
            )
            snooze_days = max(1, min(int(item.snooze_days or shared_snooze), 90))
            try:
                payload = InboxActionRequestModel(
                    kind=kind,
                    action=action,
                    alert_id=item.alert_id,
                    follow_id=item.follow_id,
                    digest_id=item.digest_id,
                    paper_id=item.paper_id,
                    arxiv_base_id=item.arxiv_base_id,
                    snooze_days=snooze_days,
                    note=item.note or shared_note,
                )
                result = apply_inbox_action_internal(payload)
                success_count += 1
                results.append(
                    {"success": True, "kind": kind, "action": action, "result": result}
                )
            except HTTPException as e:
                failure_count += 1
                results.append(
                    {
                        "success": False,
                        "kind": kind,
                        "action": action,
                        "status_code": int(e.status_code),
                        "error": str(e.detail),
                    }
                )
            except Exception as e:
                failure_count += 1
                results.append(
                    {
                        "success": False,
                        "kind": kind,
                        "action": action,
                        "status_code": 500,
                        "error": str(e),
                    }
                )

        payload = {
            "success_count": success_count,
            "failure_count": failure_count,
            "total": len(items),
            "results": results,
        }
        log_request_timing(
            "request.inbox.bulk_action",
            start_ts,
            status="error" if failure_count else "ok",
            total=len(items),
            success_count=success_count,
            failure_count=failure_count,
            http_status=207 if failure_count else 200,
        )
        return payload

    return router
