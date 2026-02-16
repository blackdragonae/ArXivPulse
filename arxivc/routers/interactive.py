from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException


def create_interactive_router(
    *,
    storage: Any,
    resolve_paper_by_id: Callable[[str], Optional[Dict[str, Any]]],
    bump_api_cache_epochs: Callable[..., None],
    attach_labels: Callable[[List[Dict[str, Any]]], None],
    download_pdf: Callable[[str], Any],
    background_retrain: Callable[[], Any],
    BookmarkRequestModel: Any,
    RateRequestModel: Any,
    PinRequestModel: Any,
    WeeklyPickRequestModel: Any,
    AuthorRequestModel: Any,
) -> APIRouter:
    """
    Interactive/action routes extracted from server.py.
    Behavior is intentionally preserved while reducing server.py size.
    """
    router = APIRouter()

    @router.post("/api/papers/{paper_id:path}/bookmark")
    def bookmark_paper(paper_id: str, req: BookmarkRequestModel):
        storage.init_db()
        paper = resolve_paper_by_id(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        resolved_id = str(paper.get("id") or paper_id)
        if req.active:
            storage.add_bookmark(resolved_id)
        else:
            storage.remove_bookmark(resolved_id)
        bump_api_cache_epochs("papers")
        return {"success": True}

    @router.post("/api/papers/{paper_id:path}/rate")
    def rate_paper(paper_id: str, req: RateRequestModel, background_tasks: BackgroundTasks):
        print(f"DEBUG: Rate request for paper_id='{paper_id}' status='{req.status}'")
        if req.status not in ["liked", "dismissed"]:
            raise HTTPException(status_code=400, detail="Invalid status")
        storage.init_db()
        paper = resolve_paper_by_id(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        resolved_id = str(paper.get("id") or paper_id)

        storage.update_interaction(resolved_id, req.status)
        bump_api_cache_epochs("papers", "graph")

        if req.status == "liked":
            background_tasks.add_task(download_pdf, resolved_id)
            background_tasks.add_task(background_retrain)

        return {"success": True}

    @router.get("/api/pins")
    def list_pins():
        storage.init_db()
        papers = storage.get_papers_by_status("liked")
        ids = [p.get("id") for p in papers if p.get("id")]
        pin_map = storage.get_pinned_map(ids)
        return pin_map

    @router.post("/api/pins/{paper_id:path}")
    def set_pin_endpoint(paper_id: str, req: PinRequestModel):
        storage.init_db()
        paper = resolve_paper_by_id(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        expires_at = None
        if req.expires_in_days is not None:
            try:
                days = int(req.expires_in_days)
                if days > 0:
                    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
            except Exception:
                expires_at = None
        result = storage.set_pin(paper.get("id"), req.note, expires_at=expires_at)
        bump_api_cache_epochs("papers")
        return result

    @router.delete("/api/pins/{paper_id:path}")
    def remove_pin_endpoint(paper_id: str):
        storage.init_db()
        paper = resolve_paper_by_id(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        ok = storage.remove_pin(paper.get("id"))
        if ok:
            bump_api_cache_epochs("papers")
        return {"success": ok}

    @router.post("/api/papers/{paper_id:path}/weekly-pick")
    def set_weekly_pick_endpoint(paper_id: str, req: WeeklyPickRequestModel):
        storage.init_db()
        paper = resolve_paper_by_id(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        result = storage.set_weekly_pick(paper.get("id"), bool(req.active))
        bump_api_cache_epochs("papers")
        return result

    @router.get("/api/weekly-picks")
    def list_weekly_picks_endpoint(days: int = 7, limit: int = 50):
        storage.init_db()
        picks = storage.list_weekly_picks(days=days, limit=limit)
        attach_labels(picks)
        return {"items": picks, "days": max(1, int(days)), "count": len(picks)}

    @router.get("/api/authors/following")
    def get_followed_authors():
        storage.init_db()
        return storage.get_followed_authors()

    @router.post("/api/authors/follow")
    def follow_author(req: AuthorRequestModel):
        storage.init_db()
        storage.follow_author(req.name)
        return {"success": True}

    @router.post("/api/authors/unfollow")
    def unfollow_author(req: AuthorRequestModel):
        storage.init_db()
        storage.unfollow_author(req.name)
        return {"success": True}

    return router

