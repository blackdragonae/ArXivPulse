from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Response, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import os
import glob
import json
import copy
import hashlib
import re
import difflib
import threading
import math
import uuid
import queue
import html
import zipfile
import tempfile
import time
import shutil
import sqlite3
import requests
from . import client, storage, ranker, downloader, config, indexer, ai_service, citation_service, embeddings, export_service, pdf_service, agent_service
from .ai_service import extract_text_from_pdf, simple_chat_logic, generate_brief, describe_image

app = FastAPI()

# Input models
class RateRequest(BaseModel):
    status: str  # 'liked' or 'dismissed'

class FetchRequest(BaseModel):
    max_results: int = 20
    date: Optional[str] = None

class AuthorRequest(BaseModel):
    name: str

class ConfigRequest(BaseModel):
    categories: List[str]
    keywords: List[str]
    vault_path: Optional[str] = ""
    warmup_models: bool = False
    notion_token: Optional[str] = None
    notion_database_id: Optional[str] = None

class InboxRuleRequest(BaseModel):
    name: str
    enabled: bool = True
    action: str = "label"  # label|dismiss (papers) / seen|reviewed|dismiss|snooze|done|read (inbox)
    label: Optional[str] = None
    keywords: List[str] = []
    authors: List[str] = []
    venues: List[str] = []
    scope: str = "papers"  # papers or inbox
    target_kind: Optional[str] = None  # alert|version_update|follow_up|digest
    snooze_days: int = 3
    min_novelty: float = 0.0
    quiet_hours_start: Optional[int] = None
    quiet_hours_end: Optional[int] = None

class PinRequest(BaseModel):
    note: Optional[str] = None
    expires_in_days: Optional[int] = None

class BookmarkRequest(BaseModel):
    active: bool

class ReadingStatusRequest(BaseModel):
    status: str
    progress: Optional[int] = None

class ReadingPlanGenerateRequest(BaseModel):
    total_minutes: int = 60
    max_items: int = 6
    budget_mode: str = "balanced"  # balanced | focus | sprint | deep
    include_new: bool = True
    include_liked: bool = True
    include_bookmarked: bool = True
    refresh: bool = True

class ReadingPlanActionRequest(BaseModel):
    paper_id: str
    action: str  # done | defer | undo_done | undefer
    defer_days: int = 1
    reason: Optional[str] = None

class VersionUpdateActionRequest(BaseModel):
    action: str  # reviewed | snooze | dismiss | clear
    paper_id: Optional[str] = None
    arxiv_base_id: Optional[str] = None
    snooze_days: int = 3
    note: Optional[str] = None

class InboxActionRequest(BaseModel):
    kind: str  # alert | version_update | follow_up | digest
    action: str
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
    items: List[InboxBulkActionItem] = []

class InboxRulesRunRequest(BaseModel):
    scope: str = "papers"  # papers|inbox|all
    dry_run: bool = False
    limit: int = 200

class FollowUpSnoozeRequest(BaseModel):
    days: int = 3

class DayRunRequest(BaseModel):
    date: Optional[str] = None
    force: bool = False
    weekend_policy: str = "skip"  # skip or run
    run_fetch: bool = True
    run_rules: bool = True
    run_reading_plan: bool = True
    run_inbox_refresh: bool = True
    run_inbox_rules_scope: str = "all"  # papers|inbox|all
    refresh_reading_plan: bool = True  # backward-compatible alias for run_reading_plan
    version_scope: str = "watchlist"
    version_days: int = 30

class DayRunPresetRequest(BaseModel):
    name: str
    description: Optional[str] = None
    options: Optional[Dict[str, Any]] = None

class DayRunPresetUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    options: Optional[Dict[str, Any]] = None

class NotesRequest(BaseModel):
    notes: Optional[str] = None
    last_updated_at: Optional[str] = None

class FollowUpRequest(BaseModel):
    days: int = 7
    note: Optional[str] = None

class LinkRequest(BaseModel):
    related_id: str
    relation: Optional[str] = None
    note: Optional[str] = None

class NotesImportRequest(BaseModel):
    items: List[Dict[str, Any]] = []

class NotesTemplatesRequest(BaseModel):
    templates: List[Dict[str, Any]] = []

class NotesAutoSummaryRequest(BaseModel):
    style: str = "concise"  # concise | structured | deep

class ViewShareRequest(BaseModel):
    name: Optional[str] = None
    status: str = "new"
    date_filter: Optional[str] = None
    smart_sort: bool = False
    favorites_sort: Optional[str] = None
    search_mode: Optional[str] = None
    search_query: Optional[str] = None
    rank_profile: Optional[Dict[str, float]] = None
    limit: Optional[int] = 80

class AlertSettingsRequest(BaseModel):
    citation_threshold: int = 25
    max_results: int = 100

class CombinedSettingsRequest(BaseModel):
    categories: List[str]
    keywords: List[str]
    vault_path: Optional[str] = ""
    citation_threshold: int = 25
    max_results: int = 100
    warmup_models: bool = False
    notion_token: Optional[str] = None
    notion_database_id: Optional[str] = None

class MarkAlertsRequest(BaseModel):
    ids: Optional[List[int]] = None

class SavedSearchRequest(BaseModel):
    name: str
    query: str
    cadence: str = "daily"  # daily | weekly
    max_results: int = 8
    mode: str = "global"  # global | semantic | local
    source_paper_id: Optional[str] = None

class ReproJobRequest(BaseModel):
    paper_id: str

class CompareRequest(BaseModel):
    paper_ids: List[str]

class DigestGenerateRequest(BaseModel):
    cadence: str = "daily"  # daily | weekly
    force: bool = True
    max_items: int = 10

class FolderScheduleRequest(BaseModel):
    cadence: str = "daily"
    max_items: int = 10
    enabled: bool = True

class FolderDigestRunRequest(BaseModel):
    cadence: Optional[str] = None
    max_items: Optional[int] = None

class LineageRequest(BaseModel):
    topic: str
    max_nodes: int = 20

class SurveyRequest(BaseModel):
    topic: str

class ChatRequest(BaseModel):
    paper_id: str
    query: str
    image: Optional[str] = None # Base64 image context

class ShareSelectionRequest(BaseModel):
    paper_ids: List[str]

class CitationLinksRequest(BaseModel):
    paper_ids: List[str]

class CommentRequest(BaseModel):
    author: Optional[str] = None
    body: str

class WeeklyPickRequest(BaseModel):
    active: bool = True

class NotionExportRequest(BaseModel):
    paper_ids: List[str]


class CrossPaperQARequest(BaseModel):
    paper_ids: List[str]
    question: str
    top_k: int = 5


class RelatedGraphRequest(BaseModel):
    paper_ids: List[str]
    limit_per_anchor: int = 8
    min_score: float = 0.68


class AssignmentRequest(BaseModel):
    assignee: str
    due_in_days: Optional[int] = None
    due_at: Optional[str] = None
    status: str = "todo"
    note: Optional[str] = None


class AssignmentUpdateRequest(BaseModel):
    assignee: Optional[str] = None
    due_at: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None

def normalize_paper_id(paper_id: str) -> str:
    """Normalizes short arXiv ids into the DB's URL-style id format."""
    if paper_id.startswith("http"):
        return paper_id
    return f"http://arxiv.org/abs/{paper_id}"

def normalize_paper_ids(paper_ids: List[str]) -> List[str]:
    """Normalizes, trims, and deduplicates paper ids while preserving order."""
    if not paper_ids:
        return []
    seen: set[str] = set()
    normalized: List[str] = []
    for pid in paper_ids:
        if not pid:
            continue
        norm = normalize_paper_id(str(pid).strip())
        if not norm or norm in seen:
            continue
        normalized.append(norm)
        seen.add(norm)
    return normalized

def find_local_pdf_path(paper_id: str) -> Optional[str]:
    """Finds a downloaded PDF path for a given paper id/url."""
    short_id = paper_id.split('/')[-1]
    potential_paths = [
        os.path.join("downloads", f"{short_id}.pdf"),
        os.path.join("downloads", f"{short_id}v1.pdf"),
    ]
    for path in potential_paths:
        if os.path.exists(path):
            return path

    matches = glob.glob(f"downloads/*{short_id}*.pdf")
    return matches[0] if matches else None

def _build_alert_rows_for_papers(papers: List[Dict]) -> List[Dict]:
    """Creates alert rows (keyword/author/citation) for candidate papers."""
    if not papers:
        return []

    settings = storage.get_alert_settings()
    citation_threshold = int(settings.get("citation_threshold", 25))
    followed_authors = set(storage.get_followed_authors())
    keywords = [k.lower() for k in config.KEYWORDS if k]

    rows = []
    for p in papers:
        paper_id = p.get("id")
        if not paper_id:
            continue
        title = p.get("title", "")
        summary = p.get("summary", "")
        text = f"{title} {summary}".lower()
        authors = p.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]

        matched_keywords = [kw for kw in keywords if kw in text]
        if matched_keywords:
            rows.append({
                "paper_id": paper_id,
                "alert_type": "keyword",
                "message": f"Keyword match: {', '.join(matched_keywords[:3])}",
            })

        matched_authors = [a for a in authors if a in followed_authors]
        if matched_authors:
            rows.append({
                "paper_id": paper_id,
                "alert_type": "author",
                "message": f"Followed author: {', '.join(matched_authors[:2])}",
            })

        citation_count = int(p.get("citation_count") or 0)
        if citation_count >= citation_threshold:
            rows.append({
                "paper_id": paper_id,
                "alert_type": "citation",
                "message": f"High citation count: {citation_count}",
            })

    return rows

def generate_alerts_for_papers(papers: List[Dict]) -> int:
    rows = _build_alert_rows_for_papers(papers)
    if not rows:
        return 0
    return storage.create_alerts(rows)

SAVED_SEARCH_SCHEDULER_INTERVAL_SEC = 300
SAVED_SEARCH_FOLLOWER_POLL_SEC = 15
SAVED_SEARCH_LOCK_NAME = "saved_search_scheduler"
SAVED_SEARCH_LOCK_TTL_SEC = max(600, SAVED_SEARCH_SCHEDULER_INTERVAL_SEC * 3)
CITATION_REFRESH_LOCK_NAME = "citation_refresh"
CITATION_REFRESH_TTL_SEC = 3600
CITATION_REFRESH_INTERVAL_SEC = 7 * 24 * 3600
CITATION_REFRESH_POLL_SEC = 3600
DAILY_FETCH_LOCK_NAME = "daily_fetch"
DAILY_FETCH_TTL_SEC = 1800
MENTION_RE = re.compile(r'@([A-Za-z0-9_.-]{2,})')
DAILY_FETCH_POLL_SEC = 300
DAILY_FETCH_START_HOUR = 0
DAILY_FETCH_START_MINUTE = 5
SHARE_TOKEN_TTL_DAYS = storage.SHARE_TOKEN_DEFAULT_TTL_DAYS
SHARE_TOKEN_CLEANUP_LOCK_NAME = "share_token_cleanup"
SHARE_TOKEN_CLEANUP_TTL_SEC = 3600
SHARE_TOKEN_CLEANUP_POLL_SEC = 6 * 3600
AUTO_DIGEST_INTERVALS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}
_SAVED_SEARCH_RUN_LOCK = threading.Lock()
_ACTIVE_SEARCH_RUNS = set()
_SCHEDULER_STOP_EVENT = threading.Event()
_SCHEDULER_OWNER_ID = f"pid-{os.getpid()}-{uuid.uuid4().hex[:8]}"
_RANKER_TRAIN_LOCK = threading.Lock()

JOB_WORKER_COUNT = 2
JOB_MAX_ATTEMPTS = 2
JOB_DEFAULT_DURATION_SEC = {
    "compare_matrix": 45.0,
    "reproducibility": 35.0,
    "discover": 40.0,
    "benchmark_extract": 50.0,
}
JOB_DURATION_HISTORY_LIMIT = 50
_JOB_QUEUE: "queue.Queue[str]" = queue.Queue()
_JOB_STOP_EVENT = threading.Event()
_JOB_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOB_DURATIONS: Dict[str, List[float]] = {}
_API_CACHE_LOCK = threading.Lock()
_API_CACHE: Dict[str, Dict[str, Any]] = {}
_API_CACHE_EPOCHS: Dict[str, int] = {
    "papers": 0,
    "stats": 0,
    "graph": 0,
}
_PAGED_RANK_CACHE_LOCK = threading.Lock()
_PAGED_RANK_CACHE: Dict[str, Dict[str, Any]] = {}
_PAGED_RANK_CACHE_TTL_SECONDS = 45
_FETCH_PIPELINE_LOCK = threading.Lock()
_FETCH_PIPELINE_ACTIVE = False
_FETCH_PIPELINE_TASKS = 0
_FETCH_PIPELINE_STARTED_AT: Optional[str] = None
_DAY_RUN_EXEC_LOCK = threading.Lock()
_DAY_RUN_IDEMPOTENCY_LOCK = threading.Lock()
_DAY_RUN_ACTIVE_SIGNATURE: Optional[str] = None
_DAY_RUN_IDEMPOTENCY_CACHE: Dict[str, Dict[str, Any]] = {}
_DAY_RUN_IDEMPOTENCY_TTL_SECONDS = 20
_NOVELTY_BACKFILL_LOCK = threading.Lock()
_NOVELTY_BACKFILL_PENDING: Dict[str, float] = {}
_NOVELTY_BACKFILL_ACTIVE = False
_INBOX_RULE_DIAG_CACHE_LOCK = threading.Lock()
_INBOX_RULE_DIAG_CACHE: Dict[str, Any] = {}
_INBOX_RULE_DIAG_CACHE_TTL_SECONDS = 45
SLOW_REQUEST_THRESHOLD_SEC = 1.5
LOG_DIR = "logs"
LOG_FILE_PREFIX = "events"
LOG_RETENTION_DAYS = 7
READING_PLAN_CACHE_TTL_SECONDS = 24 * 3600
READING_PLAN_LAST_OPTIONS_KEY = "reading_plan:today:last_options"
NOTES_TEMPLATES_CACHE_KEY = "notes:templates:v1"
DEFAULT_NOTES_TEMPLATES: List[Dict[str, str]] = [
    {
        "id": "reading",
        "name": "Reading Notes",
        "body": "## TL;DR\n- \n\n## Key Ideas\n- \n\n## Evidence\n- \n\n## Questions\n- \n\n## Next Actions\n- ",
    },
    {
        "id": "replication",
        "name": "Replication Checklist",
        "body": "## Setup\n- Data source:\n- Code repository:\n- Environment:\n\n## Repro Steps\n1. \n2. \n3. \n\n## Risks\n- \n\n## Result Log\n- ",
    },
    {
        "id": "meeting",
        "name": "Team Discussion",
        "body": "## Decision\n- \n\n## Pros\n- \n\n## Cons\n- \n\n## Open Questions\n- \n\n## Owner & Due Date\n- ",
    },
]
_LOG_LOCK = threading.Lock()
_LOG_CURRENT_DATE = None
_LOG_FILE_PATH = None

def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None

def _enqueue_novelty_backfill(scores: Optional[Dict[str, float]]) -> None:
    global _NOVELTY_BACKFILL_ACTIVE
    if not isinstance(scores, dict) or not scores:
        return

    with _NOVELTY_BACKFILL_LOCK:
        for pid, value in scores.items():
            key = str(pid or "").strip()
            if not key:
                continue
            try:
                _NOVELTY_BACKFILL_PENDING[key] = float(value or 0.0)
            except Exception:
                _NOVELTY_BACKFILL_PENDING[key] = 0.0
        should_start = not _NOVELTY_BACKFILL_ACTIVE and bool(_NOVELTY_BACKFILL_PENDING)
        if should_start:
            _NOVELTY_BACKFILL_ACTIVE = True

    if not should_start:
        return

    def _worker():
        global _NOVELTY_BACKFILL_ACTIVE
        try:
            while True:
                with _NOVELTY_BACKFILL_LOCK:
                    if not _NOVELTY_BACKFILL_PENDING:
                        _NOVELTY_BACKFILL_ACTIVE = False
                        return
                    batch = dict(_NOVELTY_BACKFILL_PENDING)
                    _NOVELTY_BACKFILL_PENDING.clear()
                try:
                    storage.update_novelty_scores(batch)
                except Exception:
                    pass
        finally:
            with _NOVELTY_BACKFILL_LOCK:
                _NOVELTY_BACKFILL_ACTIVE = False

    threading.Thread(target=_worker, daemon=True).start()

def _clear_inbox_rule_diag_cache() -> None:
    with _INBOX_RULE_DIAG_CACHE_LOCK:
        _INBOX_RULE_DIAG_CACHE.clear()

def _agent_is_due(agent: Dict, now: datetime) -> bool:
    cadence = (agent.get("cadence") or "daily").lower()
    every = timedelta(days=7 if cadence == "weekly" else 1)
    base = _parse_iso_datetime(agent.get("last_run_at")) or _parse_iso_datetime(agent.get("created_at"))
    if not base:
        return True
    return (now - base) >= every

def _get_scheduler_leader_payload() -> Dict[str, Any]:
    lock = storage.get_scheduler_lock(SAVED_SEARCH_LOCK_NAME)
    now = datetime.now()

    if not lock:
        return {
            "lock_name": SAVED_SEARCH_LOCK_NAME,
            "has_leader": False,
            "owner_id": None,
            "heartbeat_at": None,
            "heartbeat_age_seconds": None,
            "stale": None,
            "self_owner_id": _SCHEDULER_OWNER_ID,
            "self_is_leader": False,
            "scheduler_interval_seconds": SAVED_SEARCH_SCHEDULER_INTERVAL_SEC,
            "lock_ttl_seconds": SAVED_SEARCH_LOCK_TTL_SEC,
            "now": now.isoformat(),
        }

    age_seconds = None
    try:
        hb_dt = datetime.fromisoformat(lock["heartbeat_at"])
        age_seconds = round((now - hb_dt).total_seconds(), 3)
    except Exception:
        pass

    return {
        "lock_name": lock["name"],
        "has_leader": True,
        "owner_id": lock["owner_id"],
        "heartbeat_at": lock["heartbeat_at"],
        "heartbeat_age_seconds": age_seconds,
        "stale": (age_seconds is not None and age_seconds > SAVED_SEARCH_LOCK_TTL_SEC),
        "self_owner_id": _SCHEDULER_OWNER_ID,
        "self_is_leader": lock["owner_id"] == _SCHEDULER_OWNER_ID,
        "scheduler_interval_seconds": SAVED_SEARCH_SCHEDULER_INTERVAL_SEC,
        "lock_ttl_seconds": SAVED_SEARCH_LOCK_TTL_SEC,
        "now": now.isoformat(),
    }

def _run_discover_pipeline() -> Dict[str, Any]:
    """
    Discover new papers based on user's liked papers.
    Uses LLM to generate queries -> Global Search -> Filter Existing.
    """
    storage.init_db()

    liked = storage.get_papers_by_status('liked')
    if not liked:
        liked = storage.get_papers_by_status('new')[:5]

    try:
        queries = ai_service.generate_discovery_queries(liked)
        print(f"Discovery Queries: {queries}")
    except Exception as e:
        print(f"AI Error during discovery: {e}")
        queries = ["cat:cs.AI"]

    candidates: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    query_hits_by_id: Dict[str, List[str]] = {}
    rank_hint_by_id: Dict[str, int] = {}
    for q in queries:
        try:
            results = client.search_archive(q, max_results=5)
            for idx, p in enumerate(results):
                pid = str(p.get("id") or "").strip()
                if not pid:
                    continue
                query_hits_by_id.setdefault(pid, [])
                if q not in query_hits_by_id[pid]:
                    query_hits_by_id[pid].append(q)
                prev_rank = rank_hint_by_id.get(pid)
                rank_hint_by_id[pid] = min(prev_rank, idx + 1) if prev_rank is not None else (idx + 1)
                if pid not in seen_ids:
                    candidates.append(p)
                    seen_ids.add(pid)
        except Exception as search_err:
            print(f"Search Error for {q}: {search_err}")

    filtered_results = []
    if candidates:
        candidate_ids = [c['id'] for c in candidates]
        existing = storage.get_papers_by_ids(candidate_ids)
        existing_ids = set(e['id'] for e in existing)
        for c in candidates:
            if c['id'] not in existing_ids:
                filtered_results.append(c)

    keywords = [str(k).strip().lower() for k in (config.KEYWORDS or []) if str(k).strip()]
    followed_authors = set(storage.get_followed_authors() or [])
    enriched: List[Dict[str, Any]] = []
    for paper in filtered_results:
        pid = str(paper.get("id") or "").strip()
        title = str(paper.get("title") or "")
        summary = str(paper.get("summary") or "")
        text = f"{title} {summary}".lower()
        authors = paper.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        kw_hits = [kw for kw in keywords if kw in text][:4]
        author_hits = [a for a in authors if a in followed_authors][:3]
        query_hits = query_hits_by_id.get(pid) or []
        rank_hint = rank_hint_by_id.get(pid) or 6

        reasons: List[str] = []
        if query_hits:
            reasons.append(f"Matched discovery query: {query_hits[0]}")
        if kw_hits:
            reasons.append(f"Keyword overlap: {', '.join(kw_hits[:3])}")
        if author_hits:
            reasons.append(f"Followed author: {', '.join(author_hits[:2])}")
        if not reasons:
            reasons.append("Semantically related to your recent library interests.")

        score = 0.0
        score += max(0.0, 2.0 - (float(rank_hint) - 1.0) * 0.25)
        score += min(1.2, float(len(query_hits)) * 0.35)
        score += min(1.0, float(len(kw_hits)) * 0.25)
        score += min(0.8, float(len(author_hits)) * 0.4)

        paper_copy = dict(paper)
        paper_copy["recommendation_score"] = round(score, 3)
        paper_copy["recommendation_reasons"] = reasons
        paper_copy["discovery_queries"] = query_hits
        enriched.append(paper_copy)

    enriched.sort(
        key=lambda row: (
            float(row.get("recommendation_score") or 0.0),
            str(row.get("published") or ""),
        ),
        reverse=True,
    )
    return {"papers": enriched[:20], "queries": queries}

def _compute_compare_matrix(paper_ids: List[str]) -> Dict[str, Any]:
    """Compare matrix for 2-6 selected papers with caching."""
    if len(paper_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 papers.")
    if len(paper_ids) > 6:
        raise HTTPException(status_code=400, detail="Select at most 6 papers for matrix view.")

    storage.init_db()
    papers = storage.get_papers_by_ids(paper_ids)
    if len(papers) < 2:
        raise HTTPException(status_code=400, detail="Could not find enough selected papers.")

    canonical = sorted(
        [
            {
                "id": p.get("id", ""),
                "title": p.get("title", ""),
                "summary": p.get("summary", ""),
                "published": p.get("published", ""),
            }
            for p in papers
        ],
        key=lambda x: x["id"],
    )
    signature_src = "|".join(
        f"{p['id']}::{p['title']}::{p['summary']}" for p in canonical
    )
    cache_key = f"matrix:{hashlib.sha1(signature_src.encode('utf-8')).hexdigest()}"
    cached = storage.get_ai_cache(cache_key, max_age_seconds=24 * 3600)
    if cached:
        return {"result": cached, "count": len(papers), "cached": True}

    matrix = ai_service.compare_papers_matrix(papers)
    storage.set_ai_cache(cache_key, matrix)
    return {"result": matrix, "count": len(papers), "cached": False}

def _compute_compare_diff(paper_ids: List[str]) -> Dict[str, Any]:
    """Side-by-side diff for exactly 2 papers (method/dataset/results)."""
    if len(paper_ids) != 2:
        raise HTTPException(status_code=400, detail="Select exactly 2 papers.")

    storage.init_db()
    papers = storage.get_papers_by_ids(paper_ids)
    if len(papers) != 2:
        raise HTTPException(status_code=400, detail="Could not find both papers.")

    def to_struct(paper: Dict[str, Any]) -> Dict[str, Any]:
        struct = ai_service.extract_paper_structure(paper)
        return {
            "id": paper.get("id"),
            "title": paper.get("title"),
            "summary": paper.get("summary"),
            "structure": struct,
        }

    a = to_struct(papers[0])
    b = to_struct(papers[1])
    fields = ["method", "dataset", "results"]
    diffs = {f: (a["structure"].get(f) or "").strip() != (b["structure"].get(f) or "").strip() for f in fields}
    return {"papers": [a, b], "diffs": diffs}

def _run_cross_paper_qa(
    paper_ids: List[str],
    question: str,
    top_k: int = 5,
) -> Dict[str, Any]:
    storage.init_db()
    clean_question = str(question or "").strip()
    if not clean_question:
        raise HTTPException(status_code=400, detail="question is required.")

    normalized_ids = normalize_paper_ids(paper_ids or [])
    if len(normalized_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 papers.")

    paper_rows = storage.get_papers_by_ids(normalized_ids)
    paper_map = {p.get("id"): p for p in paper_rows if p.get("id")}
    papers = [paper_map[pid] for pid in normalized_ids if pid in paper_map]
    if len(papers) < 2:
        raise HTTPException(status_code=404, detail="Not enough selected papers found.")

    question_tokens = {
        tok.lower()
        for tok in re.findall(r"[a-zA-Z0-9][\\w-]{2,}", clean_question)
        if len(tok) >= 3
    }
    scored: List[Dict[str, Any]] = []
    for paper in papers:
        title = str(paper.get("title") or "")
        summary = str(paper.get("summary") or "")
        text = f"{title} {summary}".lower()
        token_hits = sum(1 for tok in question_tokens if tok in text) if question_tokens else 0
        recency_bonus = 0.0
        pub = str(paper.get("published") or "")
        if pub:
            recency_bonus = 0.25
        score = float(token_hits) + recency_bonus
        first_sentence = summary.split(".")[0].strip() if summary else ""
        scored.append(
            {
                "paper_id": paper.get("id"),
                "title": title or str(paper.get("id") or "Paper"),
                "published": pub,
                "score": round(score, 4),
                "snippet": first_sentence or summary[:320],
                "summary": summary,
            }
        )

    scored.sort(key=lambda row: (float(row.get("score") or 0.0), str(row.get("published") or "")), reverse=True)
    source_cap = max(1, min(int(top_k or 5), 12, len(scored)))
    selected_sources = scored[:source_cap]

    signature_payload = {
        "ids": [str(p.get("paper_id") or "") for p in selected_sources],
        "q": clean_question,
        "top_k": source_cap,
    }
    cache_key = "cross_qa:" + hashlib.sha1(json.dumps(signature_payload, sort_keys=True).encode("utf-8")).hexdigest()
    cached = storage.get_ai_cache(cache_key, max_age_seconds=3 * 24 * 3600)
    if cached:
        try:
            payload = json.loads(cached)
            if isinstance(payload, dict):
                payload["cached"] = True
                return payload
        except Exception:
            pass

    context_lines: List[str] = []
    for idx, source in enumerate(selected_sources, start=1):
        context_lines.append(
            "\n".join(
                [
                    f"[S{idx}] ID: {source.get('paper_id')}",
                    f"Title: {source.get('title')}",
                    f"Published: {source.get('published')}",
                    f"Abstract: {source.get('summary')}",
                ]
            )
        )
    prompt = (
        "You are an academic research assistant. Answer the question using ONLY the provided sources.\n"
        "Cite supporting claims inline with source tags like [S1], [S2].\n"
        "If evidence is weak or missing, say so explicitly.\n\n"
        f"Question: {clean_question}\n\n"
        "Sources:\n"
        + "\n\n".join(context_lines)
        + "\n\nAnswer:"
    )
    answer = (ai_service.query_ollama(prompt, "", timeout=150) or "").strip()
    if not answer:
        fallback_points: List[str] = []
        for idx, source in enumerate(selected_sources[:4], start=1):
            fallback_points.append(
                f"- [S{idx}] {source.get('title')}: {source.get('snippet') or 'No abstract snippet available.'}"
            )
        answer = (
            "AI response unavailable. Here are the most relevant selected-paper snippets:\n\n"
            + "\n".join(fallback_points)
        )

    payload = {
        "question": clean_question,
        "answer": answer,
        "count_selected": len(papers),
        "count_sources": len(selected_sources),
        "sources": [
            {
                "tag": f"S{idx}",
                "paper_id": source.get("paper_id"),
                "title": source.get("title"),
                "published": source.get("published"),
                "relevance_score": source.get("score"),
                "snippet": source.get("snippet"),
            }
            for idx, source in enumerate(selected_sources, start=1)
        ],
        "cached": False,
    }
    try:
        storage.set_ai_cache(cache_key, json.dumps(payload))
    except Exception:
        pass
    return payload

def _compute_reproducibility_scorecard(paper_id: str) -> Dict[str, Any]:
    storage.init_db()
    normalized_id = normalize_paper_id(paper_id)
    paper = storage.get_paper_by_id(normalized_id) or storage.get_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found.")

    signature = hashlib.sha1(
        f"{paper.get('id','')}|{paper.get('title','')}|{paper.get('summary','')}".encode("utf-8")
    ).hexdigest()
    cache_key = f"repro:{signature}"
    cached = storage.get_ai_cache(cache_key, max_age_seconds=7 * 24 * 3600)
    if cached:
        try:
            payload = json.loads(cached)
            payload["cached"] = True
            return payload
        except Exception:
            pass

    payload = ai_service.generate_reproducibility_scorecard(paper)
    payload["cached"] = False
    storage.set_ai_cache(cache_key, json.dumps(payload))
    return payload

_LINEAGE_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "using", "based", "via",
    "model", "models", "method", "methods", "paper", "study", "approach", "towards", "under",
    "into", "their", "our", "new", "learning", "neural", "network", "networks", "analysis",
}

def _dedupe_papers_by_id(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    seen = set()
    for p in papers:
        pid = p.get("id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(p)
    return out

def _collect_digest_candidates(cadence: str) -> List[Dict[str, Any]]:
    cadence = (cadence or "daily").lower()
    new_papers = storage.get_papers_by_status("new")
    liked = storage.get_papers_by_status("liked")

    if cadence == "weekly":
        pool = _dedupe_papers_by_id(new_papers + liked)
        pool = sorted(pool, key=lambda p: p.get("published", ""), reverse=True)
        return pool[:250]

    pool = sorted(new_papers, key=lambda p: p.get("published", ""), reverse=True)
    return pool[:120]

def _digest_is_due(cadence: str, now: Optional[datetime] = None) -> bool:
    cadence = (cadence or "daily").lower()
    if cadence not in AUTO_DIGEST_INTERVALS:
        cadence = "daily"
    last = storage.get_last_digest_created_at(cadence)
    if not last:
        return True
    last_dt = _parse_iso_datetime(last)
    if not last_dt:
        return True
    now_dt = now or datetime.now()
    return (now_dt - last_dt) >= AUTO_DIGEST_INTERVALS[cadence]

def _generate_digest_run(cadence: str = "daily", max_items: int = 10, persist: bool = True) -> Dict[str, Any]:
    storage.init_db()
    cadence = (cadence or "daily").lower()
    if cadence not in {"daily", "weekly"}:
        cadence = "daily"

    candidates = _collect_digest_candidates(cadence)
    digest = ai_service.generate_interest_digest(
        candidates,
        user_keywords=config.KEYWORDS,
        followed_authors=storage.get_followed_authors(),
        cadence=cadence,
        max_items=max_items,
    )
    digest["cadence"] = cadence

    if persist:
        digest_id = storage.create_digest_run(
            cadence=digest.get("cadence", cadence),
            title=digest.get("title", f"{cadence.title()} Digest"),
            summary=digest.get("summary", ""),
            items=digest.get("items", []),
        )
        saved = storage.get_digest_run(digest_id)
        if saved:
            return saved
    return digest

def _collect_folder_digest_candidates(folder: Dict[str, Any], limit: int = 120) -> List[Dict[str, Any]]:
    if not folder or folder.get("mode") != "sql":
        return []
    query = folder.get("query", "")
    if not query:
        return []
    limit = max(20, min(int(limit or 120), 500))
    search_results = storage.search_papers(query, limit=limit)
    ids = [r.get("id") for r in search_results if r.get("id")]
    if not ids:
        return []
    papers = storage.get_papers_by_ids(ids)
    paper_map = {p.get("id"): p for p in papers}
    ordered = [paper_map.get(pid) for pid in ids if paper_map.get(pid)]
    ordered = _attach_version_metadata(ordered, dedupe_latest=False)
    _attach_version_notes(ordered)
    _attach_match_reasons(ordered)
    return ordered

def _folder_digest_is_due(schedule: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    if not schedule:
        return False
    if not schedule.get("enabled", 1):
        return False
    cadence = (schedule.get("cadence") or "daily").lower()
    every = timedelta(days=7 if cadence == "weekly" else 1)
    base = _parse_iso_datetime(schedule.get("last_run_at")) or _parse_iso_datetime(schedule.get("created_at"))
    now_dt = now or datetime.now()
    if not base:
        return True
    return now_dt >= (base + every)

def _generate_folder_digest_run(
    folder: Dict[str, Any],
    cadence: str = "daily",
    max_items: int = 10,
    persist: bool = True,
) -> Dict[str, Any]:
    storage.init_db()
    cadence = (cadence or "daily").lower()
    if cadence not in {"daily", "weekly"}:
        cadence = "daily"
    max_items = max(3, min(int(max_items or 10), 30))

    candidates = _collect_folder_digest_candidates(folder, limit=max(120, max_items * 15))
    digest = ai_service.generate_interest_digest(
        candidates,
        user_keywords=config.KEYWORDS,
        followed_authors=storage.get_followed_authors(),
        cadence=cadence,
        max_items=max_items,
    )
    digest["cadence"] = cadence
    digest["title"] = digest.get("title") or f"{folder.get('name', 'Collection')} Digest"

    if persist:
        digest_id = storage.create_digest_run(
            cadence=digest.get("cadence", cadence),
            title=digest.get("title", "Collection Digest"),
            summary=digest.get("summary", ""),
            items=digest.get("items", []),
            source_type="folder",
            source_id=str(folder.get("id")),
            source_name=str(folder.get("name", "")),
        )
        saved = storage.get_digest_run(digest_id)
        if saved:
            return saved
    return digest

def _compute_benchmark_table(paper_ids: List[str]) -> Dict[str, Any]:
    if len(paper_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 papers for benchmark extraction.")
    if len(paper_ids) > 8:
        raise HTTPException(status_code=400, detail="Select at most 8 papers for benchmark extraction.")

    storage.init_db()
    papers = storage.get_papers_by_ids(paper_ids)
    if len(papers) < 2:
        raise HTTPException(status_code=400, detail="Could not find enough selected papers.")

    canonical = sorted(
        [
            {
                "id": p.get("id", ""),
                "title": p.get("title", ""),
                "summary": p.get("summary", ""),
                "published": p.get("published", ""),
            }
            for p in papers
        ],
        key=lambda x: x["id"],
    )
    signature_src = "|".join(f"{p['id']}::{p['title']}::{p['summary']}" for p in canonical)
    cache_key = f"bench:{hashlib.sha1(signature_src.encode('utf-8')).hexdigest()}"
    cached = storage.get_ai_cache(cache_key, max_age_seconds=24 * 3600)
    if cached:
        try:
            payload = json.loads(cached)
            payload["cached"] = True
            payload["count"] = len(papers)
            return payload
        except Exception:
            pass

    payload = ai_service.extract_benchmark_table(papers)
    payload["cached"] = False
    payload["count"] = len(papers)
    storage.set_ai_cache(cache_key, json.dumps(payload))
    return payload

def _lineage_tokenize(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    return {t for t in tokens if len(t) >= 3 and t not in _LINEAGE_STOPWORDS}

def _lineage_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / max(1, union)

def _compute_method_lineage(topic: str, max_nodes: int = 20) -> Dict[str, Any]:
    storage.init_db()
    topic = (topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required.")

    max_nodes = max(3, min(int(max_nodes), 40))
    topic_tokens = _lineage_tokenize(topic)

    try:
        hits = storage.search_full_text(topic, limit=max_nodes * 8)
    except Exception:
        hits = []
    ids = [h.get("id") for h in hits if h.get("id")]
    candidates = storage.get_papers_by_ids(ids) if ids else []
    if not candidates:
        candidates = _dedupe_papers_by_id(
            storage.get_papers_by_status("new")[: max_nodes * 4] +
            storage.get_papers_by_status("liked")[: max_nodes * 3]
        )

    if not candidates:
        return {"topic": topic, "nodes": [], "edges": [], "chains": []}

    def _relevance_score(p: Dict[str, Any]) -> float:
        text = f"{p.get('title', '')} {p.get('summary', '')}"
        tokens = _lineage_tokenize(text)
        overlap = len(tokens & topic_tokens)
        recency_boost = 0.0
        pdate = str(p.get("published") or "")
        pdt = _parse_iso_datetime(pdate) or _parse_iso_datetime(pdate[:19])
        if pdt:
            age_days = max(0.0, (datetime.now() - pdt).total_seconds() / 86400.0)
            recency_boost = max(0.0, 2.0 - (age_days / 180.0))
        return (2.5 * overlap) + recency_boost

    ranked = sorted(candidates, key=_relevance_score, reverse=True)
    selected = _dedupe_papers_by_id(ranked)[:max_nodes]
    selected = sorted(selected, key=lambda p: p.get("published", ""))

    nodes = []
    token_map: Dict[str, set[str]] = {}
    for idx, p in enumerate(selected):
        pid = str(p.get("id") or "")
        text = f"{p.get('title', '')} {p.get('summary', '')}"
        tok = _lineage_tokenize(text)
        token_map[pid] = tok
        nodes.append(
            {
                "id": pid,
                "title": p.get("title", ""),
                "published": str(p.get("published", ""))[:10],
                "authors": (p.get("authors") or [])[:3],
                "index": idx,
            }
        )

    edges = []
    incoming = set()
    for i in range(1, len(nodes)):
        curr = nodes[i]
        curr_id = curr["id"]
        curr_tokens = token_map.get(curr_id, set())
        best_parent = None
        best_score = 0.0
        search_start = max(0, i - 10)
        for j in range(search_start, i):
            prev = nodes[j]
            prev_id = prev["id"]
            prev_tokens = token_map.get(prev_id, set())
            score = _lineage_similarity(curr_tokens, prev_tokens)
            score += 0.03 * len((curr_tokens & topic_tokens) & (prev_tokens & topic_tokens))
            if score > best_score:
                best_score = score
                best_parent = prev

        if best_parent and best_score >= 0.08:
            edge = {
                "source": best_parent["id"],
                "target": curr_id,
                "score": round(best_score, 3),
                "relation": "builds_on",
            }
            edges.append(edge)
            incoming.add(curr_id)

    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for e in edges:
        by_source.setdefault(e["source"], []).append(e)
    for edge_list in by_source.values():
        edge_list.sort(key=lambda e: e["score"], reverse=True)

    node_by_id = {n["id"]: n for n in nodes}
    roots = [n["id"] for n in nodes if n["id"] not in incoming]
    chains = []
    used = set()

    for root in roots:
        chain_ids = []
        current = root
        seen_local = set()
        while current and current not in seen_local:
            seen_local.add(current)
            chain_ids.append(current)
            nxts = by_source.get(current, [])
            current = nxts[0]["target"] if nxts else None

        if len(chain_ids) >= 2:
            chain_payload = []
            for idx, nid in enumerate(chain_ids):
                phase = "improvement"
                if idx == 0:
                    phase = "ancestor"
                elif idx == len(chain_ids) - 1:
                    phase = "latest"
                n = node_by_id[nid]
                chain_payload.append(
                    {
                        "id": n["id"],
                        "title": n["title"],
                        "published": n["published"],
                        "phase": phase,
                    }
                )
                used.add(nid)
            chains.append(chain_payload)

    chains.sort(key=len, reverse=True)
    standalone = []
    for n in nodes:
        if n["id"] in used:
            continue
        standalone.append(
            [
                {
                    "id": n["id"],
                    "title": n["title"],
                    "published": n["published"],
                    "phase": "latest",
                }
            ]
        )

    return {
        "topic": topic,
        "nodes": nodes,
        "edges": edges,
        "chains": chains + standalone[:10],
    }

def _split_arxiv_version(paper_id: str) -> tuple[str, int]:
    pid = str(paper_id or "")
    if not pid:
        return "", 0
    is_url = pid.startswith("http")
    base_pid = pid
    version = 1
    segment = pid.split("/")[-1]
    match = re.search(r"(v(\d+))$", segment)
    if match:
        version = int(match.group(2))
        base_segment = segment[: -len(match.group(1))]
        if is_url:
            base_pid = pid[: -len(segment)] + base_segment
        else:
            base_pid = base_segment
    return base_pid, version

def _attach_version_metadata(papers: List[Dict[str, Any]], dedupe_latest: bool = False) -> List[Dict[str, Any]]:
    if not papers:
        return papers

    # Populate normalized version fields from DB columns when available.
    for p in papers:
        base_id = p.get("arxiv_base_id")
        ver = p.get("arxiv_version")
        if not base_id:
            base_id, parsed_ver = _split_arxiv_version(p.get("id"))
            if not ver:
                ver = parsed_ver
        try:
            ver_int = int(ver or 1)
        except Exception:
            ver_int = 1
        p["arxiv_base_id"] = base_id
        p["arxiv_version"] = max(1, ver_int)

    if not dedupe_latest:
        return papers

    max_version_in_list: Dict[str, int] = {}
    max_published_in_list: Dict[str, str] = {}
    for p in papers:
        base_id = p.get("arxiv_base_id") or ""
        if not base_id:
            continue
        ver = int(p.get("arxiv_version") or 1)
        pub = str(p.get("published", "") or "")
        prev_ver = max_version_in_list.get(base_id)
        if prev_ver is None or ver > prev_ver:
            max_version_in_list[base_id] = ver
            max_published_in_list[base_id] = pub
        elif ver == prev_ver and pub > max_published_in_list.get(base_id, ""):
            max_published_in_list[base_id] = pub

    filtered: List[Dict[str, Any]] = []
    for p in papers:
        base_id = p.get("arxiv_base_id") or ""
        ver = int(p.get("arxiv_version") or 1)
        if base_id:
            if ver != max_version_in_list.get(base_id, ver):
                continue
            if str(p.get("published", "") or "") != max_published_in_list.get(base_id, ""):
                continue
        filtered.append(p)

    return filtered


def _attach_version_notes(papers: List[Dict[str, Any]]) -> None:
    if not papers:
        return
    base_ids = [str(p.get("arxiv_base_id") or "") for p in papers if p.get("arxiv_base_id")]
    if not base_ids:
        return
    versions_by_base = storage.get_versions_by_base_ids(base_ids)
    for p in papers:
        base_id = str(p.get("arxiv_base_id") or "")
        if not base_id:
            p.pop("version_note", None)
            continue
        try:
            ver = int(p.get("arxiv_version") or 1)
        except Exception:
            ver = 1
        prior = [v for v in versions_by_base.get(base_id, []) if int(v) < ver]
        if prior:
            p["version_note"] = f"Updated to v{ver} (was v{max(prior)})"
        else:
            p.pop("version_note", None)


def _compare_structure_fields(
    from_structure: Dict[str, Any],
    to_structure: Dict[str, Any],
    fields: Optional[List[str]] = None,
) -> List[str]:
    names = fields or ["problem", "method", "dataset", "results", "limitations"]
    changed: List[str] = []
    for name in names:
        before = str((from_structure or {}).get(name) or "").strip()
        after = str((to_structure or {}).get(name) or "").strip()
        if before != after:
            changed.append(name)
    return changed


def _attach_version_change_fields(papers: List[Dict[str, Any]]) -> None:
    if not papers:
        return
    base_ids = [str(p.get("arxiv_base_id") or "") for p in papers if p.get("arxiv_base_id")]
    if not base_ids:
        for p in papers:
            p["version_changed_fields"] = []
            p["version_changed_count"] = 0
            p["version_latest_available"] = False
        return

    families = storage.get_papers_by_base_ids(base_ids)
    families = _attach_version_metadata(families, dedupe_latest=False)
    by_base: Dict[str, List[Dict[str, Any]]] = {}
    for row in families:
        base = str(row.get("arxiv_base_id") or "")
        if not base:
            continue
        by_base.setdefault(base, []).append(row)
    for base, rows in by_base.items():
        rows.sort(key=_version_sort_key, reverse=True)
        by_base[base] = rows

    paper_by_id = {str(p.get("id") or ""): p for p in papers if p.get("id")}
    compare_pairs: List[tuple[str, Dict[str, Any], Dict[str, Any], bool]] = []
    needed_ids: Dict[str, Dict[str, Any]] = {}
    for p in papers:
        pid = str(p.get("id") or "")
        base = str(p.get("arxiv_base_id") or "")
        if not pid or not base:
            p["version_changed_fields"] = []
            p["version_changed_count"] = 0
            p["version_latest_available"] = False
            continue
        family = by_base.get(base) or []
        if len(family) < 2:
            p["version_changed_fields"] = []
            p["version_changed_count"] = 0
            p["version_latest_available"] = False
            continue

        current_version = _paper_version_number(p)
        family_versions = [_paper_version_number(row) for row in family]
        max_version = max(family_versions)
        current_row = next((row for row in family if str(row.get("id") or "") == pid), None)
        if not current_row:
            current_row = next((row for row in family if _paper_version_number(row) == current_version), None)
        if not current_row:
            p["version_changed_fields"] = []
            p["version_changed_count"] = 0
            p["version_latest_available"] = False
            continue

        target_row = None
        latest_available = current_version < max_version
        if latest_available:
            target_row = next((row for row in family if _paper_version_number(row) == max_version), None)
        else:
            prior_versions = [v for v in family_versions if v < current_version]
            if prior_versions:
                prev = max(prior_versions)
                target_row = next((row for row in family if _paper_version_number(row) == prev), None)
        if not target_row:
            p["version_changed_fields"] = []
            p["version_changed_count"] = 0
            p["version_latest_available"] = bool(latest_available)
            continue

        compare_pairs.append((pid, current_row, target_row, latest_available))
        needed_ids[str(current_row.get("id"))] = current_row
        needed_ids[str(target_row.get("id"))] = target_row

    if needed_ids:
        structures = _ensure_structures_for_papers(list(needed_ids.values()), refresh=False)
    else:
        structures = {}

    for pid, current_row, target_row, latest_available in compare_pairs:
        current_id = str(current_row.get("id") or "")
        target_id = str(target_row.get("id") or "")
        if latest_available:
            from_struct = structures.get(current_id) or current_row.get("structure") or {}
            to_struct = structures.get(target_id) or target_row.get("structure") or {}
        else:
            # Latest row compared against previous row.
            from_struct = structures.get(target_id) or target_row.get("structure") or {}
            to_struct = structures.get(current_id) or current_row.get("structure") or {}
        if not isinstance(from_struct, dict):
            from_struct = {}
        if not isinstance(to_struct, dict):
            to_struct = {}
        changed = _compare_structure_fields(from_struct, to_struct)
        paper = paper_by_id.get(pid)
        if not paper:
            continue
        paper["version_changed_fields"] = changed
        paper["version_changed_count"] = len(changed)
        paper["version_latest_available"] = bool(latest_available)

    for p in papers:
        if "version_changed_fields" not in p:
            p["version_changed_fields"] = []
            p["version_changed_count"] = 0
            p["version_latest_available"] = False


def _paper_version_number(paper: Dict[str, Any]) -> int:
    try:
        return max(1, int(paper.get("arxiv_version") or 1))
    except Exception:
        return max(1, int(_split_arxiv_version(str(paper.get("id") or ""))[1] or 1))


def _version_sort_key(paper: Dict[str, Any]) -> tuple[int, str]:
    return (_paper_version_number(paper), str(paper.get("published") or ""))


def _get_version_family_for_paper(paper: Dict[str, Any]) -> List[Dict[str, Any]]:
    base_id = str(paper.get("arxiv_base_id") or _split_arxiv_version(paper.get("id"))[0] or "")
    if not base_id:
        return [paper]
    rows = storage.get_papers_by_base_ids([base_id])
    if not rows:
        return [paper]
    rows = _attach_version_metadata(rows, dedupe_latest=False)
    rows.sort(key=_version_sort_key, reverse=True)
    return rows


def _ensure_structures_for_papers(
    papers: List[Dict[str, Any]],
    refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    structures: Dict[str, Dict[str, Any]] = {}
    updates: List[tuple[str, Dict[str, Any]]] = []
    for paper in papers or []:
        pid = str(paper.get("id") or "")
        if not pid:
            continue
        existing = paper.get("structure")
        if isinstance(existing, str):
            try:
                existing = json.loads(existing)
            except Exception:
                existing = None
        if isinstance(existing, dict) and existing and not refresh:
            structures[pid] = existing
            continue
        try:
            structure = ai_service.extract_paper_structure(paper)
        except Exception:
            structure = {}
        if not isinstance(structure, dict):
            structure = {}
        structures[pid] = structure
        updates.append((pid, structure))

    if updates:
        updated = storage.update_paper_structures(updates)
        if updated > 0:
            _bump_api_cache_epochs("papers")
    return structures


def _resolve_version_base_id(arxiv_base_id: Optional[str], paper_id: Optional[str]) -> str:
    base = str(arxiv_base_id or "").strip()
    if base:
        return base
    pid = str(paper_id or "").strip()
    if not pid:
        return ""
    paper = _resolve_paper_by_id(pid)
    if paper:
        return str(paper.get("arxiv_base_id") or _split_arxiv_version(paper.get("id"))[0] or "")
    return str(_split_arxiv_version(pid)[0] or "")


def _version_update_state_active(state: Optional[Dict[str, Any]], on_date: str) -> bool:
    if not isinstance(state, dict):
        return True
    status = str(state.get("status") or "").strip().lower()
    snooze_until = str(state.get("snooze_until") or "").strip()
    if status in {"reviewed", "dismissed"}:
        return False
    if status == "snoozed" and snooze_until and snooze_until >= on_date:
        return False
    return True


def _build_version_updates_payload(
    since: Optional[str] = None,
    scope: str = "watchlist",
    limit: int = 100,
    include_triaged: bool = False,
    count_only: bool = False,
) -> Dict[str, Any]:
    lim = max(1, min(int(limit or 100), 300))
    scope_key = (scope or "watchlist").lower()
    if scope_key not in {"watchlist", "liked", "bookmarked", "new"}:
        raise HTTPException(status_code=400, detail="scope must be one of: watchlist, liked, bookmarked, new")

    since_dt = _parse_iso_datetime(since)
    if since and since_dt is None:
        try:
            since_dt = datetime.strptime(since, "%Y-%m-%d")
        except Exception:
            raise HTTPException(status_code=400, detail="since must be ISO datetime or YYYY-MM-DD")

    def _empty_payload() -> Dict[str, Any]:
        return {
            "scope": scope_key,
            "since": since_dt.isoformat() if since_dt else None,
            "count": 0,
            "active_count": 0,
            "triaged_count": 0,
            "total_count": 0,
            "items": [],
        }

    def _load_scope_rows(name: str) -> List[Dict[str, Any]]:
        if name == "liked":
            return storage.get_papers_by_status("liked")
        if name == "new":
            rows, _ = storage.get_papers_page_by_status(
                status="new",
                limit=500,
                offset=0,
                dedupe_latest=True,
                include_total=False,
            )
            return rows
        if name == "bookmarked":
            rows, _ = storage.get_bookmarked_papers_page(
                limit=5000,
                offset=0,
                dedupe_latest=False,
                include_total=False,
            )
            return rows
        return []

    if scope_key == "watchlist":
        merged: Dict[str, Dict[str, Any]] = {}
        for row in _load_scope_rows("liked") + _load_scope_rows("bookmarked"):
            pid = str(row.get("id") or "")
            if not pid:
                continue
            existing = merged.get(pid)
            if not existing or _version_sort_key(row) > _version_sort_key(existing):
                merged[pid] = row
        tracked_rows = list(merged.values())
    else:
        tracked_rows = _load_scope_rows(scope_key)

    tracked_rows = _attach_version_metadata(tracked_rows, dedupe_latest=False)
    tracked_by_base: Dict[str, Dict[str, Any]] = {}
    for row in tracked_rows:
        base = str(row.get("arxiv_base_id") or "")
        if not base:
            continue
        existing = tracked_by_base.get(base)
        if not existing or _version_sort_key(row) > _version_sort_key(existing):
            tracked_by_base[base] = row

    base_ids = list(tracked_by_base.keys())
    if not base_ids:
        return _empty_payload()

    today_iso = datetime.now().date().isoformat()
    triage_map = storage.get_version_update_state_map(base_ids, on_date=today_iso)
    family_rows = _attach_version_metadata(storage.get_papers_by_base_ids(base_ids), dedupe_latest=False)
    latest_by_base: Dict[str, Dict[str, Any]] = {}
    for row in family_rows:
        base = str(row.get("arxiv_base_id") or "")
        if not base:
            continue
        existing = latest_by_base.get(base)
        if not existing or _version_sort_key(row) > _version_sort_key(existing):
            latest_by_base[base] = row

    needed_rows: Dict[str, Dict[str, Any]] = {}
    pairs: List[tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    for base, tracked in tracked_by_base.items():
        latest = latest_by_base.get(base)
        if not latest:
            continue
        tracked_ver = _paper_version_number(tracked)
        latest_ver = _paper_version_number(latest)
        if latest_ver <= tracked_ver:
            continue
        if since_dt is not None:
            latest_pub = _parse_iso_datetime(str(latest.get("published") or ""))
            if latest_pub is None:
                try:
                    latest_pub = datetime.strptime(str(latest.get("published") or "")[:10], "%Y-%m-%d")
                except Exception:
                    latest_pub = None
            since_date = since_dt.date()
            latest_date = latest_pub.date() if latest_pub is not None else None
            if latest_date is None or latest_date < since_date:
                continue
        pairs.append((base, tracked, latest))
        if not count_only:
            needed_rows[str(tracked.get("id") or "")] = tracked
            needed_rows[str(latest.get("id") or "")] = latest

    if not pairs:
        return _empty_payload()

    if count_only:
        total_count = len(pairs)
        active_count = 0
        for base_id, _tracked, _latest in pairs:
            triage_state = triage_map.get(base_id) or {}
            if _version_update_state_active(triage_state, today_iso):
                active_count += 1
        triaged_count = max(0, total_count - active_count)
        selected_count = total_count if include_triaged else active_count
        return {
            "scope": scope_key,
            "since": since_dt.isoformat() if since_dt else None,
            "count": min(lim, selected_count),
            "active_count": active_count,
            "triaged_count": triaged_count,
            "total_count": total_count,
            "items": [],
        }

    structures = _ensure_structures_for_papers(list(needed_rows.values()), refresh=False)
    all_items: List[Dict[str, Any]] = []
    for pair_base_id, tracked, latest in pairs:
        tracked_id = str(tracked.get("id") or "")
        latest_id = str(latest.get("id") or "")
        tracked_struct = structures.get(tracked_id) or tracked.get("structure") or {}
        latest_struct = structures.get(latest_id) or latest.get("structure") or {}
        if not isinstance(tracked_struct, dict):
            tracked_struct = {}
        if not isinstance(latest_struct, dict):
            latest_struct = {}
        changed = _compare_structure_fields(tracked_struct, latest_struct)
        base_id = str(pair_base_id or latest.get("arxiv_base_id") or tracked.get("arxiv_base_id") or "")
        triage_state = triage_map.get(base_id) or {}
        triage_active = _version_update_state_active(triage_state, today_iso)
        triage_status = str(triage_state.get("status") or ("active" if triage_active else "reviewed"))
        all_items.append(
            {
                "paper_id": tracked_id,
                "paper_title": tracked.get("title"),
                "latest_id": latest_id,
                "latest_title": latest.get("title"),
                "published": latest.get("published"),
                "arxiv_base_id": base_id,
                "from_version": _paper_version_number(tracked),
                "to_version": _paper_version_number(latest),
                "changed_structure_fields": changed,
                "changed_count": len(changed),
                "triage_status": triage_status,
                "triage_active": bool(triage_active),
                "triage_snooze_until": triage_state.get("snooze_until"),
                "triage_updated_at": triage_state.get("updated_at"),
            }
        )

    all_items.sort(key=lambda x: (str(x.get("published") or ""), int(x.get("to_version") or 0)), reverse=True)
    active_items = [row for row in all_items if bool(row.get("triage_active"))]
    selected = all_items if include_triaged else active_items
    selected = selected[:lim]
    return {
        "scope": scope_key,
        "since": since_dt.isoformat() if since_dt else None,
        "count": len(selected),
        "active_count": len(active_items),
        "triaged_count": max(0, len(all_items) - len(active_items)),
        "total_count": len(all_items),
        "items": selected,
    }

def _apply_version_update_action_internal(
    action: str,
    arxiv_base_id: str,
    paper_id: Optional[str] = None,
    snooze_days: int = 3,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    act = str(action or "").strip().lower()
    base_id = _resolve_version_base_id(arxiv_base_id, paper_id)
    if not base_id:
        raise HTTPException(status_code=400, detail="paper_id or arxiv_base_id is required")

    if act == "clear":
        ok = storage.clear_version_update_state(base_id)
        _bump_api_cache_epochs("alerts", "papers")
        return {"success": True, "action": act, "arxiv_base_id": base_id, "cleared": bool(ok)}

    if act == "snooze":
        days = max(1, min(int(snooze_days or 3), 90))
        until = (datetime.now().date() + timedelta(days=days)).isoformat()
        state = storage.set_version_update_state(
            base_id,
            status="snoozed",
            snooze_until=until,
            note=note,
        )
        _bump_api_cache_epochs("alerts", "papers")
        return {"success": True, "action": act, "arxiv_base_id": base_id, "state": state}

    if act in {"reviewed", "dismiss"}:
        normalized = "dismissed" if act == "dismiss" else "reviewed"
        state = storage.set_version_update_state(
            base_id,
            status=normalized,
            snooze_until=None,
            note=note,
        )
        _bump_api_cache_epochs("alerts", "papers")
        return {"success": True, "action": act, "arxiv_base_id": base_id, "state": state}

    raise HTTPException(status_code=400, detail="action must be one of: reviewed, snooze, dismiss, clear")

def _normalize_inbox_kind(kind: Optional[str]) -> str:
    value = str(kind or "").strip().lower()
    if value in {"alert", "alerts"}:
        return "alert"
    if value in {"version", "version_update", "version_updates"}:
        return "version_update"
    if value in {"followup", "follow_up", "followups", "follow_ups"}:
        return "follow_up"
    if value in {"digest", "digests"}:
        return "digest"
    return ""

def _parse_inbox_kind_list(raw: Optional[str], fallback: Optional[List[str]] = None) -> List[str]:
    if raw is None:
        values = fallback or ["alert", "version_update", "follow_up", "digest"]
        out_default: List[str] = []
        for value in values:
            norm = _normalize_inbox_kind(value)
            if norm and norm not in out_default:
                out_default.append(norm)
        return out_default
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    out: List[str] = []
    for part in parts:
        norm = _normalize_inbox_kind(part)
        if norm and norm not in out:
            out.append(norm)
    return out or (fallback or ["alert", "version_update", "follow_up", "digest"])

def _default_inbox_action_for_kind(kind: str) -> str:
    k = _normalize_inbox_kind(kind)
    if k == "alert":
        return "seen"
    if k == "version_update":
        return "reviewed"
    if k == "follow_up":
        return "done"
    if k == "digest":
        return "read"
    return ""

def _apply_inbox_action_internal(req: InboxActionRequest) -> Dict[str, Any]:
    kind = _normalize_inbox_kind(req.kind)
    action = str(req.action or "").strip().lower()
    if kind not in {"alert", "version_update", "follow_up", "digest"}:
        raise HTTPException(status_code=400, detail="kind must be one of: alert, version_update, follow_up, digest")

    if kind == "alert":
        if action not in {"seen", "mark_seen"}:
            raise HTTPException(status_code=400, detail="alert action must be: seen")
        if req.alert_id is None:
            raise HTTPException(status_code=400, detail="alert_id is required")
        storage.mark_alerts_seen([int(req.alert_id)])
        _bump_api_cache_epochs("alerts")
        return {"success": True, "kind": kind, "action": "seen", "alert_id": int(req.alert_id)}

    if kind == "version_update":
        response = _apply_version_update_action_internal(
            action=action,
            arxiv_base_id=req.arxiv_base_id or "",
            paper_id=req.paper_id,
            snooze_days=req.snooze_days,
            note=req.note,
        )
        response["kind"] = kind
        return response

    if kind == "follow_up":
        follow_id = str(req.follow_id or "").strip()
        if not follow_id:
            raise HTTPException(status_code=400, detail="follow_id is required")
        if action == "done":
            ok = storage.mark_follow_up_done(follow_id)
            if not ok:
                raise HTTPException(status_code=404, detail="Follow-up not found")
            return {"success": True, "kind": kind, "action": action, "follow_id": follow_id}
        if action == "snooze":
            item = storage.snooze_follow_up(follow_id, days=req.snooze_days)
            if not item:
                raise HTTPException(status_code=404, detail="Follow-up not found")
            return {"success": True, "kind": kind, "action": action, "follow_id": follow_id, "item": item}
        raise HTTPException(status_code=400, detail="follow_up action must be one of: done, snooze")

    digest_id = int(req.digest_id or 0)
    if digest_id <= 0:
        raise HTTPException(status_code=400, detail="digest_id is required")
    if action not in {"read", "mark_read"}:
        raise HTTPException(status_code=400, detail="digest action must be: read")
    ok = storage.mark_digest_read(digest_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Digest not found")
    return {"success": True, "kind": kind, "action": "read", "digest_id": digest_id}

def _coerce_iso_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = _parse_iso_datetime(text)
    if parsed:
        return parsed
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except Exception:
        return None

def _coerce_naive_local(dt: Optional[datetime]) -> Optional[datetime]:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is not None:
        try:
            return dt.astimezone().replace(tzinfo=None)
        except Exception:
            return dt.replace(tzinfo=None)
    return dt

def _resolve_inbox_item_time(item: Dict[str, Any]) -> Optional[datetime]:
    if not isinstance(item, dict):
        return None
    dt = (
        _coerce_iso_datetime(item.get("_sort_ts"))
        or _coerce_iso_datetime(item.get("remind_at"))
        or _coerce_iso_datetime(item.get("created_at"))
        or _coerce_iso_datetime(item.get("published"))
    )
    return _coerce_naive_local(dt)

def _inbox_sort_epoch(item: Dict[str, Any]) -> float:
    if not isinstance(item, dict):
        return 0.0
    cached = item.get("_sort_epoch")
    if cached is not None:
        try:
            return float(cached)
        except Exception:
            pass
    dt = _resolve_inbox_item_time(item)
    if not dt:
        return 0.0
    try:
        return float(dt.timestamp())
    except Exception:
        return 0.0

def _priority_for_unified_inbox_item(
    item: Dict[str, Any],
    now: Optional[datetime] = None,
    time_ref: Optional[datetime] = None,
) -> tuple[int, str]:
    if not isinstance(item, dict):
        return 0, ""
    kind = _normalize_inbox_kind(item.get("kind"))
    now_dt = _coerce_naive_local(now) or datetime.now()
    score = {
        "follow_up": 70,
        "version_update": 60,
        "alert": 54,
        "digest": 42,
    }.get(kind, 30)
    reasons: List[str] = []

    item_time = _coerce_naive_local(time_ref) or _resolve_inbox_item_time(item)
    if item_time:
        age_hours = max(0.0, (now_dt - item_time).total_seconds() / 3600.0)
        if age_hours <= 12:
            score += 14
            reasons.append("very recent")
        elif age_hours <= 48:
            score += 9
            reasons.append("recent")
        elif age_hours <= 168:
            score += 4

    if kind == "follow_up":
        due_at = _coerce_naive_local(_coerce_iso_datetime(item.get("remind_at")))
        if due_at:
            overdue_hours = (now_dt - due_at).total_seconds() / 3600.0
            if overdue_hours >= 0:
                overdue_days = min(14.0, overdue_hours / 24.0)
                score += min(18, int(round(overdue_days * 3.0)) + 5)
                reasons.append("overdue follow-up")
            elif abs(overdue_hours) <= 24:
                score += 7
                reasons.append("due soon")

    if kind == "version_update":
        changed_count = max(0, int(item.get("changed_count") or 0))
        from_v = max(0, int(item.get("from_version") or 0))
        to_v = max(0, int(item.get("to_version") or 0))
        step = max(0, to_v - from_v)
        if changed_count:
            score += min(14, changed_count * 2)
            reasons.append(f"{changed_count} changed fields")
        if step > 1:
            score += min(8, step * 2)
            reasons.append(f"v{from_v}\u2192v{to_v}")
        changed_fields = [str(x).lower() for x in (item.get("changed_structure_fields") or []) if x]
        if any(name in {"method", "results", "dataset"} for name in changed_fields):
            score += 5
            reasons.append("core section changes")

    if kind == "alert":
        alert_type = str(item.get("alert_type") or "").lower()
        if alert_type == "citation":
            score += 8
            reasons.append("citation spike")
        elif alert_type == "author":
            score += 6
            reasons.append("followed author")
        elif alert_type == "keyword":
            score += 4
            reasons.append("keyword match")
        elif alert_type == "version":
            score += 5
            reasons.append("new version alert")

    if kind == "digest":
        paper_count = max(0, int(item.get("paper_count") or 0))
        cadence = str(item.get("cadence") or "daily").lower()
        if paper_count:
            score += min(9, int(round(math.sqrt(float(paper_count)) * 3.0)))
            reasons.append(f"{paper_count} papers")
        if cadence == "weekly":
            score += 3

    bounded = max(1, min(100, int(round(score))))
    if not reasons:
        reasons.append(kind.replace("_", " ") if kind else "inbox item")
    return bounded, "; ".join(reasons[:3])

def _build_unified_inbox_payload(
    limit: int = 60,
    version_scope: str = "watchlist",
    version_days: int = 30,
    kinds: Optional[List[str]] = None,
    include_items: bool = True,
    sort_by: str = "recent",
) -> Dict[str, Any]:
    total_limit = max(1, min(int(limit or 60), 200))
    per_kind = max(6, min(120, int(math.ceil(total_limit / 4.0)) + 6))
    days = max(1, min(int(version_days or 30), 180))
    sort_mode = str(sort_by or "recent").strip().lower()
    if sort_mode not in {"recent", "priority"}:
        sort_mode = "recent"
    since = (datetime.now().date() - timedelta(days=days - 1)).isoformat()
    selected_kinds = _parse_inbox_kind_list(None, kinds)
    selected_set = set(selected_kinds)
    with storage.connection_scope():
        count_alerts = storage.count_unseen_alerts() if "alert" in selected_set else 0
        count_followups = storage.count_follow_ups_due() if "follow_up" in selected_set else 0
        count_digests = storage.count_unread_digests() if "digest" in selected_set else 0
        versions_payload = (
            _build_version_updates_payload(
                since=since,
                scope=version_scope,
                limit=(per_kind * 3) if include_items else 1,
                include_triaged=False,
                count_only=not include_items,
            )
            if "version_update" in selected_set
            else {"items": [], "active_count": 0}
        )
    version_items = list(versions_payload.get("items") or [])
    version_active = int(versions_payload.get("active_count") or len(version_items))

    counts = {
        "alerts": int(count_alerts),
        "version_updates": max(0, int(version_active)),
        "follow_ups": int(count_followups),
        "digests": int(count_digests),
    }
    total = int(sum(int(v or 0) for v in counts.values()))

    if not include_items:
        return {
            "generated_at": datetime.now().isoformat(),
            "counts": counts,
            "total": total,
            "items": [],
            "version_scope": version_scope,
            "version_days": days,
            "version_since": since,
            "kinds": selected_kinds,
            "sort": sort_mode,
        }

    with storage.connection_scope():
        alerts = storage.get_alerts(limit=per_kind * 3, unseen_only=True) if "alert" in selected_set else []
        followups = storage.list_follow_ups(due_only=True, limit=per_kind * 3) if "follow_up" in selected_set else []
        unread_digests: List[Dict[str, Any]] = []
        if "digest" in selected_set:
            digest_runs = storage.list_digest_runs(limit=max(40, per_kind * 5), include_items=False)
            unread_digests = [r for r in digest_runs if bool(r.get("unread"))]

    items: List[Dict[str, Any]] = []
    for a in alerts:
        created_at = str(a.get("created_at") or "")
        items.append(
            {
                "kind": "alert",
                "id": f"alert:{a.get('id')}",
                "alert_id": int(a.get("id") or 0),
                "paper_id": a.get("paper_id"),
                "title": a.get("title") or a.get("paper_id") or "Alert",
                "message": a.get("message") or "",
                "alert_type": a.get("alert_type") or "",
                "created_at": created_at,
                "_sort_ts": created_at,
            }
        )

    for v in version_items[: per_kind * 2]:
        published = str(v.get("published") or "")
        items.append(
            {
                "kind": "version_update",
                "id": f"version:{v.get('arxiv_base_id') or v.get('latest_id') or v.get('paper_id')}",
                "arxiv_base_id": v.get("arxiv_base_id"),
                "paper_id": v.get("paper_id"),
                "latest_id": v.get("latest_id"),
                "title": v.get("paper_title") or v.get("latest_title") or v.get("paper_id") or "Version update",
                "from_version": int(v.get("from_version") or 0),
                "to_version": int(v.get("to_version") or 0),
                "changed_count": int(v.get("changed_count") or 0),
                "changed_structure_fields": v.get("changed_structure_fields") or [],
                "published": published,
                "created_at": published,
                "_sort_ts": published,
            }
        )

    for f in followups:
        remind_at = str(f.get("remind_at") or "")
        items.append(
            {
                "kind": "follow_up",
                "id": f"follow_up:{f.get('id')}",
                "follow_id": f.get("id"),
                "paper_id": f.get("paper_id"),
                "title": f.get("title") or f.get("paper_id") or "Follow-up",
                "note": f.get("note") or "",
                "remind_at": remind_at,
                "created_at": str(f.get("created_at") or remind_at),
                "_sort_ts": remind_at or str(f.get("created_at") or ""),
            }
        )

    for d in unread_digests[: per_kind * 2]:
        created_at = str(d.get("created_at") or "")
        items.append(
            {
                "kind": "digest",
                "id": f"digest:{d.get('id')}",
                "digest_id": int(d.get("id") or 0),
                "title": d.get("title") or "Digest",
                "summary": d.get("summary") or "",
                "cadence": d.get("cadence") or "daily",
                "paper_count": int(d.get("paper_count") or 0),
                "created_at": created_at,
                "_sort_ts": created_at,
            }
        )

    now_dt = datetime.now()
    for item in items:
        item_time = _resolve_inbox_item_time(item)
        epoch = 0.0
        if item_time:
            try:
                epoch = float(item_time.timestamp())
            except Exception:
                epoch = 0.0
        item["_sort_epoch"] = epoch
        priority_score, priority_reason = _priority_for_unified_inbox_item(item, now=now_dt, time_ref=item_time)
        item["_priority_score"] = int(priority_score)
        item["_priority_reason"] = str(priority_reason or "")

    if sort_mode == "priority":
        items.sort(
            key=lambda x: (int(x.get("_priority_score") or 0), float(x.get("_sort_epoch") or 0.0)),
            reverse=True,
        )
    else:
        items.sort(
            key=lambda x: (float(x.get("_sort_epoch") or 0.0), int(x.get("_priority_score") or 0)),
            reverse=True,
        )

    trimmed = items[:total_limit]
    for item in trimmed:
        item["priority_score"] = int(item.get("_priority_score") or 0)
        item["priority_reason"] = str(item.get("_priority_reason") or "")
        item.pop("_priority_score", None)
        item.pop("_priority_reason", None)
        item.pop("_sort_epoch", None)
        item.pop("_sort_ts", None)
    return {
        "generated_at": datetime.now().isoformat(),
        "counts": counts,
        "total": total,
        "items": trimmed,
        "version_scope": version_scope,
        "version_days": days,
        "version_since": since,
        "kinds": selected_kinds,
        "sort": sort_mode,
    }


def _text_to_diff_lines(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    lines = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    return lines or [text]


def _unified_text_diff(before: Any, after: Any, from_label: str, to_label: str) -> str:
    before_lines = _text_to_diff_lines(before)
    after_lines = _text_to_diff_lines(after)
    diff_lines = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=from_label,
        tofile=to_label,
        lineterm="",
    )
    return "\n".join(diff_lines)

def _attach_match_reasons(papers: List[Dict[str, Any]]) -> None:
    if not papers:
        return
    followed = set(storage.get_followed_authors())
    keywords = [k.lower() for k in config.KEYWORDS if k]
    for p in papers:
        reasons: List[str] = []
        text = f"{p.get('title', '')} {p.get('summary', '')}".lower()
        matched_kw = [kw for kw in keywords if kw in text]
        if p.get("match_score") is None:
            p["match_score"] = len(matched_kw)
        matched_kw = matched_kw[:3]
        if matched_kw:
            reasons.append(f"Keyword match: {', '.join(matched_kw)}")
        authors = p.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        matched_authors = [a for a in authors if a in followed][:2]
        if matched_authors:
            reasons.append(f"Followed author: {', '.join(matched_authors)}")
        if reasons:
            p["match_reasons"] = reasons

def _attach_reading_meta(papers: List[Dict[str, Any]]) -> None:
    if not papers:
        return
    ids = [p.get("id") for p in papers if p.get("id")]
    if not ids:
        return
    reading_map = storage.get_reading_status_map(ids)
    notes_map = storage.get_notes_meta_map(ids)
    reading_time_map = storage.get_reading_time_map(ids)
    assignment_map = storage.get_assignment_meta_map(ids)
    for p in papers:
        pid = p.get("id")
        if not pid:
            continue
        if pid in reading_map:
            reading = reading_map[pid]
            p["reading_status"] = reading.get("status")
            p["reading_progress"] = reading.get("progress")
            p["reading_started_at"] = reading.get("started_at")
            p["reading_finished_at"] = reading.get("finished_at")
        if pid in notes_map:
            note_meta = notes_map[pid]
            p["has_notes"] = bool(note_meta.get("has_notes"))
            p["notes_updated_at"] = note_meta.get("updated_at")
        if pid in reading_time_map:
            rt = reading_time_map[pid]
            p["reading_time_minutes"] = rt.get("minutes")
            p["reading_time_pages"] = rt.get("page_count")
            p["reading_time_updated_at"] = rt.get("updated_at")
        assign_meta = assignment_map.get(pid) or {}
        p["assignment_open_count"] = int(assign_meta.get("open_count") or 0)
        p["assignment_unread_count"] = int(assign_meta.get("unread_count") or 0)
        p["assignment_assignees"] = list(assign_meta.get("assignees") or [])

def _attach_labels(papers: List[Dict[str, Any]]) -> None:
    if not papers:
        return
    ids = [p.get("id") for p in papers if p.get("id")]
    if not ids:
        return
    label_map = storage.get_paper_labels_map(ids)
    for p in papers:
        pid = p.get("id")
        p["labels"] = label_map.get(pid, []) if pid else []

def _attach_pins(papers: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not papers:
        return {}
    ids = [p.get("id") for p in papers if p.get("id")]
    if not ids:
        return {}
    pin_map = storage.get_pinned_map(ids)
    for p in papers:
        pid = p.get("id")
        if not pid:
            continue
        rec = pin_map.get(pid)
        if rec:
            p["pinned"] = True
            p["pin_note"] = rec.get("note") or ""
            p["pin_updated_at"] = rec.get("updated_at")
            p["pin_expires_at"] = rec.get("expires_at") or ""
        else:
            p["pinned"] = False
            p["pin_note"] = ""
            p["pin_expires_at"] = ""
    return pin_map

def _apply_pin_order(papers: List[Dict[str, Any]], pin_map: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not papers or not pin_map:
        return papers
    pinned = []
    others = []
    for p in papers:
        pid = p.get("id")
        if pid and pid in pin_map:
            pinned.append(p)
        else:
            others.append(p)
    pinned.sort(key=lambda p: p.get("pin_updated_at") or "", reverse=True)
    return pinned + others

def _reading_behavior_signal_map(
    paper_ids: List[str],
    days: int = 45,
) -> Dict[str, float]:
    if not paper_ids:
        return {}
    unique_ids = [str(pid) for pid in dict.fromkeys(paper_ids) if pid]
    if not unique_ids:
        return {}
    try:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=max(1, int(days)) - 1)
        rows = storage.list_reading_plan_activity(
            limit=max(300, min(3000, len(unique_ids) * 40)),
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
        )
    except Exception:
        return {}
    wanted = set(unique_ids)
    out: Dict[str, float] = {pid: 0.0 for pid in unique_ids}
    now_date = datetime.now().date()
    for row in rows:
        pid = str(row.get("paper_id") or "")
        if not pid or pid not in wanted:
            continue
        action = str(row.get("action") or "").strip().lower()
        minutes = max(0, int(row.get("minutes") or 0))
        plan_date_str = str(row.get("plan_date") or "")
        try:
            plan_date = datetime.strptime(plan_date_str[:10], "%Y-%m-%d").date()
            age_days = max(0, (now_date - plan_date).days)
        except Exception:
            age_days = max(0, int(days))
        # Mild decay so recent behavior contributes more.
        decay = math.exp(-float(age_days) / 21.0)
        delta = 0.0
        if action == "done":
            delta = 1.0 + min(1.0, float(minutes) / 90.0)
        elif action == "undo_done":
            delta = -0.8 - min(0.8, float(minutes) / 120.0)
        elif action == "defer":
            delta = -0.35
        elif action == "undefer":
            delta = 0.2
        if delta != 0.0:
            out[pid] = float(out.get(pid, 0.0)) + (delta * decay)
    return out

def _build_rank_explain_text(paper: Dict[str, Any]) -> str:
    if not isinstance(paper, dict):
        return ""
    explain = paper.get("rank_explain")
    if isinstance(explain, str) and explain.strip():
        return explain.strip()
    relevance = float(paper.get("_profile_rel_norm") or 0.0)
    novelty = float(paper.get("_profile_nov_norm") or 0.0)
    citations = float(paper.get("_profile_cit_norm") or 0.0)
    behavior = float(paper.get("_profile_behavior_signal") or 0.0)
    behavior_component = float(paper.get("_profile_behavior_component") or 0.0)
    return (
        f"Ranked by profile: rel {int(round(relevance * 100))}%, "
        f"nov {int(round(novelty * 100))}%, cite {int(round(citations * 100))}%, "
        f"behavior {behavior:+.2f} ({behavior_component:+.2f})."
    )

def _apply_profile_sort(
    papers: List[Dict[str, Any]],
    weights: Dict[str, float],
) -> List[Dict[str, Any]]:
    if not papers:
        return []
    ranked = list(papers)

    missing_ids = [p.get("id") for p in ranked if p.get("id") and p.get("novelty_score") is None]
    novelty_map = storage.compute_novelty_scores(missing_ids, reference_status="liked") if missing_ids else {}
    if novelty_map:
        _enqueue_novelty_backfill(novelty_map)
    for p in ranked:
        if p.get("novelty_score") is None and p.get("id"):
            p["novelty_score"] = novelty_map.get(p.get("id"))

    rel_raw: List[float] = []
    score_updates: Dict[str, float] = {}
    for p in ranked:
        existing = p.get("ranker_score")
        if existing is None:
            existing = float(ranker.ranker_instance.score(p))
            pid = p.get("id")
            if pid:
                score_updates[pid] = existing
        try:
            p["ranker_score"] = float(existing)
        except Exception:
            p["ranker_score"] = float(existing or 0.0)
        rel_raw.append(float(p.get("ranker_score") or 0.0))
    if score_updates:
        try:
            storage.update_ranker_scores(score_updates)
        except Exception:
            pass

    nov_raw = [float(p.get("novelty_score") or 0.0) for p in ranked]
    cit_raw = [math.log1p(float(p.get("citation_count") or 0.0)) for p in ranked]
    behavior_map = _reading_behavior_signal_map([str(p.get("id") or "") for p in ranked], days=45)
    behavior_raw = [float(behavior_map.get(str(p.get("id") or ""), 0.0)) for p in ranked]

    rel_norm = _normalize_values(rel_raw)
    nov_norm = _normalize_values(nov_raw)
    cit_norm = _normalize_values(cit_raw)
    behavior_norm = _normalize_values(behavior_raw)
    has_behavior = any(abs(v) > 1e-9 for v in behavior_raw)
    behavior_weight = 0.15 if has_behavior else 0.0
    base_weight = 1.0 - behavior_weight

    for idx, p in enumerate(ranked):
        p["score"] = _paper_match_score(p)
        base_component = (
            weights.get("relevance", 0.5) * rel_norm[idx] +
            weights.get("novelty", 0.3) * nov_norm[idx] +
            weights.get("citations", 0.2) * cit_norm[idx]
        )
        behavior_component = behavior_weight * behavior_norm[idx]
        p["_profile_rel_norm"] = rel_norm[idx]
        p["_profile_nov_norm"] = nov_norm[idx]
        p["_profile_cit_norm"] = cit_norm[idx]
        p["_profile_behavior_signal"] = behavior_raw[idx]
        p["_profile_behavior_component"] = behavior_component
        p["_profile_score"] = (base_weight * base_component) + behavior_component
        p["rank_explain"] = _build_rank_explain_text(p)

    ranked.sort(key=lambda x: (x.get("_profile_score", 0.0), x.get("published", "")), reverse=True)
    return ranked

def _keyword_match_score(paper: Dict[str, Any]) -> int:
    if not paper:
        return 0
    text = f"{paper.get('title', '')} {paper.get('summary', '')}".lower()
    keywords = [k.lower() for k in config.KEYWORDS if k]
    return sum(1 for kw in keywords if kw and kw in text)

def _paper_match_score(paper: Dict[str, Any]) -> int:
    if not paper:
        return 0
    score = paper.get("match_score")
    if score is None:
        score = _keyword_match_score(paper)
        paper["match_score"] = score
    try:
        return int(score)
    except Exception:
        return int(score or 0)


def _estimate_reading_minutes_from_summary(paper: Dict[str, Any]) -> int:
    summary = str(paper.get("summary") or "")
    # Coarse fallback: ~1 page per ~1800 chars, bounded for stability.
    est_pages = max(2, min(20, int(len(summary) / 1800) + 1))
    return int(ai_service.estimate_reading_time_minutes(est_pages))


def _build_reading_plan_payload(
    total_minutes: int = 60,
    max_items: int = 6,
    budget_mode: str = "balanced",
    include_new: bool = True,
    include_liked: bool = True,
    include_bookmarked: bool = True,
) -> Dict[str, Any]:
    storage.init_db()
    mode = str(budget_mode or "balanced").strip().lower()
    if mode not in {"balanced", "focus", "sprint", "deep"}:
        mode = "balanced"
    budget = max(10, min(int(total_minutes or 60), 360))
    item_cap = max(1, min(int(max_items or 6), 20))
    if mode == "deep":
        item_cap = min(item_cap, 5)
    elif mode == "focus":
        item_cap = min(item_cap, 6)
    elif mode == "sprint":
        item_cap = min(item_cap, 8)

    candidates: Dict[str, Dict[str, Any]] = {}
    sources_by_id: Dict[str, set[str]] = {}

    def add_candidates(rows: List[Dict[str, Any]], source: str):
        for p in rows or []:
            pid = p.get("id")
            if not pid:
                continue
            if pid not in candidates:
                candidates[pid] = p
            sources_by_id.setdefault(pid, set()).add(source)

    if include_liked:
        add_candidates(storage.get_papers_by_status("liked"), "liked")
    if include_bookmarked:
        bookmarked_ids = storage.get_bookmarked_ids()
        if bookmarked_ids:
            add_candidates(storage.get_papers_by_ids(bookmarked_ids), "bookmarked")
    if include_new:
        new_rows, _new_total = storage.get_papers_page_by_status(
            status="new",
            limit=300,
            offset=0,
            dedupe_latest=True,
            include_total=False,
        )
        add_candidates(new_rows, "new")

    if not candidates:
        return {
            "date": datetime.now().date().isoformat(),
            "generated_at": datetime.now().isoformat(),
            "total_minutes_budget": budget,
            "max_items": item_cap,
            "budget_mode": mode,
            "planned_minutes": 0,
            "items": [],
            "count": 0,
        }

    ids = list(candidates.keys())
    reading_map = storage.get_reading_status_map(ids)
    reading_time_map = storage.get_reading_time_map(ids)
    deferred_map = storage.get_deferred_reading_map(ids, on_date=datetime.now().date().isoformat())

    scored: List[Dict[str, Any]] = []
    deferred_count = 0
    for pid, paper in candidates.items():
        if pid in deferred_map:
            deferred_count += 1
            continue
        reading = reading_map.get(pid) or {}
        status = str(reading.get("status") or "queue")
        progress = int(reading.get("progress") or 0)
        if status == "done" or progress >= 100:
            continue

        rt = reading_time_map.get(pid) or {}
        minutes_total = int(rt.get("minutes") or 0)
        if minutes_total <= 0:
            minutes_total = _estimate_reading_minutes_from_summary(paper)
        minutes_remaining = max(1, int(round(minutes_total * max(0, 100 - progress) / 100)))

        score = 0.0
        src = sources_by_id.get(pid, set())
        if "bookmarked" in src:
            score += 4.0
        if "liked" in src:
            score += 3.0
        if "new" in src:
            score += 1.0
        if status in {"reading", "in_progress"}:
            score += 3.0
        elif status in {"queue", "planned"}:
            score += 1.0
        if 0 < progress < 100:
            score += 2.0
        score += min(2.0, math.log1p(float(paper.get("citation_count") or 0.0)) / 2.0)
        score += min(2.0, 0.2 * float(_paper_match_score(paper)))
        score += min(1.5, float(paper.get("novelty_score") or 0.0) * 1.5)
        if mode == "sprint":
            # Favor high-value short reads for tight sessions.
            score += max(0.0, 2.4 - (float(minutes_remaining) / 28.0))
            if minutes_remaining > max(45, int(budget * 0.75)):
                score -= 1.0
        elif mode == "focus":
            if status in {"reading", "in_progress"}:
                score += 2.0
            if 0 < progress < 100:
                score += 1.5
        elif mode == "deep":
            # Favor richer/longer papers and deprioritize low-signal quick reads.
            score += min(2.0, float(minutes_remaining) / 35.0)
            if minutes_remaining < 20:
                score -= 0.75

        scored.append({
            "id": pid,
            "title": paper.get("title"),
            "published": paper.get("published"),
            "status": status,
            "progress": progress,
            "minutes_total": minutes_total,
            "minutes_remaining": minutes_remaining,
            "citation_count": int(paper.get("citation_count") or 0),
            "sources": sorted(src),
            "score": round(score, 3),
        })

    scored.sort(key=lambda x: (x.get("score", 0.0), x.get("published", "")), reverse=True)

    plan_items: List[Dict[str, Any]] = []
    planned_minutes = 0
    for row in scored:
        if len(plan_items) >= item_cap:
            break
        mins = int(row.get("minutes_remaining") or 0)
        if mins <= 0:
            continue
        if mode == "sprint" and plan_items and mins > max(35, int(budget * 0.6)):
            continue
        # Always include first item; then try to stay within budget.
        if plan_items and (planned_minutes + mins) > budget:
            continue
        plan_items.append(row)
        planned_minutes += mins

    return {
        "date": datetime.now().date().isoformat(),
        "generated_at": datetime.now().isoformat(),
        "total_minutes_budget": budget,
        "max_items": item_cap,
        "budget_mode": mode,
        "planned_minutes": planned_minutes,
        "deferred_count": deferred_count,
        "items": plan_items,
        "count": len(plan_items),
    }


def _reading_plan_cache_key(
    total_minutes: int = 60,
    max_items: int = 6,
    budget_mode: str = "balanced",
    include_new: bool = True,
    include_liked: bool = True,
    include_bookmarked: bool = True,
    day: Optional[str] = None,
) -> str:
    day_key = day or datetime.now().date().isoformat()
    mode = str(budget_mode or "balanced").strip().lower()
    return (
        f"reading_plan:{day_key}:"
        f"{int(total_minutes)}:{int(max_items)}:{mode}:"
        f"{int(bool(include_new))}:{int(bool(include_liked))}:{int(bool(include_bookmarked))}"
    )


def _sanitize_reading_plan_options(
    total_minutes: Optional[int] = 60,
    max_items: Optional[int] = 6,
    budget_mode: Optional[str] = "balanced",
    include_new: Optional[bool] = True,
    include_liked: Optional[bool] = True,
    include_bookmarked: Optional[bool] = True,
) -> Dict[str, Any]:
    budget = max(10, min(int(total_minutes or 60), 360))
    item_cap = max(1, min(int(max_items or 6), 20))
    mode = str(budget_mode or "balanced").strip().lower()
    if mode not in {"balanced", "focus", "sprint", "deep"}:
        mode = "balanced"
    return {
        "total_minutes": budget,
        "max_items": item_cap,
        "budget_mode": mode,
        "include_new": bool(include_new),
        "include_liked": bool(include_liked),
        "include_bookmarked": bool(include_bookmarked),
    }


def _load_last_reading_plan_options() -> Dict[str, Any]:
    defaults = _sanitize_reading_plan_options()
    raw = storage.get_ai_cache(READING_PLAN_LAST_OPTIONS_KEY, max_age_seconds=14 * 24 * 3600)
    if not raw:
        return defaults
    try:
        parsed = json.loads(raw)
    except Exception:
        return defaults
    if not isinstance(parsed, dict):
        return defaults
    return _sanitize_reading_plan_options(
        total_minutes=parsed.get("total_minutes"),
        max_items=parsed.get("max_items"),
        budget_mode=parsed.get("budget_mode"),
        include_new=parsed.get("include_new"),
        include_liked=parsed.get("include_liked"),
        include_bookmarked=parsed.get("include_bookmarked"),
    )


def _save_last_reading_plan_options(options: Dict[str, Any]) -> None:
    if not isinstance(options, dict):
        return
    try:
        storage.set_ai_cache(READING_PLAN_LAST_OPTIONS_KEY, json.dumps(options))
    except Exception:
        pass


def _persist_reading_plan_snapshot(payload: Dict[str, Any], options: Dict[str, Any], source: str) -> None:
    if not isinstance(payload, dict):
        return
    plan_date = str(payload.get("date") or datetime.now().date().isoformat())
    try:
        storage.save_reading_plan_snapshot(
            plan_date=plan_date,
            payload=payload,
            options=options,
            source=source,
        )
    except Exception:
        pass


def _refresh_today_reading_plan_cache(source: str = "auto") -> Dict[str, Any]:
    options = _load_last_reading_plan_options()
    payload = _build_reading_plan_payload(
        total_minutes=options.get("total_minutes"),
        max_items=options.get("max_items"),
        budget_mode=options.get("budget_mode"),
        include_new=options.get("include_new"),
        include_liked=options.get("include_liked"),
        include_bookmarked=options.get("include_bookmarked"),
    )
    payload["cached"] = False
    payload["options"] = options
    cache_key = _reading_plan_cache_key(
        total_minutes=options.get("total_minutes"),
        max_items=options.get("max_items"),
        budget_mode=options.get("budget_mode"),
        include_new=options.get("include_new"),
        include_liked=options.get("include_liked"),
        include_bookmarked=options.get("include_bookmarked"),
    )
    storage.set_ai_cache(cache_key, json.dumps(payload))
    _persist_reading_plan_snapshot(payload, options, source=source)
    return payload


def _refresh_today_reading_plan_async(source: str = "auto") -> None:
    def _task():
        try:
            _refresh_today_reading_plan_cache(source=source)
        except Exception:
            pass
    threading.Thread(target=_task, daemon=True).start()


def _reading_plan_minutes_for_paper(paper_id: str, payload: Optional[Dict[str, Any]]) -> int:
    if not paper_id or not isinstance(payload, dict):
        return 0
    items = payload.get("items")
    if not isinstance(items, list):
        return 0
    for item in items:
        if str((item or {}).get("id") or "") != str(paper_id):
            continue
        mins = int((item or {}).get("minutes_remaining") or 0)
        if mins <= 0:
            mins = int((item or {}).get("minutes_total") or 0)
        return max(0, mins)
    return 0


def _latest_reading_plan_payload_for_date(plan_date: Optional[str] = None) -> Dict[str, Any]:
    date_key = str(plan_date or datetime.now().date().isoformat())
    snap = storage.get_reading_plan_snapshot(date_key)
    payload = (snap or {}).get("payload") or {}
    return payload if isinstance(payload, dict) else {}


def _record_reading_plan_activity(
    action: str,
    paper_id: str,
    minutes: int = 0,
    meta: Optional[Dict[str, Any]] = None,
    plan_date: Optional[str] = None,
) -> None:
    try:
        storage.record_reading_plan_activity(
            plan_date=str(plan_date or datetime.now().date().isoformat()),
            paper_id=str(paper_id),
            action=str(action or "").strip().lower(),
            minutes=max(0, int(minutes or 0)),
            meta=meta or {},
        )
    except Exception:
        pass


def _reading_plan_progress_summary(days: int = 14) -> Dict[str, Any]:
    days_int = max(1, min(int(days or 14), 90))
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days_int - 1)
    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()

    snapshots = storage.list_reading_plan_snapshots(
        limit=max(60, days_int * 16),
        date_from=start_iso,
        date_to=end_iso,
    )
    latest_snap_by_day: Dict[str, Dict[str, Any]] = {}
    for snap in snapshots:
        day = str(snap.get("plan_date") or "")
        if not day or day in latest_snap_by_day:
            continue
        latest_snap_by_day[day] = snap

    activities = storage.list_reading_plan_activity(
        limit=max(200, days_int * 240),
        date_from=start_iso,
        date_to=end_iso,
    )

    day_list = [(start_date + timedelta(days=i)).isoformat() for i in range(days_int)]
    per_day: Dict[str, Dict[str, Any]] = {}
    for day in day_list:
        snap = latest_snap_by_day.get(day) or {}
        per_day[day] = {
            "date": day,
            "planned_count": int(snap.get("count") or 0),
            "planned_minutes": int(snap.get("planned_minutes") or 0),
            "done_count": 0,
            "done_minutes": 0,
            "deferred_count": 0,
        }

    for row in activities:
        day = str(row.get("plan_date") or "")
        if day not in per_day:
            continue
        action = str(row.get("action") or "").strip().lower()
        minutes = max(0, int(row.get("minutes") or 0))
        target = per_day[day]
        if action == "done":
            target["done_count"] += 1
            target["done_minutes"] += minutes
        elif action == "undo_done":
            target["done_count"] -= 1
            target["done_minutes"] -= minutes
        elif action == "defer":
            target["deferred_count"] += 1
        elif action == "undefer":
            target["deferred_count"] -= 1

    items: List[Dict[str, Any]] = []
    for day in day_list:
        stat = per_day[day]
        stat["done_count"] = max(0, int(stat.get("done_count") or 0))
        stat["done_minutes"] = max(0, int(stat.get("done_minutes") or 0))
        stat["deferred_count"] = max(0, int(stat.get("deferred_count") or 0))
        planned_count = max(0, int(stat.get("planned_count") or 0))
        planned_minutes = max(0, int(stat.get("planned_minutes") or 0))
        done_count = max(0, int(stat.get("done_count") or 0))
        done_minutes = max(0, int(stat.get("done_minutes") or 0))
        stat["remaining_count"] = max(0, planned_count - done_count)
        stat["remaining_minutes"] = max(0, planned_minutes - done_minutes)
        stat["completion_ratio"] = (
            round(done_count / planned_count, 3) if planned_count > 0 else 0.0
        )
        items.append(stat)

    streak = 0
    for stat in reversed(items):
        if int(stat.get("done_count") or 0) > 0:
            streak += 1
        else:
            break

    latest = items[-1] if items else {}
    prev = items[-2] if len(items) > 1 else {}
    totals = {
        "planned_count": int(sum(int(x.get("planned_count") or 0) for x in items)),
        "planned_minutes": int(sum(int(x.get("planned_minutes") or 0) for x in items)),
        "done_count": int(sum(int(x.get("done_count") or 0) for x in items)),
        "done_minutes": int(sum(int(x.get("done_minutes") or 0) for x in items)),
        "deferred_count": int(sum(int(x.get("deferred_count") or 0) for x in items)),
    }
    totals["remaining_count"] = max(0, totals["planned_count"] - totals["done_count"])
    totals["remaining_minutes"] = max(0, totals["planned_minutes"] - totals["done_minutes"])

    carry_over = {
        "count": max(0, int(prev.get("remaining_count") or 0)),
        "minutes": max(0, int(prev.get("remaining_minutes") or 0)),
    }
    today = {
        "date": str(latest.get("date") or end_iso),
        "planned_count": int(latest.get("planned_count") or 0),
        "planned_minutes": int(latest.get("planned_minutes") or 0),
        "done_count": int(latest.get("done_count") or 0),
        "done_minutes": int(latest.get("done_minutes") or 0),
        "remaining_count": int(latest.get("remaining_count") or 0),
        "remaining_minutes": int(latest.get("remaining_minutes") or 0),
    }
    completion_rate = (
        round(float(totals["done_count"]) / float(totals["planned_count"]), 3)
        if totals["planned_count"] > 0
        else 0.0
    )
    return {
        "days": days_int,
        "start_date": start_iso,
        "end_date": end_iso,
        "streak_days": streak,
        "completion_rate": completion_rate,
        "carry_over": carry_over,
        "today": today,
        "totals": totals,
        "items": items,
    }


def _parse_rank_weights(w_rel: Optional[float], w_nov: Optional[float], w_cit: Optional[float]) -> Dict[str, float]:
    defaults = {"relevance": 0.5, "novelty": 0.3, "citations": 0.2}
    if w_rel is None and w_nov is None and w_cit is None:
        return defaults.copy()

    def _safe(val, fallback):
        if val is None:
            return fallback
        try:
            num = float(val)
        except Exception:
            return fallback
        return max(0.0, num)

    w_rel_val = _safe(w_rel, defaults["relevance"])
    w_nov_val = _safe(w_nov, defaults["novelty"])
    w_cit_val = _safe(w_cit, defaults["citations"])
    total = w_rel_val + w_nov_val + w_cit_val
    if total <= 0:
        return defaults.copy()
    return {
        "relevance": w_rel_val / total,
        "novelty": w_nov_val / total,
        "citations": w_cit_val / total,
    }

def _normalize_values(values: List[float]) -> List[float]:
    if not values:
        return []
    min_val = min(values)
    max_val = max(values)
    if max_val - min_val <= 1e-9:
        return [0.0 for _ in values]
    span = max_val - min_val
    return [(v - min_val) / span for v in values]

def _normalize_rule_list(values: List[Any]) -> List[str]:
    if not values:
        return []
    out = []
    for v in values:
        val = str(v or "").strip().lower()
        if val:
            out.append(val)
    return out

def _normalize_rule_scope(scope: Optional[str]) -> str:
    value = str(scope or "").strip().lower()
    return value if value in {"papers", "inbox", "all"} else "papers"


def _rule_min_novelty(rule: Dict[str, Any]) -> float:
    try:
        value = float(rule.get("min_novelty") or 0.0)
    except Exception:
        value = 0.0
    return max(0.0, min(1.0, value))


def _rule_is_in_quiet_hours(rule: Dict[str, Any], now_dt: Optional[datetime] = None) -> bool:
    try:
        start = int(rule.get("quiet_hours_start"))
    except Exception:
        start = -1
    try:
        end = int(rule.get("quiet_hours_end"))
    except Exception:
        end = -1
    if not (0 <= start <= 23 and 0 <= end <= 23):
        return False
    hour = int((now_dt or datetime.now()).hour)
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    # wrap-around window, e.g., 22 -> 7
    return hour >= start or hour < end

def _rule_matches(rule: Dict[str, Any], paper: Dict[str, Any]) -> bool:
    if not rule or not paper:
        return False
    keywords = _normalize_rule_list(rule.get("keywords") or [])
    authors = _normalize_rule_list(rule.get("authors") or [])
    venues = _normalize_rule_list(rule.get("venues") or [])
    if not keywords and not authors and not venues:
        return False

    text = f"{paper.get('title', '')} {paper.get('summary', '')}".lower()
    paper_authors = paper.get("authors") or []
    if isinstance(paper_authors, str):
        paper_authors = [paper_authors]
    author_text = " ".join(str(a) for a in paper_authors).lower()
    categories = paper.get("categories") or []
    if isinstance(categories, str):
        categories = [categories]
    categories_text = " ".join(str(c) for c in categories).lower()

    if keywords and not any(kw in text for kw in keywords):
        return False
    if authors and not any(a in author_text for a in authors):
        return False
    if venues and not any(v in categories_text for v in venues):
        return False
    min_novelty = _rule_min_novelty(rule)
    if min_novelty > 0:
        try:
            novelty = float(paper.get("novelty_score"))
        except Exception:
            novelty = -1.0
        if novelty < min_novelty:
            return False
    return True

def _rule_matches_inbox_item(
    rule: Dict[str, Any],
    item: Dict[str, Any],
    novelty_value: Optional[float] = None,
) -> bool:
    if not rule or not item:
        return False
    target_kind = _normalize_inbox_kind(rule.get("target_kind"))
    item_kind = _normalize_inbox_kind(item.get("kind"))
    if target_kind and target_kind != item_kind:
        return False

    keywords = _normalize_rule_list(rule.get("keywords") or [])
    authors = _normalize_rule_list(rule.get("authors") or [])
    venues = _normalize_rule_list(rule.get("venues") or [])
    if not keywords and not authors and not venues:
        return False

    changed = item.get("changed_structure_fields") or []
    if not isinstance(changed, list):
        changed = []
    text = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("message") or ""),
            str(item.get("summary") or ""),
            str(item.get("note") or ""),
            str(item.get("paper_id") or ""),
            str(item.get("alert_type") or ""),
            str(item.get("cadence") or ""),
            " ".join(str(x) for x in changed if x),
        ]
    ).lower()
    if keywords and not any(kw in text for kw in keywords):
        return False
    if authors and not any(author in text for author in authors):
        return False
    if venues and not any(venue in text for venue in venues):
        return False
    min_novelty = _rule_min_novelty(rule)
    if min_novelty > 0:
        try:
            nov = float(novelty_value if novelty_value is not None else item.get("novelty_score"))
        except Exception:
            nov = -1.0
        if nov < min_novelty:
            return False
    return True

def _apply_inbox_rules_to_papers(
    papers: List[Dict[str, Any]],
    rules: Optional[List[Dict[str, Any]]] = None,
    dry_run: bool = False,
    preview_limit: int = 200,
) -> Dict[str, Any]:
    active_rules = [
        r for r in (rules or storage.list_inbox_rules(enabled_only=True))
        if _normalize_rule_scope(r.get("scope")) in {"papers", "all"}
    ]
    if not papers or not active_rules:
        return {
            "scope": "papers",
            "dry_run": bool(dry_run),
            "matched": 0,
            "applied": 0,
            "dismissed": 0,
            "labeled": 0,
            "audit_count": 0,
            "matches": [],
        }

    ids = [p.get("id") for p in papers if p.get("id")]
    status_map = storage.get_interaction_status_map(ids)
    dismissed = 0
    labeled = 0
    matched = 0
    applied = 0
    preview_cap = max(10, min(int(preview_limit or 200), 1000))
    matches: List[Dict[str, Any]] = []
    audit_rows: List[Dict[str, Any]] = []
    pending_interactions: List[tuple[str, str]] = []
    pending_labels: List[tuple[str, str, str]] = []
    now_dt = datetime.now()

    for p in papers:
        pid = p.get("id")
        if not pid:
            continue
        status = status_map.get(pid) or "new"
        for rule in active_rules:
            if not _rule_matches(rule, p):
                continue
            matched += 1
            action = str(rule.get("action") or "label").lower()
            result = "matched"
            if _rule_is_in_quiet_hours(rule, now_dt):
                result = "quiet_hours"
                match_item = {
                    "scope": "papers",
                    "rule_id": rule.get("id"),
                    "rule_name": rule.get("name"),
                    "action": action,
                    "paper_id": pid,
                    "title": p.get("title") or pid,
                    "result": result,
                }
                if len(matches) < preview_cap:
                    matches.append(match_item)
                audit_rows.append(
                    {
                        "rule_id": rule.get("id"),
                        "scope": "papers",
                        "target_kind": None,
                        "action": action,
                        "item_ref": str(pid),
                        "item_kind": "paper",
                        "result": result,
                        "meta": {"title": p.get("title"), "dry_run": bool(dry_run)},
                    }
                )
                break
            if action == "dismiss":
                if status == "new":
                    if not dry_run:
                        pending_interactions.append((str(pid), "dismissed"))
                        status = "dismissed"
                    dismissed += 1
                    applied += 1
                    result = "dismissed"
                else:
                    result = "skipped_status"
            else:
                if status == "new":
                    label = rule.get("label") or rule.get("name") or "Rule"
                    if not dry_run:
                        pending_labels.append((str(pid), str(label), f"rule:{rule.get('id')}"))
                    else:
                        labeled += 1
                    applied += 1
                    result = "labeled"
                else:
                    result = "skipped_status"
            match_item = {
                "scope": "papers",
                "rule_id": rule.get("id"),
                "rule_name": rule.get("name"),
                "action": action,
                "paper_id": pid,
                "title": p.get("title") or pid,
                "result": result,
            }
            if len(matches) < preview_cap:
                matches.append(match_item)
            audit_rows.append(
                {
                    "rule_id": rule.get("id"),
                    "scope": "papers",
                    "target_kind": None,
                    "action": action,
                    "item_ref": str(pid),
                    "item_kind": "paper",
                    "result": result,
                    "meta": {"title": p.get("title"), "dry_run": bool(dry_run)},
                }
            )
            break

    if not dry_run:
        if pending_interactions:
            storage.batch_update_interactions(pending_interactions)
        if pending_labels:
            labeled += int(storage.add_paper_labels_bulk(pending_labels) or 0)

    if (dismissed or labeled) and not dry_run:
        _bump_api_cache_epochs("papers")
    audit_count = storage.add_inbox_rule_audit(audit_rows) if audit_rows else 0
    return {
        "scope": "papers",
        "dry_run": bool(dry_run),
        "matched": matched,
        "applied": applied,
        "dismissed": dismissed,
        "labeled": labeled,
        "audit_count": int(audit_count),
        "matches": matches,
    }

def _apply_inbox_rules_to_unified_items(
    rules: Optional[List[Dict[str, Any]]] = None,
    dry_run: bool = False,
    limit: int = 200,
    version_scope: str = "watchlist",
    version_days: int = 30,
) -> Dict[str, Any]:
    active_rules = [
        r for r in (rules or storage.list_inbox_rules(enabled_only=True))
        if _normalize_rule_scope(r.get("scope")) in {"inbox", "all"}
    ]
    if not active_rules:
        return {
            "scope": "inbox",
            "dry_run": bool(dry_run),
            "matched": 0,
            "applied": 0,
            "audit_count": 0,
            "matches": [],
        }

    wanted_kinds: List[str] = []
    for rule in active_rules:
        k = _normalize_inbox_kind(rule.get("target_kind"))
        if k and k not in wanted_kinds:
            wanted_kinds.append(k)
    inbox_payload = _build_unified_inbox_payload(
        limit=max(80, min(300, int(limit or 200) * 2)),
        version_scope=version_scope,
        version_days=version_days,
        kinds=wanted_kinds or None,
        include_items=True,
    )
    items = list(inbox_payload.get("items") or [])
    if not items:
        return {
            "scope": "inbox",
            "dry_run": bool(dry_run),
            "matched": 0,
            "applied": 0,
            "audit_count": 0,
            "matches": [],
        }

    novelty_by_pid: Dict[str, float] = {}
    if any(_rule_min_novelty(r) > 0 for r in active_rules):
        paper_ids = sorted({str(it.get("paper_id") or "") for it in items if it.get("paper_id")})
        if paper_ids:
            for row in storage.get_papers_by_ids(paper_ids):
                pid = str(row.get("id") or "")
                if not pid:
                    continue
                try:
                    novelty_by_pid[pid] = float(row.get("novelty_score"))
                except Exception:
                    novelty_by_pid[pid] = -1.0

    matched = 0
    applied = 0
    preview_cap = max(10, min(int(limit or 200), 1000))
    matches: List[Dict[str, Any]] = []
    audit_rows: List[Dict[str, Any]] = []
    now_dt = datetime.now()

    for item in items:
        item_kind = _normalize_inbox_kind(item.get("kind"))
        if not item_kind:
            continue
        for rule in active_rules:
            pid = str(item.get("paper_id") or "")
            novelty_value = None
            if pid and pid in novelty_by_pid:
                novelty_value = novelty_by_pid.get(pid)
            if not _rule_matches_inbox_item(rule, item, novelty_value=novelty_value):
                continue
            matched += 1
            action = str(rule.get("action") or "").strip().lower() or _default_inbox_action_for_kind(item_kind)
            snooze_days = max(1, min(int(rule.get("snooze_days") or 3), 90))
            payload = {
                "kind": item_kind,
                "action": action,
                "alert_id": item.get("alert_id"),
                "follow_id": item.get("follow_id"),
                "digest_id": item.get("digest_id"),
                "paper_id": item.get("paper_id"),
                "arxiv_base_id": item.get("arxiv_base_id"),
                "snooze_days": snooze_days,
            }
            item_ref = str(item.get("id") or item.get("alert_id") or item.get("follow_id") or item.get("digest_id") or "")
            result = "matched"
            error = None
            if _rule_is_in_quiet_hours(rule, now_dt):
                result = "quiet_hours"
            elif dry_run:
                result = "would_apply"
            else:
                try:
                    _apply_inbox_action_internal(InboxActionRequest(**payload))
                    applied += 1
                    result = "applied"
                except HTTPException as e:
                    error = str(e.detail)
                    result = f"error:{e.status_code}"
                except Exception as e:
                    error = str(e)
                    result = "error:500"
            row = {
                "scope": "inbox",
                "rule_id": rule.get("id"),
                "rule_name": rule.get("name"),
                "kind": item_kind,
                "action": action,
                "item_ref": item_ref,
                "title": item.get("title") or item_ref,
                "result": result,
            }
            if error:
                row["error"] = error
            if len(matches) < preview_cap:
                matches.append(row)
            audit_rows.append(
                {
                    "rule_id": rule.get("id"),
                    "scope": "inbox",
                    "target_kind": item_kind,
                    "action": action,
                    "item_ref": item_ref,
                    "item_kind": item_kind,
                    "result": result,
                    "meta": {"title": item.get("title"), "error": error, "dry_run": bool(dry_run)},
                }
            )
            break

    audit_count = storage.add_inbox_rule_audit(audit_rows) if audit_rows else 0
    return {
        "scope": "inbox",
        "dry_run": bool(dry_run),
        "matched": matched,
        "applied": applied,
        "audit_count": int(audit_count),
        "matches": matches,
    }

def _run_inbox_rules(scope: str = "papers", dry_run: bool = False, limit: int = 200) -> Dict[str, Any]:
    selected_scope = _normalize_rule_scope(scope)
    rules = storage.list_inbox_rules(enabled_only=True)
    if not rules:
        return {
            "scope": selected_scope,
            "dry_run": bool(dry_run),
            "matched": 0,
            "applied": 0,
            "dismissed": 0,
            "labeled": 0,
            "audit_count": 0,
            "results": [],
        }

    results: List[Dict[str, Any]] = []
    totals = {"matched": 0, "applied": 0, "dismissed": 0, "labeled": 0, "audit_count": 0}

    if selected_scope in {"papers", "all"}:
        paper_cap = max(200, min(3000, int(limit or 200) * 8))
        papers: List[Dict[str, Any]] = []
        page_offset = 0
        while len(papers) < paper_cap:
            page_limit = min(400, paper_cap - len(papers))
            page_rows, _ = storage.get_papers_page_by_status(
                status="new",
                limit=page_limit,
                offset=page_offset,
                dedupe_latest=True,
                include_total=False,
            )
            if not page_rows:
                break
            papers.extend(page_rows)
            page_offset += len(page_rows)
            if len(page_rows) < page_limit:
                break
        paper_result = _apply_inbox_rules_to_papers(
            papers,
            rules=rules,
            dry_run=dry_run,
            preview_limit=limit,
        )
        results.append(paper_result)
        for k in totals:
            totals[k] += int(paper_result.get(k) or 0)

    if selected_scope in {"inbox", "all"}:
        inbox_result = _apply_inbox_rules_to_unified_items(
            rules=rules,
            dry_run=dry_run,
            limit=limit,
        )
        results.append(inbox_result)
        for k in totals:
            totals[k] += int(inbox_result.get(k) or 0)

    response = {
        "scope": selected_scope,
        "dry_run": bool(dry_run),
        "matched": int(totals["matched"]),
        "applied": int(totals["applied"]),
        "dismissed": int(totals["dismissed"]),
        "labeled": int(totals["labeled"]),
        "audit_count": int(totals["audit_count"]),
        "results": results,
    }
    if not bool(dry_run):
        _clear_inbox_rule_diag_cache()
    return response

def _build_inbox_rule_diagnostics(limit: int = 200) -> Dict[str, Any]:
    rules = storage.list_inbox_rules(enabled_only=False)
    diagnostics: List[Dict[str, Any]] = []
    if not rules:
        return {"count": 0, "items": [], "summary": {"warn": 0, "info": 0, "error": 0}}

    preview = _run_inbox_rules(scope="all", dry_run=True, limit=max(20, min(400, int(limit or 200))))
    matched_rule_ids: set[str] = set()
    for section in (preview.get("results") or []):
        for match in (section.get("matches") or []):
            rid = str(match.get("rule_id") or "").strip()
            if rid:
                matched_rule_ids.add(rid)

    def _add_diag(
        dtype: str,
        severity: str,
        message: str,
        rule: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        row = {
            "type": str(dtype or "notice"),
            "severity": str(severity or "info"),
            "message": str(message or "").strip(),
        }
        if isinstance(rule, dict):
            row["rule_id"] = str(rule.get("id") or "")
            row["rule_name"] = str(rule.get("name") or "")
        if isinstance(extra, dict) and extra:
            row["meta"] = extra
        diagnostics.append(row)

    signatures: Dict[str, List[Dict[str, Any]]] = {}
    conflict_signatures: Dict[str, List[Dict[str, Any]]] = {}

    for rule in rules:
        rid = str(rule.get("id") or "")
        enabled = bool(rule.get("enabled"))
        keywords = _normalize_rule_list(rule.get("keywords") or [])
        authors = _normalize_rule_list(rule.get("authors") or [])
        venues = _normalize_rule_list(rule.get("venues") or [])
        action = str(rule.get("action") or "").strip().lower() or "label"
        scope = _normalize_rule_scope(rule.get("scope"))
        target_kind = _normalize_inbox_kind(rule.get("target_kind"))
        snooze_days = max(1, min(90, int(rule.get("snooze_days") or 3)))
        min_novelty = _rule_min_novelty(rule)
        try:
            quiet_start = int(rule.get("quiet_hours_start") if rule.get("quiet_hours_start") is not None else -1)
        except Exception:
            quiet_start = -1
        try:
            quiet_end = int(rule.get("quiet_hours_end") if rule.get("quiet_hours_end") is not None else -1)
        except Exception:
            quiet_end = -1
        label = str(rule.get("label") or "").strip()
        condition_count = len(keywords) + len(authors) + len(venues) + (1 if min_novelty > 0 else 0)

        if enabled and condition_count == 0:
            _add_diag(
                "empty_conditions",
                "warn",
                "Rule has no keyword/author/category filters and may never match.",
                rule=rule,
            )
        if enabled and rid and rid not in matched_rule_ids:
            _add_diag(
                "no_matches",
                "warn",
                "Rule did not match any items in current preview.",
                rule=rule,
            )
        if enabled and condition_count <= 1 and not target_kind:
            _add_diag(
                "broad_rule",
                "info",
                "Rule is broad (very few conditions and no target kind).",
                rule=rule,
            )
        if enabled and action == "label" and not label:
            _add_diag(
                "missing_label",
                "warn",
                "Label action has empty label; fallback naming may be unclear.",
                rule=rule,
            )
        if enabled and action == "snooze" and snooze_days <= 1:
            _add_diag(
                "short_snooze",
                "info",
                "Snooze window is very short (<=1 day).",
                rule=rule,
                extra={"snooze_days": snooze_days},
            )
        quiet_ok = (0 <= quiet_start <= 23 and 0 <= quiet_end <= 23 and quiet_start != quiet_end)
        if enabled and ((quiet_start >= 0 or quiet_end >= 0) and not quiet_ok):
            _add_diag(
                "quiet_hours_invalid",
                "warn",
                "Quiet-hours window is invalid. Use two different hours in 0-23.",
                rule=rule,
                extra={"quiet_hours_start": quiet_start, "quiet_hours_end": quiet_end},
            )
        if enabled and quiet_ok:
            _add_diag(
                "quiet_hours_enabled",
                "info",
                "Rule quiet-hours window is enabled.",
                rule=rule,
                extra={"quiet_hours_start": quiet_start, "quiet_hours_end": quiet_end},
            )

        signature = "|".join(
            [
                scope,
                target_kind or "*",
                action,
                label.lower(),
                str(snooze_days),
                f"{min_novelty:.3f}",
                str(quiet_start),
                str(quiet_end),
                ",".join(sorted(keywords)),
                ",".join(sorted(authors)),
                ",".join(sorted(venues)),
            ]
        )
        signatures.setdefault(signature, []).append(rule)

        conflict_signature = "|".join(
            [
                scope,
                target_kind or "*",
                f"{min_novelty:.3f}",
                ",".join(sorted(keywords)),
                ",".join(sorted(authors)),
                ",".join(sorted(venues)),
            ]
        )
        conflict_signatures.setdefault(conflict_signature, []).append(rule)

    for grouped in signatures.values():
        if len(grouped) <= 1:
            continue
        names = [str(r.get("name") or r.get("id") or "") for r in grouped]
        for rule in grouped:
            _add_diag(
                "duplicate_rule",
                "warn",
                "Rule appears duplicated with identical conditions and action.",
                rule=rule,
                extra={"duplicates": names},
            )

    for grouped in conflict_signatures.values():
        if len(grouped) <= 1:
            continue
        actions = {str(r.get("action") or "").strip().lower() or "label" for r in grouped}
        if len(actions) <= 1:
            continue
        names = [str(r.get("name") or r.get("id") or "") for r in grouped]
        for rule in grouped:
            _add_diag(
                "conflicting_actions",
                "warn",
                "Multiple rules share the same conditions but trigger different actions.",
                rule=rule,
                extra={"peer_rules": names, "actions": sorted(actions)},
            )

    summary = {
        "warn": sum(1 for row in diagnostics if row.get("severity") == "warn"),
        "info": sum(1 for row in diagnostics if row.get("severity") == "info"),
        "error": sum(1 for row in diagnostics if row.get("severity") == "error"),
    }
    return {
        "count": len(diagnostics),
        "items": diagnostics[: max(20, min(1000, int(limit or 200) * 4))],
        "summary": summary,
        "matched_rule_ids": sorted(matched_rule_ids),
    }

def _maybe_create_version_alerts(papers: List[Dict[str, Any]]) -> int:
    if not papers:
        return 0
    candidates = []
    base_ids = set()
    for p in papers:
        pid = p.get("id")
        if not pid:
            continue
        base_id, ver = _split_arxiv_version(pid)
        if base_id:
            base_ids.add(base_id)
        candidates.append((pid, base_id, ver))

    if not base_ids:
        return 0

    existing = storage.get_papers_by_base_ids(list(base_ids))
    existing_by_base: Dict[str, List[tuple[str, int]]] = {}
    for p in existing:
        pid = p.get("id")
        if not pid:
            continue
        base_id, ver = _split_arxiv_version(pid)
        if not base_id:
            continue
        existing_by_base.setdefault(base_id, []).append((pid, ver))

    rows = []
    for pid, base_id, ver in candidates:
        if ver <= 1 or not base_id:
            continue
        prior_versions = [
            v for (existing_pid, v) in existing_by_base.get(base_id, [])
            if existing_pid != pid
        ]
        if not prior_versions:
            continue
        prev = max(prior_versions)
        if ver > prev:
            rows.append({
                "paper_id": pid,
                "alert_type": "version",
                "message": f"New arXiv version v{ver} (was v{prev})",
            })

    if not rows:
        return 0
    return storage.create_alerts(rows)

def _handle_fetched_papers(papers: List[Dict[str, Any]], batch_date: str) -> Dict[str, Any]:
    new_count = storage.save_papers(papers)
    version_alerts = _maybe_create_version_alerts(papers)
    rules_result = _apply_inbox_rules_to_papers(papers)

    ids = [p['id'] for p in papers]
    task_count = 0
    with _FETCH_PIPELINE_LOCK:
        pipeline_active = _FETCH_PIPELINE_ACTIVE

    if pipeline_active:
        if ids:
            _track_fetch_task(enrich_citations, ids)
            task_count += 1
        if papers:
            _track_fetch_task(background_index, papers)
            task_count += 1
            _track_fetch_task(enrich_structures, papers)
            task_count += 1
            _track_fetch_task(generate_alerts_for_papers, papers)
            task_count += 1
        if task_count == 0:
            _end_fetch_pipeline()
    else:
        if ids:
            threading.Thread(target=enrich_citations, args=(ids,), daemon=True).start()
        if papers:
            threading.Thread(target=background_index, args=(papers,), daemon=True).start()
            threading.Thread(target=enrich_structures, args=(papers,), daemon=True).start()
            threading.Thread(target=generate_alerts_for_papers, args=(papers,), daemon=True).start()

    _bump_api_cache_epochs("papers", "stats")

    return {
        "fetched": len(papers),
        "new": new_count,
        "date": batch_date,
        "version_alerts": version_alerts,
        "rules": rules_result,
    }

def _estimate_job_duration_seconds(job_type: str) -> float:
    with _JOB_LOCK:
        hist = list(_JOB_DURATIONS.get(job_type, []))
    if hist:
        return max(1.0, sum(hist) / len(hist))
    return max(1.0, float(JOB_DEFAULT_DURATION_SEC.get(job_type, 30.0)))

def _record_job_duration(job_type: str, duration_seconds: float):
    duration = max(0.1, float(duration_seconds))
    with _JOB_LOCK:
        hist = _JOB_DURATIONS.setdefault(job_type, [])
        hist.append(duration)
        if len(hist) > JOB_DURATION_HISTORY_LIMIT:
            del hist[:-JOB_DURATION_HISTORY_LIMIT]

def _log_event(event: str, level: str = "info", **fields: Any) -> None:
    lvl = (level or "info").lower()
    if lvl not in {"info", "warn", "error"}:
        lvl = "info"
    payload = {"event": event, "level": lvl, "ts": datetime.now().isoformat()}
    payload.update(fields)
    line = None
    try:
        line = json.dumps(payload, default=str)
        print(line)
    except Exception:
        line = f"{event} {payload}"
        print(line)
    _write_log_line(line)

def _log_request_timing(event: str, start_ts: float, **fields: Any) -> None:
    duration = max(0.0, time.perf_counter() - start_ts)
    fields.setdefault("duration_ms", round(duration * 1000, 2))
    fields.setdefault("slow", duration >= SLOW_REQUEST_THRESHOLD_SEC)
    status = fields.get("status")
    level = "info"
    if status == "error":
        level = "error"
    elif fields.get("slow"):
        level = "warn"
    _log_event(event, level=level, **fields)

def _write_log_line(line: str) -> None:
    if not line:
        return
    try:
        log_path = _get_log_path()
        if not log_path:
            return
        with _LOG_LOCK:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        pass

def _get_log_path() -> Optional[str]:
    global _LOG_CURRENT_DATE, _LOG_FILE_PATH
    today = datetime.now().strftime("%Y-%m-%d")
    if _LOG_CURRENT_DATE != today:
        _LOG_CURRENT_DATE = today
        os.makedirs(LOG_DIR, exist_ok=True)
        _LOG_FILE_PATH = os.path.join(LOG_DIR, f"{LOG_FILE_PREFIX}-{today}.log")
        _cleanup_old_logs()
    return _LOG_FILE_PATH

def _cleanup_old_logs() -> None:
    try:
        cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
        if not os.path.isdir(LOG_DIR):
            return
        for name in os.listdir(LOG_DIR):
            if not name.startswith(f"{LOG_FILE_PREFIX}-") or not name.endswith(".log"):
                continue
            date_part = name[len(LOG_FILE_PREFIX) + 1:-4]
            try:
                log_date = datetime.strptime(date_part, "%Y-%m-%d")
            except Exception:
                continue
            if log_date < cutoff:
                try:
                    os.remove(os.path.join(LOG_DIR, name))
                except Exception:
                    pass
    except Exception:
        pass

def _api_cache_get(key: str, ttl_seconds: int, epoch_key: str) -> Optional[Any]:
    now_ts = datetime.now().timestamp()
    with _API_CACHE_LOCK:
        entry = _API_CACHE.get(key)
        if not entry:
            return None
        if entry.get("epoch") != _API_CACHE_EPOCHS.get(epoch_key, 0):
            return None
        created_at = entry.get("created_at_ts", 0.0)
        if ttl_seconds is not None and (now_ts - created_at) > ttl_seconds:
            return None
        payload = entry.get("payload")
    if isinstance(payload, (dict, list)):
        try:
            return copy.deepcopy(payload)
        except Exception:
            return payload
    return payload

def _api_cache_set(key: str, payload: Any, epoch_key: str) -> None:
    now_ts = datetime.now().timestamp()
    with _API_CACHE_LOCK:
        _API_CACHE[key] = {
            "payload": payload,
            "created_at_ts": now_ts,
            "epoch": _API_CACHE_EPOCHS.get(epoch_key, 0),
        }

def _etag_for_cache_key(cache_key: str, epoch_key: str) -> str:
    epoch = _API_CACHE_EPOCHS.get(epoch_key, 0)
    payload = f"{cache_key}:{epoch}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()

def _etag_matches(if_none_match: Optional[str], etag: str) -> bool:
    if not if_none_match:
        return False
    return if_none_match.replace('"', '').strip() == etag

def _client_cache_warm(request: Optional[Request]) -> bool:
    if request is None:
        return False
    return (request.headers.get("x-client-cache") or "").lower() == "warm"

def _get_paged_rank_cache(key: str, epoch_key: str) -> Optional[List[str]]:
    now_ts = time.time()
    with _PAGED_RANK_CACHE_LOCK:
        entry = _PAGED_RANK_CACHE.get(key)
        if not entry:
            return None
        if entry.get("epoch") != _API_CACHE_EPOCHS.get(epoch_key, 0):
            return None
        created_at = entry.get("created_at_ts", 0.0)
        if (now_ts - created_at) > _PAGED_RANK_CACHE_TTL_SECONDS:
            return None
        ids = entry.get("ids") or []
    return list(ids)

def _set_paged_rank_cache(key: str, ids: List[str], epoch_key: str) -> None:
    now_ts = time.time()
    with _PAGED_RANK_CACHE_LOCK:
        _PAGED_RANK_CACHE[key] = {
            "ids": list(ids or []),
            "created_at_ts": now_ts,
            "epoch": _API_CACHE_EPOCHS.get(epoch_key, 0),
        }

def _bump_api_cache_epochs(*keys: str):
    with _API_CACHE_LOCK:
        for key in keys:
            _API_CACHE_EPOCHS[key] = _API_CACHE_EPOCHS.get(key, 0) + 1

def _start_fetch_pipeline() -> bool:
    global _FETCH_PIPELINE_ACTIVE, _FETCH_PIPELINE_TASKS, _FETCH_PIPELINE_STARTED_AT
    with _FETCH_PIPELINE_LOCK:
        if _FETCH_PIPELINE_ACTIVE:
            return False
        _FETCH_PIPELINE_ACTIVE = True
        _FETCH_PIPELINE_TASKS = 0
        _FETCH_PIPELINE_STARTED_AT = datetime.now().isoformat()
        return True

def _end_fetch_pipeline():
    global _FETCH_PIPELINE_ACTIVE, _FETCH_PIPELINE_TASKS, _FETCH_PIPELINE_STARTED_AT
    with _FETCH_PIPELINE_LOCK:
        _FETCH_PIPELINE_ACTIVE = False
        _FETCH_PIPELINE_TASKS = 0
        _FETCH_PIPELINE_STARTED_AT = None

def _fetch_task_done():
    global _FETCH_PIPELINE_ACTIVE, _FETCH_PIPELINE_TASKS, _FETCH_PIPELINE_STARTED_AT
    with _FETCH_PIPELINE_LOCK:
        _FETCH_PIPELINE_TASKS = max(0, _FETCH_PIPELINE_TASKS - 1)
        if _FETCH_PIPELINE_TASKS <= 0:
            _FETCH_PIPELINE_ACTIVE = False
            _FETCH_PIPELINE_STARTED_AT = None

def _track_fetch_task(fn, *args):
    global _FETCH_PIPELINE_TASKS
    with _FETCH_PIPELINE_LOCK:
        _FETCH_PIPELINE_TASKS += 1

    def _runner():
        try:
            fn(*args)
        finally:
            _fetch_task_done()

    threading.Thread(target=_runner, daemon=True).start()

def _queue_position_for_job(job_id: str) -> Optional[int]:
    with _JOB_QUEUE.mutex:
        queued = list(_JOB_QUEUE.queue)
    try:
        return queued.index(job_id) + 1
    except ValueError:
        return None

def _decorate_job_for_client(job: Dict[str, Any]) -> Dict[str, Any]:
    payload = json.loads(json.dumps(job))
    status = str(payload.get("status") or "unknown")
    now = datetime.now()
    eta_seconds = None
    queue_position = None

    if status == "queued":
        queue_position = _queue_position_for_job(str(payload.get("id", "")))
        est = _estimate_job_duration_seconds(str(payload.get("type", "")))
        if queue_position is not None:
            slots_before = max(0, queue_position - 1)
            eta_seconds = round((slots_before / max(1, JOB_WORKER_COUNT)) * est, 1)
            progress = min(15.0, 2.0 + min(10.0, float(slots_before)))
        else:
            progress = 2.0
    elif status in {"running", "canceling"}:
        est = _estimate_job_duration_seconds(str(payload.get("type", "")))
        started = _parse_iso_datetime(payload.get("started_at")) or _parse_iso_datetime(payload.get("updated_at"))
        elapsed = max(0.0, (now - started).total_seconds()) if started else 0.0
        eta_seconds = round(max(0.0, est - elapsed), 1)
        progress = min(99.0, (elapsed / max(1.0, est)) * 100.0)
    elif status in {"completed", "error", "canceled"}:
        eta_seconds = 0.0
        progress = 100.0
    else:
        progress = 0.0

    payload["progress_percent"] = round(progress, 1)
    payload["eta_seconds"] = eta_seconds
    payload["queue_position"] = queue_position
    payload["cancelable"] = status in {"queued", "running", "canceling"}
    payload["cancel_requested"] = bool(payload.get("cancel_requested"))
    return payload

def _create_job(job_type: str, payload: Dict[str, Any], max_attempts: int = JOB_MAX_ATTEMPTS) -> Dict[str, Any]:
    now = datetime.now().isoformat()
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "type": job_type,
        "payload": payload or {},
        "status": "queued",
        "attempts": 0,
        "max_attempts": max(1, int(max_attempts)),
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
        "cancel_requested": False,
        "cancel_requested_at": None,
    }
    with _JOB_LOCK:
        _JOBS[job_id] = job
    try:
        storage.create_job_record(job)
    except Exception as e:
        print(f"Failed to persist job {job_id}: {e}")
    _JOB_QUEUE.put(job_id)
    return job

def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            job = None
        else:
            return json.loads(json.dumps(job))
    try:
        job = storage.get_job_record(job_id)
    except Exception as e:
        print(f"Failed to load job {job_id} from storage: {e}")
        job = None
    if job:
        with _JOB_LOCK:
            _JOBS[job_id] = job
        return json.loads(json.dumps(job))
    return None

def _update_job(job_id: str, **fields) -> Optional[Dict[str, Any]]:
    persisted = None
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        job.update(fields)
        job["updated_at"] = datetime.now().isoformat()
        persisted = json.loads(json.dumps(job))
    try:
        storage.update_job_record(job_id, job)
    except Exception as e:
        print(f"Failed to persist job update {job_id}: {e}")
    return persisted

def _cancel_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None

        status = str(job.get("status") or "unknown")
        if status in {"completed", "error", "canceled"}:
            return json.loads(json.dumps(job))

        now_iso = datetime.now().isoformat()
        job["cancel_requested"] = True
        job["cancel_requested_at"] = now_iso

        if status == "queued":
            job["status"] = "canceled"
            job["error"] = "Canceled by user."
            job["finished_at"] = now_iso
        elif status in {"running", "canceling"}:
            job["status"] = "canceling"
            job["error"] = "Cancel requested by user."
        else:
            job["status"] = "canceling"
            job["error"] = "Cancel requested by user."

        job["updated_at"] = now_iso
        snapshot = json.loads(json.dumps(job))
    try:
        storage.update_job_record(job_id, job)
    except Exception as e:
        print(f"Failed to persist job cancel {job_id}: {e}")
    return snapshot

def _execute_job(job_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if job_type == "compare_matrix":
        return _compute_compare_matrix(payload.get("paper_ids") or [])
    if job_type == "benchmark_extract":
        return _compute_benchmark_table(payload.get("paper_ids") or [])
    if job_type == "reproducibility":
        paper_id = payload.get("paper_id")
        if not paper_id:
            raise ValueError("paper_id is required for reproducibility job")
        return _compute_reproducibility_scorecard(str(paper_id))
    if job_type == "discover":
        return _run_discover_pipeline()
    raise ValueError(f"Unsupported job type: {job_type}")

def _job_worker_loop(worker_name: str):
    while not _JOB_STOP_EVENT.is_set():
        try:
            job_id = _JOB_QUEUE.get(timeout=0.5)
        except queue.Empty:
            continue

        try:
            job_type = None
            payload: Dict[str, Any] = {}
            run_started_at = datetime.now()
            with _JOB_LOCK:
                job = _JOBS.get(job_id)
                if not job:
                    continue
                if job["status"] in {"completed", "error", "canceled"}:
                    continue
                if bool(job.get("cancel_requested")) and job.get("status") in {"queued", "canceling"}:
                    job["status"] = "canceled"
                    job["error"] = "Canceled by user."
                    now_iso = datetime.now().isoformat()
                    job["finished_at"] = now_iso
                    job["updated_at"] = now_iso
                    try:
                        storage.update_job_record(job_id, job)
                    except Exception as e:
                        print(f"Failed to persist job cancel during run {job_id}: {e}")
                    continue
                attempts = int(job.get("attempts", 0)) + 1
                job["status"] = "running"
                job["attempts"] = attempts
                job["started_at"] = datetime.now().isoformat()
                job["updated_at"] = job["started_at"]
                job["error"] = None
                job_type = str(job.get("type") or "")
                payload = dict(job.get("payload") or {})
                run_started_at = datetime.now()
                try:
                    storage.update_job_record(job_id, job)
                except Exception as e:
                    print(f"Failed to persist job start {job_id}: {e}")

            result = _execute_job(job_type, payload)
            run_elapsed = max(0.1, (datetime.now() - run_started_at).total_seconds())
            _record_job_duration(job_type, run_elapsed)

            current = _get_job(job_id) or {}
            if bool(current.get("cancel_requested")):
                _update_job(
                    job_id,
                    status="canceled",
                    result=None,
                    finished_at=datetime.now().isoformat(),
                    error="Canceled by user.",
                )
            else:
                _update_job(
                    job_id,
                    status="completed",
                    result=result,
                    finished_at=datetime.now().isoformat(),
                    error=None,
                )
        except Exception as e:
            current = _get_job(job_id) or {}
            if bool(current.get("cancel_requested")):
                _update_job(
                    job_id,
                    status="canceled",
                    error="Canceled by user.",
                    finished_at=datetime.now().isoformat(),
                )
                continue

            attempts = int(current.get("attempts", 1))
            max_attempts = int(current.get("max_attempts", JOB_MAX_ATTEMPTS))
            if attempts < max_attempts and not _JOB_STOP_EVENT.is_set():
                _update_job(job_id, status="queued", error=str(e))
                _JOB_QUEUE.put(job_id)
            else:
                _update_job(
                    job_id,
                    status="error",
                    error=str(e),
                    finished_at=datetime.now().isoformat(),
                )
        finally:
            _JOB_QUEUE.task_done()

def _start_job_workers():
    for idx in range(JOB_WORKER_COUNT):
        t = threading.Thread(
            target=_job_worker_loop,
            args=(f"job-worker-{idx+1}",),
            daemon=True,
        )
        t.start()

def _build_job_queue_ops() -> Dict[str, Any]:
    with _JOB_LOCK:
        jobs = [json.loads(json.dumps(j)) for j in _JOBS.values()]
    jobs = [_decorate_job_for_client(j) for j in jobs]
    by_status = {}
    for j in jobs:
        s = j.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
    jobs.sort(key=lambda j: j.get("updated_at", ""), reverse=True)
    recent = [
        {
            "id": j.get("id"),
            "type": j.get("type"),
            "status": j.get("status"),
            "attempts": j.get("attempts"),
            "max_attempts": j.get("max_attempts"),
            "updated_at": j.get("updated_at"),
            "error": j.get("error"),
            "progress_percent": j.get("progress_percent"),
            "eta_seconds": j.get("eta_seconds"),
            "queue_position": j.get("queue_position"),
        }
        for j in jobs[:20]
    ]
    return {
        "total": len(jobs),
        "queue_size": int(by_status.get("queued", 0)),
        "by_status": by_status,
        "recent": recent,
    }

def _build_scheduler_agent_ops() -> Dict[str, Any]:
    now = datetime.now()
    agents = storage.list_saved_search_agents()
    items = []
    due_now = 0
    for a in agents:
        cadence = (a.get("cadence") or "daily").lower()
        every = timedelta(days=7 if cadence == "weekly" else 1)
        base = _parse_iso_datetime(a.get("last_run_at")) or _parse_iso_datetime(a.get("created_at")) or now
        next_due = base + every
        overdue = now >= next_due
        if overdue:
            due_now += 1
        items.append({
            "id": a.get("id"),
            "name": a.get("name"),
            "query": a.get("query"),
            "cadence": cadence,
            "max_results": a.get("max_results"),
            "last_run_at": a.get("last_run_at"),
            "last_matches_count": a.get("last_matches_count"),
            "next_due_at": next_due.isoformat(),
            "overdue": overdue,
        })
    items.sort(key=lambda x: (not x["overdue"], x["next_due_at"]))
    return {
        "total": len(items),
        "due_now": due_now,
        "items": items,
    }

def _run_saved_search_agent(agent: Dict, trigger: str = "manual") -> Dict:
    agent_id = int(agent["id"])
    with _SAVED_SEARCH_RUN_LOCK:
        if agent_id in _ACTIVE_SEARCH_RUNS:
            return {"agent_id": agent_id, "skipped": True, "reason": "already-running"}
        _ACTIVE_SEARCH_RUNS.add(agent_id)

    try:
        query = str(agent.get("query") or "").strip()
        mode = str(agent.get("mode") or "global").strip().lower() or "global"
        if mode not in {"global", "semantic", "local"}:
            mode = "global"
        source_paper_id = str(agent.get("source_paper_id") or "").strip() or None
        max_results = max(1, int(agent.get("max_results") or 8))
        papers: List[Dict[str, Any]] = []
        query_used = query

        if mode == "semantic":
            seed_text = query
            if source_paper_id:
                seed_paper = _resolve_paper_by_id(source_paper_id)
                if seed_paper:
                    seed_text = f"{seed_paper.get('title', '')}. {seed_paper.get('summary', '')}".strip() or seed_text
                    source_paper_id = seed_paper.get("id")
            query_vec = embeddings.generate_embedding(seed_text)
            query_used = f"semantic:{seed_text[:160]}"
            if query_vec.size > 0:
                scored = storage.search_semantic(query_vec, limit=max(20, max_results * 6))
                score_map = {str(r.get("id") or ""): float(r.get("score") or 0.0) for r in scored if r.get("id")}
                ids = [pid for pid in score_map.keys()]
                fetched = storage.get_papers_by_ids(ids)
                by_id = {p.get("id"): p for p in fetched if p.get("id")}
                ordered: List[Dict[str, Any]] = []
                for pid in ids:
                    paper = by_id.get(pid)
                    if not paper:
                        continue
                    paper = dict(paper)
                    paper["semantic_score"] = round(float(score_map.get(pid) or 0.0), 4)
                    ordered.append(paper)
                    if len(ordered) >= max_results:
                        break
                papers = ordered
        elif mode == "local":
            matches, _total = storage.search_full_text_paged(query, limit=max_results, offset=0)
            ids = [str(m.get("id") or "") for m in matches if m.get("id")]
            papers = storage.get_papers_by_ids(ids) if ids else []
            by_id = {p.get("id"): p for p in papers if p.get("id")}
            ordered: List[Dict[str, Any]] = []
            for pid in ids:
                paper = by_id.get(pid)
                if paper:
                    ordered.append(paper)
            papers = ordered
        else:
            papers = client.search_archive(query, max_results=max_results)

        paper_ids = [p.get("id") for p in papers if p.get("id")]
        seen_ids = storage.get_saved_search_seen_ids(agent_id, paper_ids)
        new_papers = [p for p in papers if p.get("id") and p.get("id") not in seen_ids]

        # Persist all matched ids as seen to suppress repeated noise next runs.
        storage.mark_saved_search_seen(agent_id, paper_ids)
        if mode == "global":
            storage.save_papers(papers)
        created_alerts = generate_alerts_for_papers(new_papers)

        summary = ai_service.summarize_saved_search_results(agent.get("name", "Agent"), query_used, new_papers)
        storage.record_saved_search_run(agent_id, summary, len(new_papers))

        return {
            "agent_id": agent_id,
            "name": agent.get("name"),
            "query": query_used,
            "mode": mode,
            "source_paper_id": source_paper_id,
            "trigger": trigger,
            "matches": len(papers),
            "new_matches": len(new_papers),
            "repeat_matches": max(0, len(papers) - len(new_papers)),
            "created_alerts": created_alerts,
            "summary": summary,
            "papers": new_papers[:10],
        }
    finally:
        with _SAVED_SEARCH_RUN_LOCK:
            _ACTIVE_SEARCH_RUNS.discard(agent_id)

def _saved_search_scheduler_loop():
    is_leader = False
    while not _SCHEDULER_STOP_EVENT.is_set():
        try:
            storage.init_db()
            owns_lock = storage.try_acquire_scheduler_lock(
                SAVED_SEARCH_LOCK_NAME,
                _SCHEDULER_OWNER_ID,
                ttl_seconds=SAVED_SEARCH_LOCK_TTL_SEC,
            )
            if not owns_lock:
                if is_leader:
                    print("Saved-search scheduler leadership lost.")
                is_leader = False
                if _SCHEDULER_STOP_EVENT.wait(SAVED_SEARCH_FOLLOWER_POLL_SEC):
                    break
                continue
            if not is_leader:
                print(f"Saved-search scheduler leader: {_SCHEDULER_OWNER_ID}")
            is_leader = True

            now = datetime.now()
            agents = storage.list_saved_search_agents()
            for agent in agents:
                if _SCHEDULER_STOP_EVENT.is_set():
                    break
                if not storage.heartbeat_scheduler_lock(SAVED_SEARCH_LOCK_NAME, _SCHEDULER_OWNER_ID):
                    print("Saved-search scheduler heartbeat failed; aborting cycle.")
                    is_leader = False
                    break
                if _agent_is_due(agent, now):
                    try:
                        result = _run_saved_search_agent(agent, trigger="scheduler")
                        print(
                            f"Scheduler run agent={agent.get('id')} "
                            f"matches={result.get('matches', 0)} new={result.get('new_matches', 0)}"
                        )
                    except Exception as run_err:
                        print(f"Scheduler run failed for agent {agent.get('id')}: {run_err}")

            if is_leader:
                for cadence in ("daily", "weekly"):
                    if _SCHEDULER_STOP_EVENT.is_set():
                        break
                    try:
                        if _digest_is_due(cadence, now):
                            digest = _generate_digest_run(cadence=cadence, max_items=10, persist=True)
                            print(
                                f"Scheduler digest cadence={cadence} id={digest.get('id')} "
                                f"items={len(digest.get('items') or [])}"
                            )
                    except Exception as digest_err:
                        print(f"Scheduler digest failed cadence={cadence}: {digest_err}")

            if is_leader:
                schedules = storage.list_folder_digest_schedules(enabled_only=True)
                for schedule in schedules:
                    if _SCHEDULER_STOP_EVENT.is_set():
                        break
                    if not storage.heartbeat_scheduler_lock(SAVED_SEARCH_LOCK_NAME, _SCHEDULER_OWNER_ID):
                        print("Saved-search scheduler heartbeat failed; aborting cycle.")
                        is_leader = False
                        break
                    if not _folder_digest_is_due(schedule, now):
                        continue
                    folder = storage.get_folder(str(schedule.get("folder_id")))
                    if not folder:
                        continue
                    try:
                        digest = _generate_folder_digest_run(
                            folder,
                            cadence=str(schedule.get("cadence") or "daily"),
                            max_items=int(schedule.get("max_items") or 10),
                            persist=True,
                        )
                        storage.update_folder_digest_last_run(str(folder.get("id")), now.isoformat())
                        print(
                            f"Scheduler folder digest folder={folder.get('id')} "
                            f"items={len(digest.get('items') or [])}"
                        )
                    except Exception as folder_err:
                        print(f"Scheduler folder digest failed for folder {folder.get('id')}: {folder_err}")

            if is_leader:
                storage.heartbeat_scheduler_lock(SAVED_SEARCH_LOCK_NAME, _SCHEDULER_OWNER_ID)
        except Exception as e:
            print(f"Saved search scheduler error: {e}")
        if _SCHEDULER_STOP_EVENT.wait(SAVED_SEARCH_SCHEDULER_INTERVAL_SEC):
            break

def _refresh_citations_if_due() -> Dict[str, Any]:
    storage.init_db()
    now = datetime.now()
    last_raw = storage.get_ai_cache("citation_refresh:last_run")
    if last_raw:
        last_dt = _parse_iso_datetime(last_raw)
        if last_dt and (now - last_dt).total_seconds() < CITATION_REFRESH_INTERVAL_SEC:
            return {"ran": False, "reason": "not_due"}

    ids = storage.get_papers_for_citation_refresh(limit=300, stale_days=7)
    if not ids:
        storage.set_ai_cache("citation_refresh:last_run", now.isoformat())
        return {"ran": False, "reason": "no_candidates"}

    try:
        counts = citation_service.get_citations(ids)
        if counts:
            storage.update_citations(counts)
            papers = storage.get_papers_by_ids(list(counts.keys()))
            generate_alerts_for_papers(papers)
        storage.set_ai_cache("citation_refresh:last_run", now.isoformat())
        return {"ran": True, "updated": len(counts or {})}
    except Exception as e:
        print(f"Citation refresh failed: {e}")
        return {"ran": False, "error": str(e)}

def _citation_refresh_loop():
    is_leader = False
    while not _SCHEDULER_STOP_EVENT.is_set():
        try:
            storage.init_db()
            owns_lock = storage.try_acquire_scheduler_lock(
                CITATION_REFRESH_LOCK_NAME,
                _SCHEDULER_OWNER_ID,
                ttl_seconds=CITATION_REFRESH_TTL_SEC,
            )
            if not owns_lock:
                is_leader = False
                if _SCHEDULER_STOP_EVENT.wait(CITATION_REFRESH_POLL_SEC):
                    break
                continue
            if not is_leader:
                print(f"Citation refresh leader: {_SCHEDULER_OWNER_ID}")
            is_leader = True
            _refresh_citations_if_due()
            if _SCHEDULER_STOP_EVENT.wait(CITATION_REFRESH_POLL_SEC):
                break
        except Exception as e:
            print(f"Citation refresh loop error: {e}")
            if _SCHEDULER_STOP_EVENT.wait(CITATION_REFRESH_POLL_SEC):
                break

def _daily_fetch_due(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=DAILY_FETCH_START_HOUR, minute=DAILY_FETCH_START_MINUTE, second=0, microsecond=0)
    if now < start:
        return False
    run = storage.get_daily_fetch_run(now.date().isoformat())
    return not run or run.get("status") != "success"

def _run_daily_fetch(date_str: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    storage.init_db()
    if not date_str:
        date_str = datetime.now().date().isoformat()
    if not force:
        run = storage.get_daily_fetch_run(date_str)
        if run and run.get("status") == "success":
            return {"skipped": True, "reason": "already_fetched", "date": date_str}
    if not _start_fetch_pipeline():
        return {"skipped": True, "reason": "fetch_in_progress", "date": date_str}
    try:
        papers = client.fetch_papers_by_date(date_str)
        result = _handle_fetched_papers(papers, date_str)
        storage.record_daily_fetch_run(
            date_str,
            status="success",
            fetched=int(result.get("fetched") or 0),
            new_count=int(result.get("new") or 0),
            forced=bool(force),
        )
        result["skipped"] = False
        return result
    except client.ArxivRateLimitError as e:
        retry_after = max(1, int(getattr(e, "retry_after_seconds", 60) or 60))
        storage.record_daily_fetch_run(
            date_str,
            status="error",
            reason=str(e),
            forced=bool(force),
        )
        _end_fetch_pipeline()
        return {
            "skipped": False,
            "error": str(e),
            "status_code": 429,
            "retry_after_seconds": retry_after,
            "date": date_str,
        }
    except Exception as e:
        storage.record_daily_fetch_run(
            date_str,
            status="error",
            reason=str(e),
            forced=bool(force),
        )
        _end_fetch_pipeline()
        return {"skipped": False, "error": str(e), "date": date_str}

def _daily_fetch_loop():
    is_leader = False
    while not _SCHEDULER_STOP_EVENT.is_set():
        try:
            storage.init_db()
            owns_lock = storage.try_acquire_scheduler_lock(
                DAILY_FETCH_LOCK_NAME,
                _SCHEDULER_OWNER_ID,
                ttl_seconds=DAILY_FETCH_TTL_SEC,
            )
            if not owns_lock:
                is_leader = False
                if _SCHEDULER_STOP_EVENT.wait(DAILY_FETCH_POLL_SEC):
                    break
                continue
            if not is_leader:
                print(f"Daily fetch leader: {_SCHEDULER_OWNER_ID}")
            is_leader = True

            now = datetime.now()
            if _daily_fetch_due(now):
                result = _run_daily_fetch(now.date().isoformat(), force=False)
                print(f"Daily fetch result: {result}")

            if _SCHEDULER_STOP_EVENT.wait(DAILY_FETCH_POLL_SEC):
                break
        except Exception as e:
            print(f"Daily fetch loop error: {e}")
            if _SCHEDULER_STOP_EVENT.wait(DAILY_FETCH_POLL_SEC):
                break

def _share_token_cleanup_loop():
    is_leader = False
    while not _SCHEDULER_STOP_EVENT.is_set():
        try:
            storage.init_db()
            owns_lock = storage.try_acquire_scheduler_lock(
                SHARE_TOKEN_CLEANUP_LOCK_NAME,
                _SCHEDULER_OWNER_ID,
                ttl_seconds=SHARE_TOKEN_CLEANUP_TTL_SEC,
            )
            if not owns_lock:
                is_leader = False
                if _SCHEDULER_STOP_EVENT.wait(SHARE_TOKEN_CLEANUP_POLL_SEC):
                    break
                continue
            if not is_leader:
                print(f"Share token cleanup leader: {_SCHEDULER_OWNER_ID}")
            is_leader = True

            removed = storage.purge_expired_share_tokens()
            if removed:
                print(f"Share token cleanup removed {removed} tokens.")

            if _SCHEDULER_STOP_EVENT.wait(SHARE_TOKEN_CLEANUP_POLL_SEC):
                break
        except Exception as e:
            print(f"Share token cleanup error: {e}")
            if _SCHEDULER_STOP_EVENT.wait(SHARE_TOKEN_CLEANUP_POLL_SEC):
                break

def _run_ranker_training(reason: str = "manual"):
    """Trains the ranker in a guarded section to avoid overlapping runs."""
    if not _RANKER_TRAIN_LOCK.acquire(blocking=False):
        print(f"DEBUG: Ranker training skipped ({reason}) because another run is in progress.")
        return
    try:
        storage.init_db()
        liked = storage.get_papers_by_status('liked')
        ranker.train_ranker(liked)
        print(f"DEBUG: Ranker training complete ({reason}) on {len(liked)} papers.")
    except Exception as e:
        print(f"Ranker training failed ({reason}): {e}")
    finally:
        _RANKER_TRAIN_LOCK.release()

def _schedule_ranker_training(reason: str = "manual"):
    threading.Thread(target=_run_ranker_training, args=(reason,), daemon=True).start()

def background_retrain():
    """Background task trigger to retrain logic on new data."""
    _schedule_ranker_training("interaction")

def _warm_models_async(reason: str = "startup"):
    if not config.WARMUP_MODELS:
        return
    def _task():
        try:
            print(f"DEBUG: Warmup embeddings ({reason})...")
            embeddings.get_model()
            embeddings.generate_embedding("warmup")
        except Exception as e:
            print(f"Embedding warmup skipped: {e}")
        try:
            print(f"DEBUG: Warmup AI model ({reason})...")
            ai_service.query_ollama("ping", "", timeout=5)
        except Exception as e:
            print(f"AI warmup skipped: {e}")
    threading.Thread(target=_task, daemon=True).start()

def _load_jobs_from_storage():
    try:
        storage.init_db()
        storage.reset_inflight_jobs()
        jobs = storage.list_job_records(limit=400)
    except Exception as e:
        print(f"Failed to load jobs from storage: {e}")
        return

    with _JOB_LOCK:
        _JOBS.clear()
        for job in jobs:
            _JOBS[job["id"]] = job

    queued = [j for j in jobs if j.get("status") == "queued"]
    queued.sort(key=lambda j: j.get("created_at") or "")
    for job in queued:
        _JOB_QUEUE.put(job["id"])

@app.on_event("startup")
def startup_event():
    storage.init_db()
    _SCHEDULER_STOP_EVENT.clear()
    _JOB_STOP_EVENT.clear()
    # Train ranker asynchronously so API startup stays fast.
    _schedule_ranker_training("startup")
    threading.Thread(target=storage.recompute_match_scores, args=(list(config.KEYWORDS),), daemon=True).start()
    threading.Thread(target=storage.backfill_fts, args=(2000,), daemon=True).start()
    _load_bundle_cache_from_storage()
    _load_jobs_from_storage()
    _warm_models_async("startup")
    threading.Thread(target=_saved_search_scheduler_loop, daemon=True).start()
    threading.Thread(target=_citation_refresh_loop, daemon=True).start()
    threading.Thread(target=_daily_fetch_loop, daemon=True).start()
    threading.Thread(target=_share_token_cleanup_loop, daemon=True).start()
    _start_job_workers()

@app.on_event("shutdown")
def shutdown_event():
    _SCHEDULER_STOP_EVENT.set()
    _JOB_STOP_EVENT.set()
    try:
        storage.release_scheduler_lock(SAVED_SEARCH_LOCK_NAME, _SCHEDULER_OWNER_ID)
        storage.release_scheduler_lock(CITATION_REFRESH_LOCK_NAME, _SCHEDULER_OWNER_ID)
        storage.release_scheduler_lock(DAILY_FETCH_LOCK_NAME, _SCHEDULER_OWNER_ID)
        storage.release_scheduler_lock(SHARE_TOKEN_CLEANUP_LOCK_NAME, _SCHEDULER_OWNER_ID)
    except Exception as e:
        print(f"Failed to release scheduler lock: {e}")

def background_index(papers: List[dict]):
    """Generates embeddings for new papers in background."""
    print(f"Indexing {len(papers)} papers for semantic search...")
    if not papers:
        return

    ids = []
    texts = []
    for p in papers:
        pid = p.get("id")
        if not pid:
            continue
        ids.append(pid)
        texts.append(f"{p.get('title', '')} {p.get('summary', '')}")

    if not ids:
        return

    try:
        vectors = embeddings.batch_generate_embeddings(texts)
        if getattr(vectors, "size", 0) > 0:
            pairs = [(paper_id, vectors[idx]) for idx, paper_id in enumerate(ids)]
            storage.save_embeddings(pairs)
            novelty_map = storage.compute_novelty_scores([pid for pid, _ in pairs], reference_status="liked")
            if novelty_map:
                storage.update_novelty_scores(novelty_map)
                _bump_api_cache_epochs("papers")
            print("Indexing complete.")
            return
    except Exception as e:
        print(f"Batch indexing failed, falling back to single mode: {e}")

    # Fallback path if batch encoding is unavailable.
    indexed_ids = []
    for pid, text in zip(ids, texts):
        vec = embeddings.generate_embedding(text)
        if getattr(vec, "size", 0) > 0:
            storage.save_embedding(pid, vec)
            indexed_ids.append(pid)
    if indexed_ids:
        novelty_map = storage.compute_novelty_scores(indexed_ids, reference_status="liked")
        if novelty_map:
            storage.update_novelty_scores(novelty_map)
            _bump_api_cache_epochs("papers")
    print("Indexing complete.")


def enrich_structures(papers: List[dict]):
    """Background task to cache structured extraction for fetched papers."""
    if not papers:
        return
    ids = [str(p.get("id")) for p in papers if p.get("id")]
    if not ids:
        return

    try:
        db_rows = storage.get_papers_by_ids(ids)
    except Exception as e:
        print(f"Structure enrichment load failed: {e}")
        return
    if not db_rows:
        return

    missing = [p for p in db_rows if not p.get("structure")]
    if not missing:
        return
    try:
        _ensure_structures_for_papers(missing, refresh=False)
        print(f"Structured extraction updated for {len(missing)} papers.")
    except Exception as e:
        print(f"Structure enrichment failed: {e}")

def enrich_citations(paper_ids: List[str]):
    """Background task to fetch citation counts."""
    print(f"Enriching {len(paper_ids)} papers with citation counts...")
    counts = citation_service.get_citations(paper_ids)
    if counts:
        storage.update_citations(counts)
        papers = storage.get_papers_by_ids(list(counts.keys()))
        generate_alerts_for_papers(papers)
        print(f"Updated citations for {len(counts)} papers.")

@app.post("/api/fetch")
def api_fetch(req: FetchRequest, background_tasks: BackgroundTasks):
    storage.init_db()
    start_ts = time.perf_counter()
    if not _start_fetch_pipeline():
        started_at = None
        with _FETCH_PIPELINE_LOCK:
            started_at = _FETCH_PIPELINE_STARTED_AT
        detail = "Fetch already running."
        if started_at:
            detail = f"Fetch already running (started at {started_at})."
        raise HTTPException(status_code=409, detail=detail)
    try:
        if req.date:
            papers = client.fetch_papers_by_date(req.date)
            batch_date = req.date
        else:
            # Ignore req.max_results, we fetch the whole day day
            papers, batch_date = client.fetch_latest_daily_batch()
        result = _handle_fetched_papers(papers, batch_date)
        if req.date:
            storage.record_daily_fetch_run(
                batch_date,
                status="success",
                fetched=int(result.get("fetched") or 0),
                new_count=int(result.get("new") or 0),
                forced=True,
            )
        _log_request_timing(
            "request.fetch",
            start_ts,
            status="ok",
            fetched=int(result.get("fetched") or 0),
            new_count=int(result.get("new") or 0),
            date=batch_date,
        )
        return result
    except client.ArxivRateLimitError as e:
        _end_fetch_pipeline()
        retry_after = max(1, int(getattr(e, "retry_after_seconds", 60) or 60))
        _log_request_timing(
            "request.fetch",
            start_ts,
            status="error",
            error=str(e),
            http_status=429,
            retry_after=retry_after,
        )
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"detail": str(e), "retry_after_seconds": retry_after},
        )
    except Exception as e:
        _end_fetch_pipeline()
        _log_request_timing("request.fetch", start_ts, status="error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/fetch/daily")
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
                raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
        else:
            now = datetime.now()
            if now.weekday() >= 5:
                return {"skipped": True, "reason": "weekend"}

    result = _run_daily_fetch(date_str=date, force=force)
    if "error" in result:
        status_code = int(result.get("status_code") or 500)
        retry_after = int(result.get("retry_after_seconds") or 0)
        _log_request_timing(
            "request.fetch_daily",
            start_ts,
            status="error",
            error=str(result.get("error")),
            date=result.get("date"),
            forced=bool(force),
            http_status=status_code,
            retry_after=retry_after or None,
        )
        if status_code == 429 and retry_after > 0:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={"detail": result["error"], "retry_after_seconds": retry_after},
            )
        raise HTTPException(status_code=status_code, detail=result["error"])
    _log_request_timing(
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

def _sanitize_day_run_options(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = DayRunRequest().dict()
    candidate = options if isinstance(options, dict) else {}
    merged = {**base, **candidate}
    try:
        return DayRunRequest(**merged).dict()
    except Exception:
        return DayRunRequest().dict()

def _day_run_idempotency_key(payload: DayRunRequest) -> str:
    options = _sanitize_day_run_options(payload.dict() if payload else {})
    raw = json.dumps(options, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()

def _prune_day_run_idempotency_cache_locked(now_ts: Optional[float] = None) -> None:
    now_value = float(now_ts or time.time())
    stale: List[str] = []
    for key, entry in _DAY_RUN_IDEMPOTENCY_CACHE.items():
        age = now_value - float(entry.get("stored_at") or 0.0)
        if age > float(_DAY_RUN_IDEMPOTENCY_TTL_SECONDS):
            stale.append(key)
    for key in stale:
        _DAY_RUN_IDEMPOTENCY_CACHE.pop(key, None)

def _get_day_run_cached_response(signature: str) -> Optional[Dict[str, Any]]:
    if not signature:
        return None
    with _DAY_RUN_IDEMPOTENCY_LOCK:
        _prune_day_run_idempotency_cache_locked()
        entry = _DAY_RUN_IDEMPOTENCY_CACHE.get(signature)
        if not isinstance(entry, dict):
            return None
        response = copy.deepcopy(entry.get("response") or {})
    if isinstance(response, dict):
        response["idempotency_key"] = signature
        response["idempotent_replay"] = True
    return response if isinstance(response, dict) else None

def _set_day_run_cached_response(signature: str, response: Dict[str, Any]) -> None:
    if not signature or not isinstance(response, dict):
        return
    with _DAY_RUN_IDEMPOTENCY_LOCK:
        _prune_day_run_idempotency_cache_locked()
        _DAY_RUN_IDEMPOTENCY_CACHE[signature] = {
            "stored_at": time.time(),
            "response": copy.deepcopy(response),
        }

def _run_day_with_idempotency(payload: DayRunRequest, source: str = "api") -> Dict[str, Any]:
    global _DAY_RUN_ACTIVE_SIGNATURE
    signature = _day_run_idempotency_key(payload)
    cached = _get_day_run_cached_response(signature)
    if cached:
        return cached

    with _DAY_RUN_IDEMPOTENCY_LOCK:
        active_signature = _DAY_RUN_ACTIVE_SIGNATURE
    if not _DAY_RUN_EXEC_LOCK.acquire(blocking=False):
        if active_signature and active_signature == signature:
            deadline = time.time() + 8.0
            while time.time() < deadline:
                replay = _get_day_run_cached_response(signature)
                if replay:
                    return replay
                time.sleep(0.15)
            replay = _get_day_run_cached_response(signature)
            if replay:
                return replay
        raise HTTPException(status_code=409, detail="A day run is already in progress. Please retry shortly.")

    with _DAY_RUN_IDEMPOTENCY_LOCK:
        _DAY_RUN_ACTIVE_SIGNATURE = signature
    try:
        response = _execute_day_run(payload, source=source)
        if isinstance(response, dict):
            response["idempotency_key"] = signature
            response["idempotent_replay"] = False
        _set_day_run_cached_response(signature, response)
        return response
    finally:
        with _DAY_RUN_IDEMPOTENCY_LOCK:
            if _DAY_RUN_ACTIVE_SIGNATURE == signature:
                _DAY_RUN_ACTIVE_SIGNATURE = None
        _DAY_RUN_EXEC_LOCK.release()

def _execute_day_run(payload: DayRunRequest, source: str = "api") -> Dict[str, Any]:
    date_val = str(payload.date or "").strip() or None
    if date_val:
        try:
            datetime.strptime(date_val, "%Y-%m-%d")
        except Exception:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    weekend_policy = str(payload.weekend_policy or "skip").strip().lower()
    if weekend_policy not in {"skip", "run"}:
        weekend_policy = "skip"

    run_fetch = bool(payload.run_fetch)
    run_rules = bool(payload.run_rules)
    run_reading_plan = bool(payload.run_reading_plan) and bool(payload.refresh_reading_plan)
    run_inbox_refresh = bool(payload.run_inbox_refresh)
    run_rules_scope = _normalize_rule_scope(payload.run_inbox_rules_scope)
    version_days = max(1, min(int(payload.version_days or 30), 180))
    version_scope = str(payload.version_scope or "watchlist").strip().lower() or "watchlist"
    now = datetime.now()
    requested_at = now.isoformat()
    effective_date = date_val or now.date().isoformat()

    errors: List[str] = []
    steps: Dict[str, Any] = {}

    fetch_result: Dict[str, Any] = {"skipped": True, "reason": "fetch_disabled", "date": effective_date}
    if run_fetch:
        try:
            target_dt = datetime.strptime(effective_date, "%Y-%m-%d")
            if not bool(payload.force) and weekend_policy == "skip" and target_dt.weekday() >= 5:
                fetch_result = {"skipped": True, "reason": "weekend", "date": effective_date}
            else:
                fetch_result = _run_daily_fetch(date_str=effective_date, force=bool(payload.force))
        except Exception as e:
            fetch_result = {"skipped": False, "error": str(e), "date": effective_date}
        if "error" in fetch_result:
            errors.append(f"fetch: {fetch_result.get('error')}")
    steps["fetch"] = fetch_result

    rules_result: Dict[str, Any] = {
        "scope": run_rules_scope,
        "dry_run": False,
        "matched": 0,
        "applied": 0,
        "dismissed": 0,
        "labeled": 0,
        "audit_count": 0,
        "skipped": True,
        "reason": "rules_disabled",
    }
    if run_rules:
        try:
            rules_result = _run_inbox_rules(scope=run_rules_scope, dry_run=False, limit=250)
            rules_result["skipped"] = False
        except Exception as e:
            errors.append(f"rules: {e}")
            rules_result = {
                "scope": run_rules_scope,
                "dry_run": False,
                "matched": 0,
                "applied": 0,
                "dismissed": 0,
                "labeled": 0,
                "audit_count": 0,
                "skipped": False,
                "error": str(e),
            }
    steps["rules"] = rules_result

    if run_reading_plan:
        try:
            reading_plan = _refresh_today_reading_plan_cache(source=f"day_run:{source}")
        except Exception as e:
            errors.append(f"reading_plan: {e}")
            reading_plan = _latest_reading_plan_payload_for_date()
    else:
        reading_plan = _latest_reading_plan_payload_for_date()
        if not isinstance(reading_plan, dict):
            reading_plan = {}
        reading_plan["_skipped"] = True
    steps["reading_plan"] = {
        "date": (reading_plan or {}).get("date"),
        "count": int((reading_plan or {}).get("count") or 0),
        "planned_minutes": int((reading_plan or {}).get("planned_minutes") or 0),
        "cached": bool((reading_plan or {}).get("cached")),
        "skipped": bool((reading_plan or {}).get("_skipped")),
    }

    if run_inbox_refresh:
        try:
            unified = _build_unified_inbox_payload(
                limit=60,
                version_scope=version_scope,
                version_days=version_days,
                include_items=False,
            )
        except Exception as e:
            errors.append(f"inbox: {e}")
            unified = {"total": 0, "counts": {"alerts": 0, "version_updates": 0, "follow_ups": 0, "digests": 0}}
    else:
        unified = {"total": 0, "counts": {"alerts": 0, "version_updates": 0, "follow_ups": 0, "digests": 0}, "_skipped": True}
    steps["inbox"] = {"total": int(unified.get("total") or 0), "counts": unified.get("counts") or {}, "skipped": bool(unified.get("_skipped"))}

    progress = _reading_plan_progress_summary(days=14)
    success_steps = int(sum(1 for key in ["fetch", "rules", "reading_plan", "inbox"] if not bool(steps.get(key, {}).get("error"))))
    if errors and success_steps > 0:
        status = "partial"
    elif errors:
        status = "error"
    else:
        status = "ok"

    summary = (
        f"Fetch {'skipped' if fetch_result.get('skipped') else 'completed'}; "
        f"rules applied {int(rules_result.get('applied') or 0)}; "
        f"{int((reading_plan or {}).get('count') or 0)} reading-plan items; "
        f"inbox total {int(unified.get('total') or 0)}."
    )

    response = {
        "date": fetch_result.get("date") or effective_date,
        "status": status,
        "errors": errors,
        "fetch": fetch_result,
        "rules": rules_result,
        "reading_plan": steps["reading_plan"],
        "progress": {
            "streak_days": int(progress.get("streak_days") or 0),
            "completion_rate": float(progress.get("completion_rate") or 0.0),
            "today": progress.get("today") or {},
        },
        "inbox": steps["inbox"],
        "steps": steps,
        "options": {
            "date": effective_date,
            "force": bool(payload.force),
            "weekend_policy": weekend_policy,
            "run_fetch": run_fetch,
            "run_rules": run_rules,
            "run_reading_plan": run_reading_plan,
            "run_inbox_refresh": run_inbox_refresh,
            "run_inbox_rules_scope": run_rules_scope,
            "version_scope": version_scope,
            "version_days": version_days,
        },
        "summary": summary,
        "requested_at": requested_at,
    }
    run_id = 0
    try:
        run_id = storage.record_day_run_history(
            run_date=response.get("date") or effective_date,
            requested_at=requested_at,
            status=status,
            options=response.get("options") or {},
            summary=summary,
            payload=response,
        )
    except Exception:
        run_id = 0
    response["run_id"] = int(run_id or 0)
    return response

@app.post("/api/day/run")
def run_day(req: Optional[DayRunRequest] = None):
    storage.init_db()
    start_ts = time.perf_counter()
    payload = req or DayRunRequest()
    response = _run_day_with_idempotency(payload, source="api")
    fetch_result = response.get("fetch") or {}
    _log_request_timing(
        "request.day_run",
        start_ts,
        status=response.get("status") or ("skipped" if fetch_result.get("skipped") else "ok"),
        fetched=int(fetch_result.get("fetched") or 0),
        new_count=int(fetch_result.get("new") or 0),
        date=response.get("date"),
        inbox_total=int(response.get("inbox", {}).get("total") or 0),
        run_id=int(response.get("run_id") or 0),
    )
    return response

@app.get("/api/day/runs")
def list_day_runs(limit: int = 30):
    storage.init_db()
    items = storage.list_day_run_history(limit=limit)
    return {"count": len(items), "items": items}

@app.get("/api/day/presets")
def list_day_run_presets(limit: int = 50):
    storage.init_db()
    items = storage.list_day_run_presets(limit=limit)
    return {"count": len(items), "items": items}

@app.post("/api/day/presets")
def create_day_run_preset(req: DayRunPresetRequest):
    storage.init_db()
    name = str(req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    options = _sanitize_day_run_options(req.options or {})
    created = storage.create_day_run_preset(
        name=name,
        description=(str(req.description or "").strip() or None),
        options=options,
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create preset")
    return created

@app.put("/api/day/presets/{preset_id}")
def update_day_run_preset(preset_id: int, req: DayRunPresetUpdateRequest):
    storage.init_db()
    updates: Dict[str, Any] = {}
    if req.name is not None:
        updates["name"] = str(req.name or "").strip() or "Preset"
    if req.description is not None:
        updates["description"] = str(req.description or "").strip()
    if req.options is not None:
        updates["options"] = _sanitize_day_run_options(req.options)
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    updated = storage.update_day_run_preset(int(preset_id), updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Preset not found")
    return updated

@app.delete("/api/day/presets/{preset_id}")
def delete_day_run_preset(preset_id: int):
    storage.init_db()
    ok = storage.delete_day_run_preset(int(preset_id))
    return {"success": bool(ok)}

@app.post("/api/day/presets/{preset_id}/run")
def run_day_preset(preset_id: int):
    storage.init_db()
    preset = storage.get_day_run_preset(int(preset_id))
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    options = preset.get("options") or {}
    payload = DayRunRequest(**_sanitize_day_run_options(options))
    response = _run_day_with_idempotency(payload, source=f"preset:{int(preset_id)}")
    storage.mark_day_run_preset_used(int(preset_id))
    response["preset_id"] = int(preset_id)
    return response

@app.post("/api/day/run/{run_id}/retry")
def retry_day_run(run_id: int):
    storage.init_db()
    record = storage.get_day_run_history(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run history not found")
    options = record.get("options") or {}
    if not isinstance(options, dict):
        options = {}
    payload = DayRunRequest(**_sanitize_day_run_options(options))
    response = _run_day_with_idempotency(payload, source=f"retry:{int(run_id)}")
    response["retry_of"] = int(run_id)
    return response

@app.get("/api/daily-fetch/runs")
def list_daily_fetch_runs(limit: int = 30, date_from: Optional[str] = None, date_to: Optional[str] = None):
    storage.init_db()
    return storage.list_daily_fetch_runs(limit=limit, date_from=date_from, date_to=date_to)

@app.get("/api/papers")
def get_papers(
    status: str = 'new',
    limit: int = 100,
    offset: int = 0,
    date: Optional[str] = None,
    sort: Optional[str] = None,
    w_relevance: Optional[float] = None,
    w_novelty: Optional[float] = None,
    w_citations: Optional[float] = None,
    include_meta: bool = False,
    include_novelty: bool = True,
    request: Request = None,
):
    storage.init_db()
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    cache_key = f"papers:{status}:{limit}:{offset}:{date or ''}:{sort or ''}:{w_relevance}:{w_novelty}:{w_citations}:{int(include_meta)}:{int(include_novelty)}"
    etag = _etag_for_cache_key(cache_key, "papers")
    if request is not None:
        inm = request.headers.get("if-none-match")
        if _etag_matches(inm, etag) and _client_cache_warm(request):
            return Response(status_code=304, headers={"ETag": etag})
    cached = _api_cache_get(cache_key, ttl_seconds=15, epoch_key="papers")
    if cached is not None:
        return JSONResponse(content=cached, headers={"ETag": etag})

    sort_mode = (sort or '').lower()
    if sort_mode == 'ai':
        sort_mode = 'smart'
    weights = _parse_rank_weights(w_relevance, w_novelty, w_citations)
    use_profile = (sort_mode == 'profile') or (sort_mode in {'smart', 'profile'} and any(v is not None for v in [w_relevance, w_novelty, w_citations]))
    use_smart = (sort_mode == 'smart' and not use_profile)
    with storage.connection_scope():
        raw_bookmarked_ids = set(storage.get_bookmarked_ids())
    bookmarked_ids = set(raw_bookmarked_ids)
    for bid in raw_bookmarked_ids:
        sid = str(bid or "")
        if sid and not sid.startswith("http"):
            bookmarked_ids.add(normalize_paper_id(sid))

    # Fast SQL-paged path for recency-sorted feeds.
    # This avoids loading and version-deduping large datasets on every offset.
    if include_meta and not use_smart and not use_profile and sort_mode in {'', 'date'} and status in {'new', 'dismissed', 'read', 'bookmarked'}:
        with storage.connection_scope():
            published_date_filter = None
            if date and status == 'new':
                d = datetime.strptime(date, "%Y-%m-%d").date()
                published_date_filter = (d - timedelta(days=1)).isoformat()
            if status == "bookmarked":
                result, total = storage.get_bookmarked_papers_page(
                    limit=limit,
                    offset=offset,
                    published_date=published_date_filter,
                    dedupe_latest=False,
                )
            else:
                result, total = storage.get_papers_page_by_status(
                    status=status,
                    limit=limit,
                    offset=offset,
                    published_date=published_date_filter,
                    dedupe_latest=(status == "new"),
                    include_liked_in_new=(status == "new"),
                )

            for p in result:
                pid = p.get('id')
                p['bookmarked'] = (status == "bookmarked") or bool(pid and pid in bookmarked_ids)
                p['score'] = _paper_match_score(p)
            result = _attach_version_metadata(result, dedupe_latest=False if status == "bookmarked" else (status == "new"))
            if include_novelty and result:
                missing_ids = [p["id"] for p in result if p.get("novelty_score") is None]
                novelty_map = storage.compute_novelty_scores(missing_ids, reference_status="liked") if missing_ids else {}
                if novelty_map:
                    _enqueue_novelty_backfill(novelty_map)
                for p in result:
                    if p.get("novelty_score") is None:
                        p["novelty_score"] = novelty_map.get(p["id"])

            _attach_version_notes(result)
            _attach_version_change_fields(result)
            _attach_match_reasons(result)
            _attach_reading_meta(result)
            _attach_labels(result)
            _attach_pins(result)
            payload = {
                "items": result,
                "total": total,
                "offset": offset,
                "limit": limit,
                "has_more": (offset + len(result)) < total,
            }
        _api_cache_set(cache_key, payload, epoch_key="papers")
        return JSONResponse(content=payload, headers={"ETag": etag})

    with storage.connection_scope():
        # Check for bookmark queries
        if status == 'bookmarked':
            papers = storage.get_papers_by_ids(list(raw_bookmarked_ids))
        else:
            papers = storage.get_papers_by_status(
                status,
                include_liked_in_new=(status == "new"),
            )

            # Only filter 'new' papers by date.
            # Favorites and Dismissed should show all history regardless of the date picker.
            if date and status == 'new':
                # Shift date back by 1 day for filtering
                d = datetime.strptime(date, "%Y-%m-%d").date()
                query_d = d - timedelta(days=1)
                filter_str = query_d.isoformat()

                papers = [p for p in papers if p['published'].startswith(filter_str)]

        # Inject bookmark status into every paper
        for p in papers:
            p['bookmarked'] = (p['id'] in bookmarked_ids)

        dedupe_versions = (status == 'new')
        papers = _attach_version_metadata(papers, dedupe_latest=dedupe_versions)
        pin_map = {}
        if status == 'liked':
            pin_map = _attach_pins(papers)

        rank_cache_key = None
        rank_cache_ids: Optional[List[str]] = None
        if include_meta and (use_profile or use_smart):
            rank_cache_key = (
                f"papers_rank:{status}:{date or ''}:{sort_mode}:"
                f"{weights.get('relevance', 0.0):.4f}:{weights.get('novelty', 0.0):.4f}:{weights.get('citations', 0.0):.4f}"
            )
            rank_cache_ids = _get_paged_rank_cache(rank_cache_key, "papers")

        computed_novelty = False
        if status == 'liked' and sort_mode in {'date', 'matches', 'novelty'}:
            ranked = list(papers)
            if sort_mode == 'matches':
                for p in ranked:
                    p["match_score"] = _paper_match_score(p)
                ranked.sort(key=lambda x: (x.get("match_score", 0), x.get("published", "")), reverse=True)
            elif sort_mode == 'novelty':
                missing_ids = [p["id"] for p in ranked if p.get("novelty_score") is None]
                novelty_map = storage.compute_novelty_scores(missing_ids, reference_status="liked") if missing_ids else {}
                if novelty_map:
                    _enqueue_novelty_backfill(novelty_map)
                for p in ranked:
                    if p.get("novelty_score") is None:
                        p["novelty_score"] = novelty_map.get(p["id"])
                ranked.sort(key=lambda x: (x.get("novelty_score") or 0), reverse=True)
                computed_novelty = True
            else:
                ranked.sort(key=lambda x: x.get("published", ""), reverse=True)
            if pin_map:
                ranked = _apply_pin_order(ranked, pin_map)
            total = len(ranked)
            result = ranked[offset: offset + limit]
        elif use_profile:
            used_cache = False
            if rank_cache_ids:
                paper_map = {p.get("id"): p for p in papers if p.get("id")}
                ranked = [paper_map[pid] for pid in rank_cache_ids if pid in paper_map]
                used_cache = True
            else:
                ranked = _apply_profile_sort(papers, weights)
                if rank_cache_key:
                    _set_paged_rank_cache(rank_cache_key, [p.get("id") for p in ranked if p.get("id")], "papers")
            if pin_map and status == 'liked' and not used_cache:
                ranked = _apply_pin_order(ranked, pin_map)
            total = len(ranked)
            result = ranked[offset: offset + limit]
            computed_novelty = True
        else:
            # Fast path for paged feeds: keep ordering by recency and avoid re-ranking the full set on each page.
            if include_meta and not use_smart:
                ranked = sorted(papers, key=lambda x: x.get("published", ""), reverse=True)
                if pin_map and status == 'liked':
                    ranked = _apply_pin_order(ranked, pin_map)
                total = len(ranked)
                result = ranked[offset: offset + limit]
                for p in result:
                    p["score"] = _paper_match_score(p)
            else:
                used_cache = False
                if use_smart and rank_cache_ids:
                    paper_map = {p.get("id"): p for p in papers if p.get("id")}
                    ranked = [paper_map[pid] for pid in rank_cache_ids if pid in paper_map]
                    used_cache = True
                else:
                    ranked = ranker.rank_papers(papers, use_smart_rank=use_smart)
                    if use_smart and rank_cache_key:
                        _set_paged_rank_cache(rank_cache_key, [p.get("id") for p in ranked if p.get("id")], "papers")
                if pin_map and status == 'liked' and not used_cache:
                    ranked = _apply_pin_order(ranked, pin_map)
                total = len(ranked)
                result = ranked[offset: offset + limit]

        if include_novelty and result and not computed_novelty:
            missing_ids = [p["id"] for p in result if p.get("novelty_score") is None]
            novelty_map = storage.compute_novelty_scores(missing_ids, reference_status="liked") if missing_ids else {}
            if novelty_map:
                _enqueue_novelty_backfill(novelty_map)
            for p in result:
                if p.get("novelty_score") is None:
                    p["novelty_score"] = novelty_map.get(p["id"])

        _attach_version_notes(result)
        _attach_version_change_fields(result)
        _attach_match_reasons(result)
        _attach_reading_meta(result)
        _attach_labels(result)
        _attach_pins(result)

    if include_meta:
        payload = {
            "items": result,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + len(result)) < total,
        }
    else:
        payload = result

    _api_cache_set(cache_key, payload, epoch_key="papers")
    return JSONResponse(content=payload, headers={"ETag": etag})

@app.get("/api/search")
def api_search(
    q: str,
    mode: str = 'keyword',
    limit: int = 50,
    offset: int = 0,
    include_meta: bool = False,
    request: Request = None,
):
    storage.init_db()
    start_ts = time.perf_counter()
    if not q:
        _log_request_timing("request.search", start_ts, status="empty_query", mode=mode, query_len=0, results=0)
        return []

    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    cache_key = f"search:{mode}:{q.strip().lower()}:{limit}:{offset}:{int(include_meta)}"
    etag = _etag_for_cache_key(cache_key, "papers")
    if request is not None:
        inm = request.headers.get("if-none-match")
        if _etag_matches(inm, etag) and _client_cache_warm(request):
            _log_request_timing(
                "request.search",
                start_ts,
                status="not_modified",
                mode=mode,
                query_len=len(q or ""),
                results=0,
            )
            return Response(status_code=304, headers={"ETag": etag})

    cached = _api_cache_get(cache_key, ttl_seconds=45, epoch_key="papers")
    if cached is not None:
        if include_meta and isinstance(cached, dict):
            cached["cached"] = True
        _log_request_timing(
            "request.search",
            start_ts,
            status="cached",
            mode=mode,
            query_len=len(q or ""),
            results=len(cached.get("items", [])) if isinstance(cached, dict) else len(cached),
        )
        return JSONResponse(content=cached, headers={"ETag": etag})

    matches: List[Dict[str, Any]] = []
    total = 0

    if mode == 'semantic':
        vec = embeddings.generate_embedding(q)
        if vec.size > 0:
            fetch_limit = min(200, offset + limit)
            results = storage.search_semantic(vec, limit=fetch_limit)
            matches = [{"id": r['id'], "snippet": f"Similarity: {r['score']:.2f}"} for r in results]
            total = len(matches)
            if offset:
                matches = matches[offset: offset + limit]
    else:
        matches, total = storage.search_full_text_paged(q, limit=limit, offset=offset)

    if not matches:
        payload = {"items": [], "total": total, "offset": offset, "limit": limit, "has_more": False} if include_meta else []
        _api_cache_set(cache_key, payload, epoch_key="papers")
        _log_request_timing(
            "request.search",
            start_ts,
            status="ok",
            mode=mode,
            query_len=len(q or ""),
            results=0,
        )
        return JSONResponse(content=payload, headers={"ETag": etag})

    ids = [m['id'] for m in matches]
    papers = storage.get_papers_by_ids(ids)
    snippet_map = {m['id']: m['snippet'] for m in matches}
    paper_map = {p['id']: p for p in papers}

    ordered_papers = []
    for pid in ids:
        if pid in paper_map:
            p = paper_map[pid]
            p['search_snippet'] = snippet_map.get(pid)
            ordered_papers.append(p)

    ordered_papers = _attach_version_metadata(ordered_papers, dedupe_latest=False)
    _attach_version_notes(ordered_papers)
    _attach_version_change_fields(ordered_papers)
    _attach_match_reasons(ordered_papers)
    _attach_reading_meta(ordered_papers)
    _attach_labels(ordered_papers)
    _attach_pins(ordered_papers)

    has_more = (offset + len(ordered_papers)) < total if total else len(ordered_papers) == limit
    payload = {
        "items": ordered_papers,
        "total": total or len(ordered_papers),
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
    } if include_meta else ordered_papers
    if include_meta and isinstance(payload, dict):
        payload["cached"] = False

    _api_cache_set(cache_key, payload, epoch_key="papers")
    _log_request_timing(
        "request.search",
        start_ts,
        status="ok",
        mode=mode,
        query_len=len(q or ""),
        results=len(ordered_papers),
    )
    return JSONResponse(content=payload, headers={"ETag": etag})

@app.get("/api/search/global")
def api_search_global(q: str):
    """Searches global ArXiv and saves results temporarily to DB."""
    if not q:
        return []
        
    print(f"DEBUG: Global Search for '{q}'")
    papers = client.search_archive(q, max_results=20)
    
    # Save these papers to DB so they have IDs, can be bookmarked/rated
    # Note: save_papers updates if exists, inserts if new.
    # It sets status='new' by default if new.
    # We might not want to flood 'new' feed?
    # Actually client.fetch_latest_daily_batch does the same.
    # But usually 'new' feed is date sorted. These old papers will be buried or appear interspersed?
    # get_papers sort by date defaults so they might appear if they are new?
    # No, get_papers filters by date if 'new' status.
    # If we fetch an old paper (2017), it will be saved with status 'new'.
    # But get_papers(status='new') won't show it unless date picker is set to 2017 or cleared?
    # Let's just save them.
    storage.save_papers(papers)
    
    # We return them directly to front-end
    # But we should enrich them/check if they are already bookmarked/liked in DB?
    # get_papers_by_ids handles that?
    # Let's re-fetch from DB to ensure consistency (and getting standard fields)
    ids = [p['id'] for p in papers]
    
    # Re-fetch to get 'bookmarked', 'score', etc properties if they existed
    db_papers = storage.get_papers_by_ids(ids)
    db_papers = _attach_version_metadata(db_papers, dedupe_latest=False)
    _attach_version_notes(db_papers)
    _attach_version_change_fields(db_papers)
    _attach_match_reasons(db_papers)
    _attach_reading_meta(db_papers)
    _attach_labels(db_papers)
    _attach_pins(db_papers)
    
    # Inject search snippet equivalent (Abstract)
    for p in db_papers:
        # Highlight matches in title/summary?
        # For now just return as is.
        pass
        
    return db_papers

@app.post("/api/fts/rebuild")
def rebuild_fts():
    """Rebuilds the FTS index for the full library in the background."""
    storage.init_db()
    def _run():
        start_ts = time.perf_counter()
        try:
            count = storage.rebuild_fts(batch_size=1000)
            _log_request_timing("fts.rebuild", start_ts, status="ok", indexed=count)
        except Exception as e:
            _log_request_timing("fts.rebuild", start_ts, status="error", error=str(e))
    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}

@app.get("/api/search-agents")
def list_saved_search_agents():
    storage.init_db()
    return storage.list_saved_search_agents()

@app.post("/api/search-agents")
def create_saved_search_agent(req: SavedSearchRequest):
    storage.init_db()
    cadence = (req.cadence or "daily").lower()
    if cadence not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="Cadence must be 'daily' or 'weekly'.")
    mode = (req.mode or "global").strip().lower()
    if mode not in {"global", "semantic", "local"}:
        raise HTTPException(status_code=400, detail="mode must be one of: global, semantic, local")
    name = (req.name or "").strip()
    query = (req.query or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    if mode != "semantic" and not query:
        raise HTTPException(status_code=400, detail="query is required for local/global modes.")
    source_paper_id = None
    if req.source_paper_id:
        paper = _resolve_paper_by_id(req.source_paper_id)
        if not paper and mode == "semantic":
            raise HTTPException(status_code=404, detail="source_paper_id not found")
        if paper:
            source_paper_id = paper.get("id")
    agent_id = storage.create_saved_search_agent(
        name=name,
        query=query,
        cadence=cadence,
        max_results=max(1, int(req.max_results)),
        mode=mode,
        source_paper_id=source_paper_id,
    )
    return {"id": agent_id}

@app.delete("/api/search-agents/{agent_id}")
def delete_saved_search_agent(agent_id: int):
    storage.init_db()
    storage.delete_saved_search_agent(agent_id)
    return {"success": True}

@app.post("/api/search-agents/{agent_id}/run")
def run_saved_search_agent(agent_id: int):
    storage.init_db()
    agent = storage.get_saved_search_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Saved search agent not found.")
    return _run_saved_search_agent(agent, trigger="manual")

@app.get("/api/system/scheduler-leader")
def get_scheduler_leader():
    """
    Debug endpoint: returns current scheduler leader lock state.
    Useful when running multiple API workers/processes.
    """
    storage.init_db()
    return _get_scheduler_leader_payload()

@app.get("/api/system/scheduler-ops")
def get_scheduler_ops():
    """Ops dashboard payload: leader health + due agents + queue stats."""
    storage.init_db()
    leader = _get_scheduler_leader_payload()
    return {
        "leader": leader,
        "agents": _build_scheduler_agent_ops(),
        "jobs": _build_job_queue_ops(),
    }

@app.get("/api/digest/runs")
def list_digest_runs(limit: int = 20, cadence: Optional[str] = None):
    storage.init_db()
    cad = (cadence or "").strip().lower() or None
    if cad and cad not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="cadence must be daily or weekly")
    return storage.list_digest_runs(limit=limit, cadence=cad)

@app.get("/api/digest/runs/{digest_id}")
def get_digest_run(digest_id: int):
    storage.init_db()
    run = storage.get_digest_run(digest_id)
    if not run:
        raise HTTPException(status_code=404, detail="Digest run not found.")
    return run

@app.get("/api/digest/latest")
def get_latest_digest(cadence: Optional[str] = None):
    storage.init_db()
    cad = (cadence or "").strip().lower() or None
    if cad and cad not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="cadence must be daily or weekly")
    run = storage.get_latest_digest(cadence=cad)
    if not run:
        return {"digest": None}
    return {"digest": run}

@app.get("/api/digest/unread-count")
def get_digest_unread_count():
    storage.init_db()
    return {"unread": storage.count_unread_digests()}

@app.post("/api/digest/{digest_id}/read")
def mark_digest_read(digest_id: int):
    storage.init_db()
    ok = storage.mark_digest_read(digest_id)
    return {"success": ok}

@app.post("/api/digest/{digest_id}/share")
def share_digest(digest_id: int):
    storage.init_db()
    run = storage.get_digest_run(digest_id)
    if not run:
        raise HTTPException(status_code=404, detail="Digest run not found.")
    token = storage.create_share_token("digest", str(digest_id), ttl_days=SHARE_TOKEN_TTL_DAYS)
    return {"token": token}

@app.post("/api/share/selection")
def share_selection(req: ShareSelectionRequest):
    storage.init_db()
    ids = normalize_paper_ids(req.paper_ids or [])
    if not ids:
        raise HTTPException(status_code=400, detail="No papers selected.")
    papers = storage.get_papers_by_ids(ids)
    if not papers:
        raise HTTPException(status_code=404, detail="Papers not found.")
    token = storage.create_share_token("selection", json.dumps(ids), ttl_days=SHARE_TOKEN_TTL_DAYS)
    return {"token": token, "count": len(ids)}

@app.post("/api/share/view")
def share_view(req: ViewShareRequest):
    storage.init_db()
    status = (req.status or "new").lower()
    if status not in {"new", "liked", "dismissed", "bookmarked"}:
        raise HTTPException(status_code=400, detail="Unsupported status for view share.")
    limit = max(1, min(int(req.limit or 80), 200))

    sort_mode = "smart" if req.smart_sort else ""
    if status == "liked" and req.favorites_sort:
        sort_mode = req.favorites_sort
    if sort_mode == "ai":
        sort_mode = "smart"

    weights = _parse_rank_weights(
        (req.rank_profile or {}).get("relevance"),
        (req.rank_profile or {}).get("novelty"),
        (req.rank_profile or {}).get("citations"),
    )
    use_profile = bool(req.smart_sort) or (status == "liked" and sort_mode == "smart")

    published_date_filter = None
    if req.date_filter and status == "new":
        try:
            d = datetime.strptime(req.date_filter, "%Y-%m-%d").date()
            published_date_filter = (d - timedelta(days=1)).isoformat()
        except Exception:
            published_date_filter = None

    # Local query filter
    query = (req.search_query or "").strip().lower()

    def _load_share_candidates(max_rows: int) -> List[Dict[str, Any]]:
        cap = max(1, min(int(max_rows or 0), 5000))
        rows: List[Dict[str, Any]] = []
        page_offset = 0
        while len(rows) < cap:
            page_limit = min(400, cap - len(rows))
            if page_limit <= 0:
                break
            if status == "bookmarked":
                page_rows, _ = storage.get_bookmarked_papers_page(
                    limit=page_limit,
                    offset=page_offset,
                    published_date=published_date_filter,
                    dedupe_latest=False,
                    query_text=query or None,
                    include_total=False,
                )
            else:
                page_rows, _ = storage.get_papers_page_by_status(
                    status=status,
                    limit=page_limit,
                    offset=page_offset,
                    published_date=published_date_filter,
                    dedupe_latest=(status == "new"),
                    query_text=query or None,
                    include_total=False,
                )
            if not page_rows:
                break
            rows.extend(page_rows)
            page_offset += len(page_rows)
            if len(page_rows) < page_limit:
                break
        return rows

    with storage.connection_scope():
        if status == "liked" and not query:
            papers = storage.get_papers_by_status("liked")
        else:
            if not query and not use_profile and sort_mode in {"", "date"}:
                scan_cap = limit
            else:
                scan_cap = max(600, min(5000, limit * 12))
                if query:
                    scan_cap = max(scan_cap, min(5000, limit * 20))
            papers = _load_share_candidates(scan_cap)

        pin_map = _attach_pins(papers) if status == "liked" else {}

        if status == "liked" and sort_mode in {"date", "matches", "novelty"}:
            ranked = list(papers)
            if sort_mode == "matches":
                for p in ranked:
                    p["match_score"] = _paper_match_score(p)
                ranked.sort(key=lambda x: (x.get("match_score", 0), x.get("published", "")), reverse=True)
            elif sort_mode == "novelty":
                missing_ids = [p["id"] for p in ranked if p.get("novelty_score") is None]
                novelty_map = storage.compute_novelty_scores(missing_ids, reference_status="liked") if missing_ids else {}
                if novelty_map:
                    _enqueue_novelty_backfill(novelty_map)
                for p in ranked:
                    if p.get("novelty_score") is None:
                        p["novelty_score"] = novelty_map.get(p["id"])
                ranked.sort(key=lambda x: (x.get("novelty_score") or 0), reverse=True)
            else:
                ranked.sort(key=lambda x: x.get("published", ""), reverse=True)
        elif use_profile:
            ranked = _apply_profile_sort(papers, weights)
        elif sort_mode == "smart":
            ranked = ranker.rank_papers(papers, use_smart_rank=True)
        else:
            ranked = sorted(papers, key=lambda x: x.get("published", ""), reverse=True)

        if pin_map:
            ranked = _apply_pin_order(ranked, pin_map)

        ids = [p.get("id") for p in ranked if p.get("id")][:limit]
        meta_parts = [status]
        if query:
            meta_parts.append(f"query: {query[:60]}")
        meta = " · ".join(meta_parts)
        payload = {
            "ids": ids,
            "title": req.name or "Shared View",
            "meta": meta,
        }
        token = storage.create_share_token("view", json.dumps(payload), ttl_days=SHARE_TOKEN_TTL_DAYS)
    return {"token": token, "count": len(ids)}

@app.post("/api/weekly-picks/share")
def share_weekly_picks(days: int = 7):
    storage.init_db()
    payload = {"days": max(1, int(days))}
    token = storage.create_share_token("weekly_picks", json.dumps(payload), ttl_days=SHARE_TOKEN_TTL_DAYS)
    return {"token": token, "days": payload["days"]}

def _takeaway_from_summary(summary: str) -> str:
    text = (summary or "").strip()
    if not text:
        return "Notable weekly pick."
    for sep in [". ", "? ", "! "]:
        if sep in text:
            line = text.split(sep)[0].strip()
            if line:
                return line[:160]
    return (text[:160] + "…") if len(text) > 160 else text

def _build_weekly_picks_digest(days: int = 7) -> Dict[str, Any]:
    days_int = max(1, int(days))
    picks = storage.list_weekly_picks(days=days_int, limit=80)
    items = []
    for p in picks:
        items.append({
            "paper_id": p.get("id"),
            "title": p.get("title") or p.get("id") or "Untitled",
            "takeaway": _takeaway_from_summary(p.get("summary") or ""),
        })
    now = datetime.now().date().isoformat()
    title = f"Weekly Picks Digest - {now}"
    summary = f"{len(items)} picks from the last {days_int} days."
    return {
        "title": title,
        "summary": summary,
        "days": days_int,
        "created_at": datetime.now().isoformat(),
        "items": items,
    }

@app.get("/api/weekly-picks/digest")
def weekly_picks_digest(days: int = 7):
    storage.init_db()
    digest = _build_weekly_picks_digest(days=days)
    return digest

@app.post("/api/weekly-picks/digest/share")
def share_weekly_picks_digest(days: int = 7):
    storage.init_db()
    digest = _build_weekly_picks_digest(days=days)
    token = storage.create_share_token("weekly_digest", json.dumps(digest), ttl_days=SHARE_TOKEN_TTL_DAYS)
    return {"token": token, "days": digest.get("days")}


def _build_weekly_review(days: int = 7) -> Dict[str, Any]:
    days_int = max(1, min(int(days or 7), 30))
    today = datetime.now().date()
    start = today - timedelta(days=days_int - 1)
    start_iso = start.isoformat()
    end_iso = today.isoformat()

    progress = _reading_plan_progress_summary(days=days_int)
    versions = _build_version_updates_payload(
        since=start_iso,
        scope="watchlist",
        limit=300,
        include_triaged=True,
    )
    active_version_items = [x for x in (versions.get("items") or []) if bool(x.get("triage_active"))]
    picks = storage.list_weekly_picks(days=days_int, limit=80)

    activity = storage.list_reading_plan_activity(
        limit=max(300, days_int * 260),
        date_from=start_iso,
        date_to=end_iso,
    )
    by_paper: Dict[str, Dict[str, Any]] = {}
    for row in activity:
        pid = str(row.get("paper_id") or "")
        if not pid:
            continue
        action = str(row.get("action") or "").strip().lower()
        minutes = max(0, int(row.get("minutes") or 0))
        item = by_paper.setdefault(pid, {"paper_id": pid, "done_count": 0, "done_minutes": 0})
        if action == "done":
            item["done_count"] += 1
            item["done_minutes"] += minutes
        elif action == "undo_done":
            item["done_count"] -= 1
            item["done_minutes"] -= minutes
    ranked_completed = []
    for item in by_paper.values():
        done_count = max(0, int(item.get("done_count") or 0))
        done_minutes = max(0, int(item.get("done_minutes") or 0))
        if done_count <= 0 and done_minutes <= 0:
            continue
        ranked_completed.append(
            {
                "paper_id": item["paper_id"],
                "done_count": done_count,
                "done_minutes": done_minutes,
            }
        )
    ranked_completed.sort(key=lambda x: (int(x.get("done_minutes") or 0), int(x.get("done_count") or 0)), reverse=True)
    top_completed = ranked_completed[:12]

    if top_completed:
        rows = storage.get_papers_by_ids([x["paper_id"] for x in top_completed])
        title_by_id = {str(r.get("id") or ""): str(r.get("title") or "") for r in rows}
        for item in top_completed:
            item["title"] = title_by_id.get(item["paper_id"]) or item["paper_id"]

    day_list = [(start + timedelta(days=i)).isoformat() for i in range(days_int)]
    reading_items = list(progress.get("items") or [])
    reading_by_date = {str(x.get("date") or ""): x for x in reading_items if isinstance(x, dict)}
    reading_trend = [
        {
            "date": day,
            "planned_count": int((reading_by_date.get(day) or {}).get("planned_count") or 0),
            "done_count": int((reading_by_date.get(day) or {}).get("done_count") or 0),
            "done_minutes": int((reading_by_date.get(day) or {}).get("done_minutes") or 0),
            "completion_ratio": float((reading_by_date.get(day) or {}).get("completion_ratio") or 0.0),
        }
        for day in day_list
    ]

    version_by_day: Dict[str, int] = {day: 0 for day in day_list}
    for item in active_version_items:
        day = str(item.get("published") or "")[:10]
        if day in version_by_day:
            version_by_day[day] += 1
    version_trend = [{"date": day, "count": int(version_by_day.get(day) or 0)} for day in day_list]

    picks_by_day: Dict[str, int] = {day: 0 for day in day_list}
    for item in picks:
        day = str(item.get("published") or "")[:10]
        if day in picks_by_day:
            picks_by_day[day] += 1
    picks_trend = [{"date": day, "count": int(picks_by_day.get(day) or 0)} for day in day_list]

    summary = (
        f"{int(progress.get('totals', {}).get('done_count') or 0)} items completed, "
        f"{int(progress.get('totals', {}).get('done_minutes') or 0)} minutes logged, "
        f"{len(active_version_items)} active version updates, "
        f"{len(picks)} weekly picks."
    )
    return {
        "days": days_int,
        "start_date": start_iso,
        "end_date": end_iso,
        "created_at": datetime.now().isoformat(),
        "title": f"Weekly Review - {end_iso}",
        "summary": summary,
        "reading": {
            "streak_days": int(progress.get("streak_days") or 0),
            "completion_rate": float(progress.get("completion_rate") or 0.0),
            "totals": progress.get("totals") or {},
            "carry_over": progress.get("carry_over") or {},
            "today": progress.get("today") or {},
        },
        "version_updates": {
            "active_count": len(active_version_items),
            "triaged_count": int(versions.get("triaged_count") or 0),
            "total_count": int(versions.get("total_count") or 0),
            "items": active_version_items[:12],
        },
        "weekly_picks": {
            "count": len(picks),
            "items": [
                {
                    "paper_id": p.get("id"),
                    "title": p.get("title") or p.get("id"),
                    "published": p.get("published"),
                }
                for p in picks[:12]
            ],
        },
        "trends": {
            "reading": reading_trend,
            "version_updates": version_trend,
            "weekly_picks": picks_trend,
        },
        "top_completed": top_completed,
    }


@app.get("/api/weekly-review")
def weekly_review(days: int = 7):
    storage.init_db()
    return _build_weekly_review(days=days)


@app.post("/api/weekly-review/share")
def share_weekly_review(days: int = 7):
    storage.init_db()
    payload = _build_weekly_review(days=days)
    token = storage.create_share_token("weekly_review", json.dumps(payload), ttl_days=SHARE_TOKEN_TTL_DAYS)
    return {"token": token, "days": payload.get("days")}


def _parse_share_selection_payload(payload_id: str) -> List[str]:
    if not payload_id:
        return []
    raw: Any = None
    try:
        raw = json.loads(payload_id)
    except Exception:
        raw = [p.strip() for p in str(payload_id).split(",") if p.strip()]
    if not isinstance(raw, list):
        return []
    return normalize_paper_ids([str(p) for p in raw if p])

def _order_papers_for_ids(papers: List[Dict[str, Any]], ids: List[str]) -> List[Dict[str, Any]]:
    if not papers or not ids:
        return []
    paper_map = {p.get("id"): p for p in papers if p.get("id")}
    ordered: List[Dict[str, Any]] = []
    used: set[str] = set()
    for pid in ids:
        candidate = paper_map.get(pid)
        if not candidate:
            for p in papers:
                pid_val = p.get("id") or ""
                if pid and pid in pid_val:
                    candidate = p
                    break
        if not candidate:
            continue
        cid = candidate.get("id")
        if not cid or cid in used:
            continue
        ordered.append(candidate)
        used.add(cid)
    return ordered

def _render_shared_paper_list_page(title: str, meta: str, papers: List[Dict[str, Any]]) -> HTMLResponse:
    safe_title = html.escape(title or "Shared Papers")
    safe_meta = html.escape(meta or "")
    items_html_parts = []
    for p in papers:
        title_text = str(p.get("title") or p.get("id") or "Untitled")
        authors = p.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        authors_str = ", ".join(authors)[:120]
        summary = str(p.get("summary") or "")[:320]
        pdf_url = str(p.get("pdf_url") or "#")
        filter_text = f"{title_text} {authors_str} {summary}".lower()
        items_html_parts.append(
            f"<li data-text=\"{html.escape(filter_text, quote=True)}\">"
            f"<strong>{html.escape(title_text)}</strong>"
            f"<div style='color:#94a3b8; font-size:0.85rem;'>{html.escape(authors_str)}</div>"
            f"<div style='margin-top:0.35rem; color:#cbd5f5;'>{html.escape(summary)}</div>"
            f"<div style='margin-top:0.3rem;'><a href='{html.escape(pdf_url)}' style='color:#38bdf8;'>PDF</a></div>"
            f"</li>"
        )
    items_html = "".join(items_html_parts)
    body = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{safe_title}</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#0f172a; color:#e2e8f0; padding:2rem; }}
            .card {{ max-width:860px; margin:0 auto; background:#111827; border-radius:14px; padding:1.5rem; border:1px solid rgba(148,163,184,0.2); }}
            h1 {{ margin-top:0; font-size:1.5rem; }}
            .meta {{ color:#94a3b8; font-size:0.9rem; margin-bottom:0.8rem; }}
            .filter-row {{ display:flex; gap:0.75rem; align-items:center; margin:0.8rem 0 0.6rem; flex-wrap:wrap; }}
            .filter-input {{ flex:1; min-width:220px; padding:0.55rem 0.75rem; border-radius:10px; border:1px solid rgba(148,163,184,0.4); background:#0f172a; color:#e2e8f0; }}
            ol {{ margin:0.8rem 0 0 1.2rem; }}
            li {{ margin-bottom:1.2rem; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>{safe_title}</h1>
            <div class="meta">{safe_meta}</div>
            <div class="filter-row">
                <input id="filterInput" class="filter-input" type="search" placeholder="Filter papers..." autocomplete="off">
                <div id="resultsCount" class="meta">{len(papers)} items</div>
            </div>
            <div id="noResults" class="meta" style="display:none;">No matches found.</div>
            <ol id="papersList">{items_html}</ol>
        </div>
        <script>
            const input = document.getElementById('filterInput');
            const items = Array.from(document.querySelectorAll('#papersList li'));
            const countEl = document.getElementById('resultsCount');
            const emptyEl = document.getElementById('noResults');
            const update = () => {{
                const q = (input.value || '').trim().toLowerCase();
                let visible = 0;
                items.forEach((item) => {{
                    const hay = item.dataset.text || '';
                    const match = !q || hay.includes(q);
                    item.style.display = match ? '' : 'none';
                    if (match) {{
                        visible += 1;
                    }}
                }});
                if (countEl) {{
                    countEl.textContent = visible + " items";
                }}
                if (emptyEl) {{
                    emptyEl.style.display = visible ? 'none' : 'block';
                }}
            }};
            input.addEventListener('input', update);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=body)

@app.get("/api/share/{token}")
def get_shared_payload(token: str):
    storage.init_db()
    record = storage.get_share_token(token)
    if not record:
        raise HTTPException(status_code=404, detail="Share token not found.")
    kind = record.get("kind")
    payload_id = record.get("payload_id")
    if kind == "digest":
        run = storage.get_digest_run(int(payload_id))
        if not run:
            raise HTTPException(status_code=404, detail="Digest not found.")
        return {"kind": "digest", "digest": run}
    if kind == "collection":
        folder = storage.get_folder(str(payload_id))
        if not folder:
            raise HTTPException(status_code=404, detail="Collection not found.")
        papers = _get_folder_papers(folder, limit=80, include_private=False)
        return {"kind": "collection", "collection": folder, "papers": papers}
    if kind == "selection":
        ids = _parse_share_selection_payload(payload_id)
        if not ids:
            raise HTTPException(status_code=400, detail="Invalid selection payload.")
        papers = storage.get_papers_by_ids(ids)
        ordered = _order_papers_for_ids(papers, ids)
        if not ordered:
            raise HTTPException(status_code=404, detail="Selection not found.")
        return {"kind": "selection", "papers": ordered}
    if kind == "weekly_picks":
        days = 7
        try:
            payload = json.loads(payload_id or "{}")
            days = max(1, int(payload.get("days", 7)))
        except Exception:
            days = 7
        picks = storage.list_weekly_picks(days=days, limit=80)
        return {"kind": "weekly_picks", "days": days, "papers": picks}
    if kind == "weekly_digest":
        try:
            payload = json.loads(payload_id or "{}")
            return {"kind": "weekly_digest", "digest": payload}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid weekly digest payload.")
    if kind == "weekly_review":
        try:
            payload = json.loads(payload_id or "{}")
            return {"kind": "weekly_review", "review": payload}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid weekly review payload.")
    if kind == "view":
        try:
            payload = json.loads(payload_id or "{}")
        except Exception:
            payload = {}
        ids = _parse_share_selection_payload(json.dumps(payload.get("ids") or []))
        if not ids:
            raise HTTPException(status_code=400, detail="Invalid view payload.")
        papers = storage.get_papers_by_ids(ids)
        ordered = _order_papers_for_ids(papers, ids)
        if not ordered:
            raise HTTPException(status_code=404, detail="View not found.")
        return {"kind": "view", "title": payload.get("title"), "meta": payload.get("meta"), "papers": ordered}
    raise HTTPException(status_code=400, detail="Unsupported shared payload.")

@app.delete("/api/share/{token}")
def revoke_share_token(token: str):
    storage.init_db()
    ok = storage.delete_share_token(token)
    if not ok:
        raise HTTPException(status_code=404, detail="Share token not found.")
    return {"success": True}

@app.get("/share/{token}")
def get_shared_page(token: str):
    storage.init_db()
    record = storage.get_share_token(token)
    if not record:
        raise HTTPException(status_code=404, detail="Share token not found.")
    kind = record.get("kind")
    payload_id = record.get("payload_id")
    if kind == "digest":
        run = storage.get_digest_run(int(payload_id))
        if not run:
            raise HTTPException(status_code=404, detail="Digest not found.")

        title = html.escape(run.get("title", "Digest"))
        summary = html.escape(run.get("summary", ""))
        created_at = html.escape(run.get("created_at", ""))
        cadence = html.escape(run.get("cadence", ""))
        items = run.get("items") or []
        items_html = "".join(
            f"<li><strong>{html.escape(str(i.get('title') or i.get('paper_id')))}</strong><br>"
            f"<span style='color:#475569;'>{html.escape(str(i.get('reason') or ''))}</span></li>"
            for i in items
        )

        body = f"""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{title}</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#0f172a; color:#e2e8f0; padding:2rem; }}
                .card {{ max-width:760px; margin:0 auto; background:#111827; border-radius:14px; padding:1.5rem; border:1px solid rgba(148,163,184,0.2); }}
                h1 {{ margin-top:0; font-size:1.4rem; }}
                .meta {{ color:#94a3b8; font-size:0.9rem; margin-bottom:0.8rem; }}
                ol {{ margin:0.8rem 0 0 1.2rem; }}
                li {{ margin-bottom:0.8rem; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>{title}</h1>
                <div class="meta">{created_at} • {cadence}</div>
                <p>{summary}</p>
                <h3>Top picks</h3>
                <ol>{items_html}</ol>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=body)

    if kind == "collection":
        folder = storage.get_folder(str(payload_id))
        if not folder:
            raise HTTPException(status_code=404, detail="Collection not found.")
        papers = _get_folder_papers(folder, limit=80, include_private=False)
        title = folder.get("name", "Collection")
        query = folder.get("query", "")
        meta = f"Read-only collection - Query: {query}"
        return _render_shared_paper_list_page(title, meta, papers)

    if kind == "selection":
        ids = _parse_share_selection_payload(payload_id)
        if not ids:
            raise HTTPException(status_code=400, detail="Invalid selection payload.")
        papers = storage.get_papers_by_ids(ids)
        ordered = _order_papers_for_ids(papers, ids)
        if not ordered:
            raise HTTPException(status_code=404, detail="Selection not found.")
        meta = f"Read-only selection - {len(ordered)} papers"
        return _render_shared_paper_list_page("Shared Selection", meta, ordered)

    if kind == "weekly_picks":
        days = 7
        try:
            payload = json.loads(payload_id or "{}")
            days = max(1, int(payload.get("days", 7)))
        except Exception:
            days = 7
        picks = storage.list_weekly_picks(days=days, limit=80)
        meta = f"Read-only weekly picks - last {days} days"
        return _render_shared_paper_list_page("My Weekly Picks", meta, picks)

    if kind == "weekly_digest":
        try:
            payload = json.loads(payload_id or "{}")
        except Exception:
            payload = {}
        title = html.escape(payload.get("title") or "Weekly Picks Digest")
        summary = html.escape(payload.get("summary") or "")
        created_at = html.escape(payload.get("created_at") or "")
        items = payload.get("items") or []
        items_html = "".join(
            f"<li><strong>{html.escape(str(i.get('title') or i.get('paper_id') or ''))}</strong>"
            f"<div style='color:#94a3b8; font-size:0.85rem; margin-top:0.2rem;'>{html.escape(str(i.get('takeaway') or ''))}</div></li>"
            for i in items
        )
        body = f"""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{title}</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#0f172a; color:#e2e8f0; padding:2rem; }}
                .card {{ max-width:860px; margin:0 auto; background:#111827; border-radius:14px; padding:1.5rem; border:1px solid rgba(148,163,184,0.2); }}
                h1 {{ margin-top:0; font-size:1.5rem; }}
                .meta {{ color:#94a3b8; font-size:0.9rem; margin-bottom:0.8rem; }}
                ol {{ margin:0.8rem 0 0 1.2rem; }}
                li {{ margin-bottom:1.0rem; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>{title}</h1>
                <div class="meta">{created_at}</div>
                <p>{summary}</p>
                <ol>{items_html}</ol>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=body)

    if kind == "weekly_review":
        try:
            payload = json.loads(payload_id or "{}")
        except Exception:
            payload = {}
        title = html.escape(payload.get("title") or "Weekly Review")
        summary = html.escape(payload.get("summary") or "")
        start_date = html.escape(payload.get("start_date") or "")
        end_date = html.escape(payload.get("end_date") or "")
        reading = payload.get("reading") or {}
        versions = payload.get("version_updates") or {}
        picks = payload.get("weekly_picks") or {}
        completed = payload.get("top_completed") or []
        completed_html = "".join(
            f"<li><strong>{html.escape(str(i.get('title') or i.get('paper_id') or ''))}</strong>"
            f" · {int(i.get('done_minutes') or 0)}m · {int(i.get('done_count') or 0)} done</li>"
            for i in completed[:12]
        )
        version_html = "".join(
            f"<li>{html.escape(str(i.get('paper_title') or i.get('paper_id') or ''))}"
            f" · v{int(i.get('from_version') or 0)}→v{int(i.get('to_version') or 0)}</li>"
            for i in (versions.get("items") or [])[:12]
        )
        picks_html = "".join(
            f"<li>{html.escape(str(i.get('title') or i.get('paper_id') or ''))}</li>"
            for i in (picks.get("items") or [])[:12]
        )
        body = f"""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{title}</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#0f172a; color:#e2e8f0; padding:2rem; }}
                .card {{ max-width:920px; margin:0 auto; background:#111827; border-radius:14px; padding:1.5rem; border:1px solid rgba(148,163,184,0.2); }}
                .meta {{ color:#94a3b8; font-size:0.9rem; margin-bottom:0.8rem; }}
                .grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:0.7rem; margin:0.8rem 0 1rem; }}
                .tile {{ border:1px solid rgba(148,163,184,0.25); border-radius:10px; padding:0.7rem; background:rgba(255,255,255,0.03); }}
                .label {{ color:#94a3b8; font-size:0.82rem; }}
                .value {{ margin-top:0.2rem; font-weight:700; }}
                h2 {{ margin-top:1rem; font-size:1.1rem; }}
                ol {{ margin:0.55rem 0 0 1.2rem; }}
                li {{ margin-bottom:0.45rem; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>{title}</h1>
                <div class="meta">{start_date} - {end_date}</div>
                <p>{summary}</p>
                <div class="grid">
                    <div class="tile">
                        <div class="label">Reading streak</div>
                        <div class="value">{int(reading.get('streak_days') or 0)} days</div>
                    </div>
                    <div class="tile">
                        <div class="label">Completion</div>
                        <div class="value">{round(float(reading.get('completion_rate') or 0.0) * 100, 1)}%</div>
                    </div>
                    <div class="tile">
                        <div class="label">Active version updates</div>
                        <div class="value">{int(versions.get('active_count') or 0)}</div>
                    </div>
                </div>
                <h2>Top Completed</h2>
                <ol>{completed_html or '<li>No completed items logged.</li>'}</ol>
                <h2>Version Updates</h2>
                <ol>{version_html or '<li>No active updates.</li>'}</ol>
                <h2>Weekly Picks</h2>
                <ol>{picks_html or '<li>No weekly picks.</li>'}</ol>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=body)

    if kind == "view":
        try:
            payload = json.loads(payload_id or "{}")
        except Exception:
            payload = {}
        ids = _parse_share_selection_payload(json.dumps(payload.get("ids") or []))
        if not ids:
            raise HTTPException(status_code=400, detail="Invalid view payload.")
        papers = storage.get_papers_by_ids(ids)
        ordered = _order_papers_for_ids(papers, ids)
        if not ordered:
            raise HTTPException(status_code=404, detail="View not found.")
        title = payload.get("title") or "Shared View"
        meta = payload.get("meta") or "Shared view"
        return _render_shared_paper_list_page(title, meta, ordered)

    raise HTTPException(status_code=400, detail="Unsupported shared payload.")

@app.post("/api/digest/generate")
def generate_digest(req: DigestGenerateRequest):
    storage.init_db()
    cadence = (req.cadence or "daily").strip().lower()
    if cadence not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="cadence must be daily or weekly")

    if not req.force and not _digest_is_due(cadence):
        latest = storage.get_latest_digest(cadence=cadence)
        return {"generated": False, "digest": latest}

    digest = _generate_digest_run(
        cadence=cadence,
        max_items=max(3, min(int(req.max_items), 15)),
        persist=True,
    )
    return {"generated": True, "digest": digest}

@app.post("/api/jobs/compare-matrix")
def submit_compare_matrix_job(req: CompareRequest):
    if len(req.paper_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 papers.")
    if len(req.paper_ids) > 6:
        raise HTTPException(status_code=400, detail="Select at most 6 papers.")
    job = _create_job("compare_matrix", {"paper_ids": req.paper_ids})
    return {"job_id": job["id"], "status": job["status"]}

@app.post("/api/jobs/reproducibility")
def submit_reproducibility_job(req: ReproJobRequest):
    if not req.paper_id:
        raise HTTPException(status_code=400, detail="paper_id is required.")
    job = _create_job("reproducibility", {"paper_id": req.paper_id})
    return {"job_id": job["id"], "status": job["status"]}

@app.post("/api/jobs/discover")
def submit_discover_job():
    job = _create_job("discover", {})
    return {"job_id": job["id"], "status": job["status"]}

@app.post("/api/jobs/benchmark-extract")
def submit_benchmark_extract_job(req: CompareRequest):
    if len(req.paper_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 papers.")
    if len(req.paper_ids) > 8:
        raise HTTPException(status_code=400, detail="Select at most 8 papers.")
    job = _create_job("benchmark_extract", {"paper_ids": req.paper_ids})
    return {"job_id": job["id"], "status": job["status"]}

@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _decorate_job_for_client(job)

@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = _cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job": _decorate_job_for_client(job)}

@app.post("/api/papers/{paper_id:path}/bookmark")
def bookmark_paper(paper_id: str, req: BookmarkRequest):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    resolved_id = str(paper.get("id") or paper_id)
    if req.active:
        storage.add_bookmark(resolved_id)
    else:
        storage.remove_bookmark(resolved_id)
    _bump_api_cache_epochs("papers")
    return {"success": True}

@app.post("/api/papers/{paper_id:path}/rate")
def rate_paper(paper_id: str, req: RateRequest, background_tasks: BackgroundTasks):
    print(f"DEBUG: Rate request for paper_id='{paper_id}' status='{req.status}'")
    if req.status not in ['liked', 'dismissed']:
        raise HTTPException(status_code=400, detail="Invalid status")
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    resolved_id = str(paper.get("id") or paper_id)

    storage.update_interaction(resolved_id, req.status)
    _bump_api_cache_epochs("papers", "graph")
    
    if req.status == 'liked':
        background_tasks.add_task(downloader.download_pdf, resolved_id)
        background_tasks.add_task(background_retrain)
        
    return {"success": True}

@app.get("/api/papers/{paper_id:path}/reading")
def get_paper_reading_status(paper_id: str):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    status = storage.get_reading_status(paper.get("id"))
    if not status:
        return {"paper_id": paper.get("id"), "status": "queue", "progress": 0}
    return status

@app.get("/api/papers/{paper_id:path}/reading-time")
def get_paper_reading_time(paper_id: str, download: bool = False, refresh: bool = False):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    pid = paper.get("id")
    if not refresh:
        existing = storage.get_reading_time(pid)
        if existing and int(existing.get("minutes") or 0) > 0:
            return {
                "paper_id": pid,
                "page_count": int(existing.get("page_count") or 0),
                "minutes": int(existing.get("minutes") or 0),
                "updated_at": existing.get("updated_at"),
                "cached": True,
                "available": True,
            }

    pdf_path = find_local_pdf_path(pid)
    if not pdf_path and download:
        try:
            downloader.download_pdf(pid)
            pdf_path = find_local_pdf_path(pid)
        except Exception as e:
            return {
                "paper_id": pid,
                "available": False,
                "reason": f"download_failed: {e}",
            }

    if not pdf_path or not os.path.exists(pdf_path):
        return {
            "paper_id": pid,
            "available": False,
            "reason": "pdf_not_found",
        }

    pages = ai_service.count_pdf_pages(pdf_path)
    if pages <= 0:
        return {
            "paper_id": pid,
            "available": False,
            "reason": "page_count_failed",
        }

    minutes = ai_service.estimate_reading_time_minutes(pages)
    rec = storage.set_reading_time(pid, pages, minutes)
    return {
        "paper_id": pid,
        "page_count": rec.get("page_count", pages),
        "minutes": rec.get("minutes", minutes),
        "updated_at": rec.get("updated_at"),
        "cached": False,
        "available": True,
    }

@app.post("/api/papers/{paper_id:path}/reading")
def set_paper_reading_status(paper_id: str, req: ReadingStatusRequest):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    status = storage.set_reading_status(
        paper.get("id"),
        status=req.status,
        progress=req.progress,
    )
    if status.get("status") in {"reading", "done"}:
        storage.clear_deferred_reading_plan_paper(paper.get("id"))
    _bump_api_cache_epochs("papers")
    _refresh_today_reading_plan_async(source="reading_status")
    return status


@app.post("/api/reading-plan/generate")
def generate_reading_plan(req: ReadingPlanGenerateRequest):
    storage.init_db()
    options = _sanitize_reading_plan_options(
        total_minutes=req.total_minutes,
        max_items=req.max_items,
        budget_mode=req.budget_mode,
        include_new=req.include_new,
        include_liked=req.include_liked,
        include_bookmarked=req.include_bookmarked,
    )
    _save_last_reading_plan_options(options)
    cache_key = _reading_plan_cache_key(
        total_minutes=options.get("total_minutes"),
        max_items=options.get("max_items"),
        budget_mode=options.get("budget_mode"),
        include_new=options.get("include_new"),
        include_liked=options.get("include_liked"),
        include_bookmarked=options.get("include_bookmarked"),
    )

    if not bool(req.refresh):
        cached = storage.get_ai_cache(cache_key, max_age_seconds=READING_PLAN_CACHE_TTL_SECONDS)
        if cached:
            try:
                payload = json.loads(cached)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                payload["cached"] = True
                return payload

    payload = _build_reading_plan_payload(
        total_minutes=options.get("total_minutes"),
        max_items=options.get("max_items"),
        budget_mode=options.get("budget_mode"),
        include_new=options.get("include_new"),
        include_liked=options.get("include_liked"),
        include_bookmarked=options.get("include_bookmarked"),
    )
    payload["cached"] = False
    payload["options"] = options
    storage.set_ai_cache(cache_key, json.dumps(payload))
    _persist_reading_plan_snapshot(payload, options, source="generate")
    return payload


@app.get("/api/reading-plan/today")
def get_today_reading_plan(refresh: bool = False):
    storage.init_db()
    options = _load_last_reading_plan_options()
    cache_key = _reading_plan_cache_key(
        total_minutes=options.get("total_minutes"),
        max_items=options.get("max_items"),
        budget_mode=options.get("budget_mode"),
        include_new=options.get("include_new"),
        include_liked=options.get("include_liked"),
        include_bookmarked=options.get("include_bookmarked"),
    )
    if not refresh:
        cached = storage.get_ai_cache(cache_key, max_age_seconds=READING_PLAN_CACHE_TTL_SECONDS)
        if cached:
            try:
                payload = json.loads(cached)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                payload["cached"] = True
                return payload

    return _refresh_today_reading_plan_cache(source="today")


@app.get("/api/reading-plan/history")
def get_reading_plan_history(
    limit: int = 30,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    storage.init_db()
    items = storage.list_reading_plan_snapshots(limit=limit, date_from=date_from, date_to=date_to)
    return {"count": len(items), "items": items}


@app.get("/api/reading-plan/progress")
def get_reading_plan_progress(days: int = 14):
    storage.init_db()
    return _reading_plan_progress_summary(days=days)


@app.post("/api/reading-plan/action")
def apply_reading_plan_action(req: ReadingPlanActionRequest):
    storage.init_db()
    paper = _resolve_paper_by_id(req.paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    pid = str(paper.get("id") or "")
    action = (req.action or "").lower().strip()
    today_iso = datetime.now().date().isoformat()
    plan_before = _latest_reading_plan_payload_for_date(today_iso)
    action_minutes = _reading_plan_minutes_for_paper(pid, plan_before)

    if action == "done":
        reading = storage.set_reading_status(pid, status="done", progress=100)
        storage.clear_deferred_reading_plan_paper(pid)
        _record_reading_plan_activity("done", pid, minutes=action_minutes, meta={"source": "reading_plan_action"})
        _bump_api_cache_epochs("papers")
        plan = _refresh_today_reading_plan_cache(source="action_done")
        return {
            "success": True,
            "action": "done",
            "paper_id": pid,
            "reading": reading,
            "plan": {
                "date": plan.get("date"),
                "count": int(plan.get("count") or 0),
                "planned_minutes": int(plan.get("planned_minutes") or 0),
            },
            "progress": _reading_plan_progress_summary(days=14),
        }

    if action == "defer":
        days = max(1, min(int(req.defer_days or 1), 30))
        defer_until = (datetime.now().date() + timedelta(days=days)).isoformat()
        deferred = storage.defer_reading_plan_paper(pid, defer_until=defer_until, reason=req.reason)
        _record_reading_plan_activity(
            "defer",
            pid,
            minutes=action_minutes,
            meta={"days": days, "defer_until": defer_until, "reason": req.reason},
        )
        plan = _refresh_today_reading_plan_cache(source="action_defer")
        return {
            "success": True,
            "action": "defer",
            "paper_id": pid,
            "deferred": deferred,
            "plan": {
                "date": plan.get("date"),
                "count": int(plan.get("count") or 0),
                "planned_minutes": int(plan.get("planned_minutes") or 0),
            },
            "progress": _reading_plan_progress_summary(days=14),
        }

    if action == "undo_done":
        reading = storage.set_reading_status(pid, status="queue", progress=0)
        _record_reading_plan_activity("undo_done", pid, minutes=action_minutes, meta={"source": "reading_plan_action"})
        _bump_api_cache_epochs("papers")
        plan = _refresh_today_reading_plan_cache(source="action_undo_done")
        return {
            "success": True,
            "action": "undo_done",
            "paper_id": pid,
            "reading": reading,
            "plan": {
                "date": plan.get("date"),
                "count": int(plan.get("count") or 0),
                "planned_minutes": int(plan.get("planned_minutes") or 0),
            },
            "progress": _reading_plan_progress_summary(days=14),
        }

    if action == "undefer":
        cleared = storage.clear_deferred_reading_plan_paper(pid)
        _record_reading_plan_activity("undefer", pid, minutes=action_minutes, meta={"cleared": bool(cleared)})
        plan = _refresh_today_reading_plan_cache(source="action_undefer")
        return {
            "success": True,
            "action": "undefer",
            "paper_id": pid,
            "cleared": bool(cleared),
            "plan": {
                "date": plan.get("date"),
                "count": int(plan.get("count") or 0),
                "planned_minutes": int(plan.get("planned_minutes") or 0),
            },
            "progress": _reading_plan_progress_summary(days=14),
        }

    raise HTTPException(status_code=400, detail="action must be one of: done, defer, undo_done, undefer")


@app.get("/api/reading-plan/{plan_date}")
def get_reading_plan_for_date(plan_date: str):
    storage.init_db()
    try:
        datetime.strptime(plan_date, "%Y-%m-%d")
    except Exception:
        raise HTTPException(status_code=400, detail="plan_date must be YYYY-MM-DD")
    snap = storage.get_reading_plan_snapshot(plan_date)
    if not snap:
        raise HTTPException(status_code=404, detail="Reading plan snapshot not found")
    payload = snap.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    payload["cached"] = True
    payload["options"] = snap.get("options") or payload.get("options") or _sanitize_reading_plan_options()
    payload["snapshot_id"] = snap.get("id")
    payload["snapshot_created_at"] = snap.get("created_at")
    payload["snapshot_source"] = snap.get("source")
    return payload

def _normalize_notes_templates(templates: Any) -> List[Dict[str, str]]:
    if not isinstance(templates, list):
        return copy.deepcopy(DEFAULT_NOTES_TEMPLATES)
    out: List[Dict[str, str]] = []
    for idx, row in enumerate(templates):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        body = str(row.get("body") or "").strip()
        if not name or not body:
            continue
        raw_id = str(row.get("id") or "").strip().lower()
        if not raw_id:
            raw_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not raw_id:
            raw_id = f"template-{idx + 1}"
        out.append(
            {
                "id": raw_id[:64],
                "name": name[:80],
                "body": body[:8000],
            }
        )
        if len(out) >= 24:
            break
    if not out:
        return copy.deepcopy(DEFAULT_NOTES_TEMPLATES)
    return out

def _load_notes_templates() -> List[Dict[str, str]]:
    raw = storage.get_ai_cache(NOTES_TEMPLATES_CACHE_KEY, max_age_seconds=365 * 24 * 3600)
    if not raw:
        return copy.deepcopy(DEFAULT_NOTES_TEMPLATES)
    try:
        parsed = json.loads(raw)
    except Exception:
        return copy.deepcopy(DEFAULT_NOTES_TEMPLATES)
    return _normalize_notes_templates(parsed)

def _build_notes_auto_summary_block(paper: Dict[str, Any], style: str = "concise") -> str:
    style_clean = str(style or "concise").strip().lower()
    if style_clean not in {"concise", "structured", "deep"}:
        style_clean = "concise"
    title = str(paper.get("title") or "").strip()
    summary = str(paper.get("summary") or "").strip()
    structure = ai_service.extract_paper_structure(paper)
    prompt = (
        "Create a Markdown notes block for this paper.\n"
        f"Style: {style_clean}\n"
        "Keep it factual and concise. Include: TL;DR, Method, Evidence, Caveats, and Next action.\n"
        "Do not invent facts; explicitly write 'Not found in abstract' when missing.\n\n"
        f"Title: {title}\n"
        f"Abstract: {summary}\n"
        f"Structure hints: {json.dumps(structure)}\n\n"
        "Return only Markdown."
    )
    ai_text = (ai_service.query_ollama(prompt, "", timeout=120) or "").strip()
    if ai_text:
        return ai_text

    def pick(field: str, default: str = "Not found in abstract."):
        value = str((structure or {}).get(field) or "").strip()
        return value or default

    return (
        f"## Auto Summary\n"
        f"- **TL;DR:** {pick('problem')}\n\n"
        f"### Method\n"
        f"- {pick('method')}\n\n"
        f"### Evidence\n"
        f"- {pick('results')}\n\n"
        f"### Caveats\n"
        f"- {pick('limitations')}\n\n"
        f"### Next Action\n"
        f"- Verify dataset/setup details before reproducing results.\n"
    )

@app.get("/api/notes/templates")
def list_notes_templates_endpoint():
    storage.init_db()
    templates = _load_notes_templates()
    return {"count": len(templates), "templates": templates}

@app.post("/api/notes/templates")
def save_notes_templates_endpoint(req: NotesTemplatesRequest):
    storage.init_db()
    templates = _normalize_notes_templates(req.templates)
    storage.set_ai_cache(NOTES_TEMPLATES_CACHE_KEY, json.dumps(templates))
    return {"success": True, "count": len(templates), "templates": templates}

@app.post("/api/papers/{paper_id:path}/notes/auto-summary")
def generate_notes_auto_summary_endpoint(paper_id: str, req: Optional[NotesAutoSummaryRequest] = None):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    style = (req.style if req else "concise") or "concise"
    block = _build_notes_auto_summary_block(paper, style=style)
    return {
        "paper_id": paper.get("id"),
        "style": str(style).strip().lower(),
        "block": block,
    }

@app.get("/api/papers/{paper_id:path}/questions")
def get_paper_questions(paper_id: str, refresh: bool = False):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    cache_key = f"paper_questions:{paper.get('id')}"
    if not refresh:
        cached = storage.get_ai_cache(cache_key, max_age_seconds=30 * 24 * 3600)
        if cached:
            try:
                questions = json.loads(cached)
            except Exception:
                questions = []
            return {"paper_id": paper.get("id"), "questions": questions, "cached": True, "available": True}
        return {"paper_id": paper.get("id"), "questions": [], "cached": False, "available": False}

    questions = ai_service.generate_reading_questions(paper)
    storage.set_ai_cache(cache_key, json.dumps(questions))
    return {"paper_id": paper.get("id"), "questions": questions, "cached": False, "available": True}

@app.get("/api/papers/{paper_id:path}/notes")
def get_paper_notes_endpoint(paper_id: str):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    notes = storage.get_paper_notes(paper.get("id"))
    if not notes:
        return {"paper_id": paper.get("id"), "notes": ""}
    return notes

@app.post("/api/papers/{paper_id:path}/notes")
def set_paper_notes_endpoint(paper_id: str, req: NotesRequest):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    current = storage.get_paper_notes(paper.get("id"))
    expected = (req.last_updated_at or "").strip()
    current_updated = (current or {}).get("updated_at") or ""
    if req.last_updated_at is not None and expected != current_updated:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Notes updated elsewhere.",
                "current": {
                    "paper_id": paper.get("id"),
                    "notes": (current or {}).get("notes") or "",
                    "updated_at": current_updated,
                },
            },
        )
    result = storage.set_paper_notes(paper.get("id"), req.notes)
    _bump_api_cache_epochs("papers")
    return result

@app.get("/api/papers/{paper_id:path}/notes/history")
def list_notes_history_endpoint(paper_id: str, limit: int = 20):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return storage.list_paper_notes_history(paper.get("id"), limit=limit)

@app.get("/api/papers/{paper_id:path}/notes/diff")
def diff_notes_endpoint(paper_id: str, history_id: str):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    entry = storage.get_paper_notes_history_entry(history_id)
    if not entry or entry.get("paper_id") != paper.get("id"):
        raise HTTPException(status_code=404, detail="Notes history entry not found")
    current = storage.get_paper_notes(paper.get("id")) or {"notes": "", "updated_at": ""}
    from_lines = (entry.get("notes") or "").splitlines()
    to_lines = (current.get("notes") or "").splitlines()
    diff_lines = difflib.unified_diff(
        from_lines,
        to_lines,
        fromfile="history",
        tofile="current",
        lineterm="",
    )
    diff_text = "\n".join(diff_lines)
    return {
        "diff": diff_text,
        "from": {"id": entry.get("id"), "created_at": entry.get("created_at")},
        "to": {"updated_at": current.get("updated_at")},
    }

@app.post("/api/papers/{paper_id:path}/notes/history/{history_id}/restore")
def restore_notes_history_endpoint(paper_id: str, history_id: str):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    entry = storage.get_paper_notes_history_entry(history_id)
    if not entry or entry.get("paper_id") != paper.get("id"):
        raise HTTPException(status_code=404, detail="Notes history entry not found")
    result = storage.set_paper_notes(paper.get("id"), entry.get("notes"))
    _bump_api_cache_epochs("papers")
    return result

@app.get("/api/notes/export")
def export_notes_endpoint():
    storage.init_db()
    items = storage.export_notes()
    return {
        "exported_at": datetime.now().isoformat(),
        "count": len(items),
        "items": items,
    }

@app.post("/api/notes/import")
def import_notes_endpoint(req: NotesImportRequest):
    storage.init_db()
    items = req.items or []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items must be a list")
    skipped = 0
    entries: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            continue
        pid = item.get("paper_id") or item.get("id")
        notes = (item.get("notes") or "").strip()
        if not pid or not notes:
            skipped += 1
            continue
        norm = normalize_paper_id(str(pid))
        paper = storage.get_paper_by_id(norm) or storage.get_paper_by_id(str(pid))
        if not paper:
            skipped += 1
            continue
        entries.append({"paper_id": paper.get("id"), "notes": notes})
    bulk = storage.import_notes_bulk(entries)
    imported = int(bulk.get("imported") or 0)
    skipped += int(bulk.get("skipped") or 0)
    if imported:
        _bump_api_cache_epochs("papers")
    return {"imported": imported, "skipped": skipped}

@app.get("/api/papers/{paper_id:path}/comments")
def list_paper_comments_endpoint(paper_id: str, limit: int = 50):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return storage.list_paper_comments(paper.get("id"), limit=limit)

@app.post("/api/papers/{paper_id:path}/comments")
def add_paper_comment_endpoint(paper_id: str, req: CommentRequest):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    body = (req.body or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Comment body is required.")
    mentions = sorted(set(MENTION_RE.findall(body)))
    comment = storage.add_paper_comment(paper.get("id"), req.author or "", body, mentions)
    return comment

@app.get("/api/mentions")
def list_mentions_endpoint(handle: str, limit: int = 50):
    storage.init_db()
    clean = (handle or "").strip().lstrip("@")
    if not clean:
        raise HTTPException(status_code=400, detail="handle is required")
    return storage.list_mentions_for_handle(clean, limit=limit)

@app.delete("/api/papers/{paper_id:path}/comments/{comment_id}")
def delete_paper_comment_endpoint(paper_id: str, comment_id: str):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    ok = storage.delete_paper_comment(comment_id)
    return {"success": ok}

@app.post("/api/papers/{paper_id:path}/follow-ups")
def add_follow_up_endpoint(paper_id: str, req: FollowUpRequest):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    try:
        days = max(1, int(req.days))
    except Exception:
        days = 7
    remind_at = (datetime.now() + timedelta(days=days)).isoformat()
    result = storage.add_follow_up(paper.get("id"), remind_at, req.note)
    return result

@app.get("/api/follow-ups")
def list_follow_ups_endpoint(due_only: bool = True, limit: int = 50):
    storage.init_db()
    return storage.list_follow_ups(due_only=bool(due_only), limit=limit)

@app.get("/api/follow-ups/count")
def count_follow_ups_endpoint():
    storage.init_db()
    return {"due": int(storage.count_follow_ups_due())}

@app.post("/api/follow-ups/{follow_id}/done")
def mark_follow_up_done_endpoint(follow_id: str):
    storage.init_db()
    ok = storage.mark_follow_up_done(follow_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    return {"success": True}

@app.post("/api/follow-ups/{follow_id}/snooze")
def snooze_follow_up_endpoint(follow_id: str, req: FollowUpSnoozeRequest):
    storage.init_db()
    days = max(1, min(int(req.days or 3), 90))
    item = storage.snooze_follow_up(follow_id, days=days)
    if not item:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    return {"success": True, "item": item, "days": days}

@app.get("/api/papers/{paper_id:path}/links")
def list_paper_links_endpoint(paper_id: str, limit: int = 50):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return storage.list_paper_links(paper.get("id"), limit=limit)

@app.post("/api/papers/{paper_id:path}/links")
def add_paper_link_endpoint(paper_id: str, req: LinkRequest):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    related_norm = normalize_paper_id(req.related_id)
    related = storage.get_paper_by_id(related_norm) or storage.get_paper_by_id(req.related_id)
    if not related:
        raise HTTPException(status_code=404, detail="Related paper not found")
    result = storage.add_paper_link(paper.get("id"), related.get("id"), req.relation, req.note)
    return result

@app.delete("/api/papers/{paper_id:path}/links/{link_id}")
def delete_paper_link_endpoint(paper_id: str, link_id: str):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    ok = storage.delete_paper_link(link_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"success": True}

@app.get("/api/papers/{paper_id:path}/assignments")
def list_paper_assignments_endpoint(
    paper_id: str,
    status: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 100,
):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    items = storage.list_paper_assignments(
        paper_id=paper.get("id"),
        status=status,
        unread_only=bool(unread_only),
        limit=limit,
    )
    return {"paper_id": paper.get("id"), "count": len(items), "items": items}

@app.post("/api/papers/{paper_id:path}/assignments")
def add_paper_assignment_endpoint(paper_id: str, req: AssignmentRequest):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    assignee = str(req.assignee or "").strip()
    if not assignee:
        raise HTTPException(status_code=400, detail="assignee is required")

    due_at = str(req.due_at or "").strip() or None
    if not due_at and req.due_in_days is not None:
        days = max(0, min(int(req.due_in_days or 0), 365))
        if days > 0:
            due_at = (datetime.now() + timedelta(days=days)).isoformat()
    created = storage.add_paper_assignment(
        paper_id=paper.get("id"),
        assignee=assignee,
        due_at=due_at,
        status=req.status,
        note=req.note,
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create assignment")
    _bump_api_cache_epochs("papers")
    return created

@app.get("/api/assignments")
def list_assignments_endpoint(
    assignee: Optional[str] = None,
    status: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 150,
):
    storage.init_db()
    items = storage.list_paper_assignments(
        assignee=assignee,
        status=status,
        unread_only=bool(unread_only),
        limit=limit,
    )
    return {"count": len(items), "items": items}

@app.put("/api/assignments/{assignment_id}")
def update_assignment_endpoint(assignment_id: str, req: AssignmentUpdateRequest):
    storage.init_db()
    updates: Dict[str, Any] = {}
    if req.assignee is not None:
        updates["assignee"] = req.assignee
    if req.due_at is not None:
        updates["due_at"] = req.due_at
    if req.status is not None:
        updates["status"] = req.status
    if req.note is not None:
        updates["note"] = req.note
    item = storage.update_paper_assignment(assignment_id, updates)
    if not item:
        raise HTTPException(status_code=404, detail="Assignment not found")
    _bump_api_cache_epochs("papers")
    return item

@app.post("/api/assignments/{assignment_id}/viewed")
def mark_assignment_viewed_endpoint(assignment_id: str):
    storage.init_db()
    ok = storage.mark_paper_assignment_viewed(assignment_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return {"success": True, "assignment_id": assignment_id}

@app.get("/api/config")
def get_config():
    return {
        "keywords": config.KEYWORDS,
        "categories": config.CATEGORIES,
        "vault_path": config.VAULT_PATH,
        "warmup_models": bool(config.WARMUP_MODELS),
    }

@app.get("/api/settings")
def get_all_settings():
    storage.init_db()
    alert_settings = storage.get_alert_settings()
    return {
        "keywords": config.KEYWORDS,
        "categories": config.CATEGORIES,
        "vault_path": config.VAULT_PATH,
        "citation_threshold": int(alert_settings.get("citation_threshold", 25)),
        "max_results": int(alert_settings.get("max_results", 100)),
        "warmup_models": bool(config.WARMUP_MODELS),
        "notion_token": config.NOTION_TOKEN,
        "notion_database_id": config.NOTION_DATABASE_ID,
    }

@app.post("/api/config")
def update_config(req: ConfigRequest):
    previous_keywords = list(config.KEYWORDS)
    config.save_config(
        req.categories,
        req.keywords,
        req.vault_path,
        req.warmup_models,
        notion_token=req.notion_token,
        notion_database_id=req.notion_database_id,
    )
    if previous_keywords != list(config.KEYWORDS):
        threading.Thread(target=storage.recompute_match_scores, args=(list(config.KEYWORDS),), daemon=True).start()
    _bump_api_cache_epochs("papers")
    return {"success": True}

@app.post("/api/settings")
def update_all_settings(req: CombinedSettingsRequest):
    storage.init_db()
    previous_config = {
        "categories": list(config.CATEGORIES),
        "keywords": list(config.KEYWORDS),
        "vault_path": config.VAULT_PATH,
        "warmup_models": bool(config.WARMUP_MODELS),
        "notion_token": config.NOTION_TOKEN,
        "notion_database_id": config.NOTION_DATABASE_ID,
    }
    previous_alerts = storage.get_alert_settings()
    next_alerts = {
        "citation_threshold": max(0, int(req.citation_threshold)),
        "max_results": max(10, int(req.max_results)),
    }

    try:
        config.save_config(
            req.categories,
            req.keywords,
            req.vault_path,
            req.warmup_models,
            notion_token=req.notion_token,
            notion_database_id=req.notion_database_id,
        )
        storage.set_alert_settings(next_alerts)
    except Exception as e:
        rollback_errors = []
        try:
            config.save_config(
                previous_config["categories"],
                previous_config["keywords"],
                previous_config["vault_path"],
                previous_config["warmup_models"],
                notion_token=previous_config.get("notion_token"),
                notion_database_id=previous_config.get("notion_database_id"),
            )
        except Exception as rollback_cfg_err:
            rollback_errors.append(f"config rollback failed: {rollback_cfg_err}")
        try:
            storage.set_alert_settings(previous_alerts)
        except Exception as rollback_alert_err:
            rollback_errors.append(f"alert rollback failed: {rollback_alert_err}")

        detail = f"Failed to save settings: {e}"
        if rollback_errors:
            detail += " | " + " | ".join(rollback_errors)
        raise HTTPException(status_code=500, detail=detail)

    if bool(req.warmup_models) and not previous_config.get("warmup_models"):
        _warm_models_async("settings")

    if previous_config.get("keywords") != list(config.KEYWORDS):
        threading.Thread(target=storage.recompute_match_scores, args=(list(config.KEYWORDS),), daemon=True).start()
        _bump_api_cache_epochs("papers")

    return {
        "success": True,
        "settings": {
            "keywords": config.KEYWORDS,
            "categories": config.CATEGORIES,
            "vault_path": config.VAULT_PATH,
            "citation_threshold": next_alerts["citation_threshold"],
            "max_results": next_alerts["max_results"],
            "warmup_models": bool(config.WARMUP_MODELS),
            "notion_token": config.NOTION_TOKEN,
            "notion_database_id": config.NOTION_DATABASE_ID,
        },
    }

@app.get("/api/inbox-rules")
def list_inbox_rules():
    storage.init_db()
    return storage.list_inbox_rules(enabled_only=False)

@app.post("/api/inbox-rules")
def create_inbox_rule(req: InboxRuleRequest):
    storage.init_db()
    scope = _normalize_rule_scope(req.scope)
    target_kind = _normalize_inbox_kind(req.target_kind)
    try:
        min_novelty = float(req.min_novelty or 0.0)
    except Exception:
        min_novelty = 0.0
    min_novelty = max(0.0, min(1.0, min_novelty))
    rule = {
        "name": req.name,
        "enabled": bool(req.enabled),
        "action": req.action,
        "label": req.label,
        "keywords": req.keywords,
        "authors": req.authors,
        "venues": req.venues,
        "scope": scope,
        "target_kind": target_kind or None,
        "snooze_days": max(1, min(int(req.snooze_days or 3), 90)),
        "min_novelty": min_novelty,
        "quiet_hours_start": req.quiet_hours_start,
        "quiet_hours_end": req.quiet_hours_end,
    }
    created = storage.add_inbox_rule(rule)
    _clear_inbox_rule_diag_cache()
    return created

@app.put("/api/inbox-rules/{rule_id}")
def update_inbox_rule(rule_id: str, req: InboxRuleRequest):
    storage.init_db()
    scope = _normalize_rule_scope(req.scope)
    target_kind = _normalize_inbox_kind(req.target_kind)
    try:
        min_novelty = float(req.min_novelty or 0.0)
    except Exception:
        min_novelty = 0.0
    min_novelty = max(0.0, min(1.0, min_novelty))
    updates = {
        "name": req.name,
        "enabled": bool(req.enabled),
        "action": req.action,
        "label": req.label,
        "keywords": req.keywords,
        "authors": req.authors,
        "venues": req.venues,
        "scope": scope,
        "target_kind": target_kind or None,
        "snooze_days": max(1, min(int(req.snooze_days or 3), 90)),
        "min_novelty": min_novelty,
        "quiet_hours_start": req.quiet_hours_start,
        "quiet_hours_end": req.quiet_hours_end,
    }
    storage.update_inbox_rule(rule_id, updates)
    _clear_inbox_rule_diag_cache()
    return {"success": True}

@app.delete("/api/inbox-rules/{rule_id}")
def delete_inbox_rule_endpoint(rule_id: str):
    storage.init_db()
    ok = storage.delete_inbox_rule(rule_id)
    _clear_inbox_rule_diag_cache()
    return {"success": ok}

@app.get("/api/inbox-rules/audit")
def list_inbox_rule_audit_endpoint(limit: int = 200, rule_id: Optional[str] = None):
    storage.init_db()
    items = storage.list_inbox_rule_audit(limit=limit, rule_id=rule_id)
    return {"count": len(items), "items": items}

@app.get("/api/inbox-rules/diagnostics")
def get_inbox_rule_diagnostics(limit: int = 200):
    storage.init_db()
    lim = max(20, min(1000, int(limit or 200)))
    cache_key = f"diag:{lim}"
    now_ts = time.time()
    with _INBOX_RULE_DIAG_CACHE_LOCK:
        cached = _INBOX_RULE_DIAG_CACHE.get(cache_key)
        if cached and (now_ts - float(cached.get("ts") or 0.0)) <= _INBOX_RULE_DIAG_CACHE_TTL_SECONDS:
            payload = cached.get("payload")
            if isinstance(payload, dict):
                return payload
    payload = _build_inbox_rule_diagnostics(limit=lim)
    with _INBOX_RULE_DIAG_CACHE_LOCK:
        _INBOX_RULE_DIAG_CACHE[cache_key] = {"ts": now_ts, "payload": payload}
    return payload

@app.post("/api/inbox-rules/preview")
def preview_inbox_rules(req: Optional[InboxRulesRunRequest] = None):
    storage.init_db()
    payload = req or InboxRulesRunRequest(scope="all", dry_run=True, limit=200)
    return _run_inbox_rules(scope=payload.scope, dry_run=True, limit=payload.limit)

@app.post("/api/inbox-rules/apply")
def apply_inbox_rules(req: Optional[InboxRulesRunRequest] = None):
    storage.init_db()
    payload = req or InboxRulesRunRequest(scope="papers", dry_run=False, limit=200)
    result = _run_inbox_rules(scope=payload.scope, dry_run=bool(payload.dry_run), limit=payload.limit)
    return result

@app.get("/api/pins")
def list_pins():
    storage.init_db()
    papers = storage.get_papers_by_status("liked")
    ids = [p.get("id") for p in papers if p.get("id")]
    pin_map = storage.get_pinned_map(ids)
    return pin_map

@app.post("/api/pins/{paper_id:path}")
def set_pin_endpoint(paper_id: str, req: PinRequest):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
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
    _bump_api_cache_epochs("papers")
    return result

@app.delete("/api/pins/{paper_id:path}")
def remove_pin_endpoint(paper_id: str):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    ok = storage.remove_pin(paper.get("id"))
    if ok:
        _bump_api_cache_epochs("papers")
    return {"success": ok}

@app.post("/api/papers/{paper_id:path}/weekly-pick")
def set_weekly_pick_endpoint(paper_id: str, req: WeeklyPickRequest):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    result = storage.set_weekly_pick(paper.get("id"), bool(req.active))
    _bump_api_cache_epochs("papers")
    return result

@app.get("/api/weekly-picks")
def list_weekly_picks_endpoint(days: int = 7, limit: int = 50):
    storage.init_db()
    picks = storage.list_weekly_picks(days=days, limit=limit)
    _attach_labels(picks)
    return {"items": picks, "days": max(1, int(days)), "count": len(picks)}

@app.get("/api/authors/following")
def get_followed_authors():
    storage.init_db()
    return storage.get_followed_authors()

@app.post("/api/authors/follow")
def follow_author(req: AuthorRequest):
    storage.init_db()
    storage.follow_author(req.name)
    return {"success": True}

@app.post("/api/authors/unfollow")
def unfollow_author(req: AuthorRequest):
    storage.init_db()
    storage.unfollow_author(req.name)
    return {"success": True}

@app.get("/api/stats")
def get_stats():
    storage.init_db()
    cached = _api_cache_get("stats", ttl_seconds=60, epoch_key="stats")
    if cached is not None:
        return cached
    data = storage.get_daily_stats()
    _api_cache_set("stats", data, epoch_key="stats")
    return data

@app.get("/api/graph")
async def get_graph():
    storage.init_db()
    cached = _api_cache_get("graph", ttl_seconds=60, epoch_key="graph")
    if cached is not None:
        return cached
    data = storage.get_graph_data()
    _api_cache_set("graph", data, epoch_key="graph")
    return data

@app.post("/api/citations/links")
def get_citation_links(req: CitationLinksRequest):
    storage.init_db()
    ids = normalize_paper_ids(req.paper_ids or [])
    if not ids:
        raise HTTPException(status_code=400, detail="No paper IDs provided.")
    ids_key = "|".join(ids)
    cache_key = f"citation_links:{hashlib.sha1(ids_key.encode('utf-8')).hexdigest()}"
    cached = storage.get_ai_cache(cache_key, max_age_seconds=12 * 3600)
    if cached:
        try:
            payload = json.loads(cached)
            payload["cached"] = True
            return payload
        except Exception:
            pass

    papers = storage.get_papers_by_ids(ids)
    paper_map = {p.get("id"): p for p in papers if p.get("id")}
    nodes = []
    for pid in ids:
        p = paper_map.get(pid) or {}
        nodes.append({
            "id": pid,
            "label": p.get("title") or pid,
            "year": (p.get("published") or "")[:4],
        })

    links = citation_service.get_direct_links(ids)
    payload = {
        "nodes": nodes,
        "edges": links.get("edges", []),
        "missing": links.get("missing", []),
        "cached": False,
    }
    storage.set_ai_cache(cache_key, json.dumps({k: payload[k] for k in ["nodes", "edges", "missing"]}))
    return payload

@app.get("/api/lineage")
def get_method_lineage(topic: str, max_nodes: int = 20):
    return _compute_method_lineage(topic=topic, max_nodes=max_nodes)

@app.get("/api/papers/{paper_id:path}/rabbithole")
async def get_rabbit_hole(paper_id: str):
    """Fetches citation/reference graph for a specific paper."""
    print(f"DEBUG: Rabbit Hole for {paper_id}")
    # Normalize ID if needed, similar to chat endpoint
    # Actually citation_service handles the stripping.
    # But if it's a URL, we pass it as is.
    data = citation_service.get_paper_graph(paper_id)
    return data

@app.post("/api/chat")
async def chat_with_paper(req: ChatRequest):
    paper_id = normalize_paper_id(req.paper_id)
    paper = storage.get_paper_by_id(paper_id)
    if not paper:
        # Fallback if we already store this id in short format.
        paper = storage.get_paper_by_id(req.paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id}")

    pdf_path = find_local_pdf_path(paper['id'])

    # Auto-download if missing.
    if not pdf_path:
        print(f"Auto-downloading PDF for {paper['id']}...")
        try:
            downloader.download_pdf(paper['id'])
            pdf_path = find_local_pdf_path(paper['id'])
            if not pdf_path:
                return JSONResponse(content={"response": "Failed to download PDF. Please try again later."})
        except Exception as e:
            print(f"Download failed: {e}")
            return JSONResponse(content={"response": f"Error downloading PDF: {str(e)}"})

    text = extract_text_from_pdf(pdf_path)
    
    if req.image:
        # Vision Chat Mode
        # We use the image + query. Text context is optional but helpful?
        # Use query_ollama directly.
        response_text = ai_service.query_ollama(req.query, text, images=[req.image])
        if not response_text:
             response_text = "I couldn't analyze the image. Please ensure 'llava' model is installed."
        return {"response": response_text}
        
    response = simple_chat_logic(text, req.query)
    
    return {"response": response}

@app.get("/api/papers/{paper_id:path}/images")
def get_paper_images(paper_id: str):
    """Extracts images from the paper's PDF."""
    normalized_id = normalize_paper_id(paper_id)
    paper = storage.get_paper_by_id(normalized_id) or storage.get_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found.")

    pdf_path = find_local_pdf_path(paper['id'])
    if not pdf_path:
        try:
            downloader.download_pdf(paper['id'])
            pdf_path = find_local_pdf_path(paper['id'])
        except Exception as e:
            print(f"Image fetch auto-download failed: {e}")

    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found.")
        
    images = pdf_service.extract_images_from_pdf(pdf_path)
    return images


@app.get("/api/version-updates")
def get_version_updates(
    since: Optional[str] = None,
    scope: str = "watchlist",
    limit: int = 100,
    include_triaged: bool = False,
):
    storage.init_db()
    return _build_version_updates_payload(
        since=since,
        scope=scope,
        limit=limit,
        include_triaged=bool(include_triaged),
    )


@app.get("/api/version-updates/count")
def get_version_updates_count(
    since: Optional[str] = None,
    scope: str = "watchlist",
):
    storage.init_db()
    payload = _build_version_updates_payload(
        since=since,
        scope=scope,
        limit=300,
        include_triaged=False,
        count_only=True,
    )
    return {
        "scope": payload.get("scope"),
        "since": payload.get("since"),
        "active": int(payload.get("active_count") or payload.get("count") or 0),
        "triaged": int(payload.get("triaged_count") or 0),
        "total": int(payload.get("total_count") or 0),
    }


@app.post("/api/version-updates/action")
def apply_version_update_action(req: VersionUpdateActionRequest):
    storage.init_db()
    return _apply_version_update_action_internal(
        action=req.action,
        arxiv_base_id=req.arxiv_base_id or "",
        paper_id=req.paper_id,
        snooze_days=req.snooze_days,
        note=req.note,
    )

@app.get("/api/inbox/unified")
def get_unified_inbox(
    limit: int = 60,
    version_scope: str = "watchlist",
    version_days: int = 30,
    kinds: Optional[str] = None,
    sort: str = "recent",
):
    storage.init_db()
    kind_list = _parse_inbox_kind_list(kinds)
    return _build_unified_inbox_payload(
        limit=limit,
        version_scope=version_scope,
        version_days=version_days,
        kinds=kind_list,
        include_items=True,
        sort_by=sort,
    )

@app.get("/api/inbox/focus")
def get_unified_inbox_focus(
    limit: int = 12,
    version_scope: str = "watchlist",
    version_days: int = 30,
    kinds: Optional[str] = None,
):
    storage.init_db()
    focus_limit = max(1, min(int(limit or 12), 80))
    kind_list = _parse_inbox_kind_list(kinds)
    seed_limit = max(30, min(200, focus_limit * 6))
    payload = _build_unified_inbox_payload(
        limit=seed_limit,
        version_scope=version_scope,
        version_days=version_days,
        kinds=kind_list,
        include_items=True,
        sort_by="priority",
    )
    items = list(payload.get("items") or [])[:focus_limit]
    payload["items"] = items
    payload["count"] = len(items)
    payload["focus_limit"] = focus_limit
    payload["mode"] = "focus"
    return payload


@app.get("/api/inbox/count")
def get_unified_inbox_count(
    version_scope: str = "watchlist",
    version_days: int = 30,
    kinds: Optional[str] = None,
):
    storage.init_db()
    kind_list = _parse_inbox_kind_list(kinds)
    payload = _build_unified_inbox_payload(
        limit=1,
        version_scope=version_scope,
        version_days=version_days,
        kinds=kind_list,
        include_items=False,
    )
    return {
        "total": int(payload.get("total") or 0),
        "counts": payload.get("counts") or {},
        "version_scope": payload.get("version_scope"),
        "version_since": payload.get("version_since"),
        "kinds": payload.get("kinds") or kind_list,
    }


@app.post("/api/inbox/action")
def apply_unified_inbox_action(req: InboxActionRequest):
    storage.init_db()
    return _apply_inbox_action_internal(req)

@app.post("/api/inbox/bulk-action")
def apply_unified_inbox_bulk_action(req: InboxBulkActionRequest):
    storage.init_db()
    items = list(req.items or [])
    if not items:
        raise HTTPException(status_code=400, detail="items is required")
    if len(items) > 500:
        raise HTTPException(status_code=400, detail="items max length is 500")

    shared_action = str(req.action or "").strip().lower() or None
    shared_snooze = max(1, min(int(req.snooze_days or 3), 90))
    shared_note = req.note
    success_count = 0
    failure_count = 0
    results: List[Dict[str, Any]] = []

    for item in items:
        kind = _normalize_inbox_kind(item.kind)
        action = str(item.action or shared_action or _default_inbox_action_for_kind(kind)).strip().lower()
        snooze_days = max(1, min(int(item.snooze_days or shared_snooze), 90))
        try:
            payload = InboxActionRequest(
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
            result = _apply_inbox_action_internal(payload)
            success_count += 1
            results.append({"success": True, "kind": kind, "action": action, "result": result})
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
            results.append({"success": False, "kind": kind, "action": action, "status_code": 500, "error": str(e)})

    return {
        "success_count": success_count,
        "failure_count": failure_count,
        "total": len(items),
        "results": results,
    }

@app.get("/api/papers/{paper_id:path}/versions")
def get_paper_versions(paper_id: str):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    family = _get_version_family_for_paper(paper)
    items = []
    for p in family:
        items.append(
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "summary": p.get("summary"),
                "published": p.get("published"),
                "arxiv_base_id": p.get("arxiv_base_id"),
                "arxiv_version": _paper_version_number(p),
                "citation_count": int(p.get("citation_count") or 0),
                "has_structure": bool(p.get("structure")),
            }
        )
    return {
        "paper_id": paper.get("id"),
        "arxiv_base_id": paper.get("arxiv_base_id") or _split_arxiv_version(paper.get("id"))[0],
        "count": len(items),
        "versions": items,
    }


@app.get("/api/papers/{paper_id:path}/diff")
def get_paper_version_diff(paper_id: str, v_from: Optional[int] = None, v_to: Optional[int] = None):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    family = _get_version_family_for_paper(paper)
    latest_by_version: Dict[int, Dict[str, Any]] = {}
    for p in family:
        version = _paper_version_number(p)
        existing = latest_by_version.get(version)
        if not existing or _version_sort_key(p) > _version_sort_key(existing):
            latest_by_version[version] = p

    available_versions = sorted(latest_by_version.keys())
    if len(available_versions) < 2:
        raise HTTPException(status_code=400, detail="No prior version available for diff.")

    to_version = int(v_to) if v_to is not None else max(available_versions)
    if to_version not in latest_by_version:
        raise HTTPException(status_code=400, detail=f"Version v{to_version} not found.")

    if v_from is None:
        prior = [v for v in available_versions if v < to_version]
        if not prior:
            raise HTTPException(status_code=400, detail=f"No version earlier than v{to_version}.")
        from_version = max(prior)
    else:
        from_version = int(v_from)
        if from_version not in latest_by_version:
            raise HTTPException(status_code=400, detail=f"Version v{from_version} not found.")

    if from_version == to_version:
        raise HTTPException(status_code=400, detail="v_from and v_to must differ.")

    from_paper = latest_by_version[from_version]
    to_paper = latest_by_version[to_version]
    structures = _ensure_structures_for_papers([from_paper, to_paper], refresh=False)
    from_structure = structures.get(from_paper.get("id") or "", from_paper.get("structure") or {})
    to_structure = structures.get(to_paper.get("id") or "", to_paper.get("structure") or {})
    if not isinstance(from_structure, dict):
        from_structure = {}
    if not isinstance(to_structure, dict):
        to_structure = {}

    fields = ["problem", "method", "dataset", "results", "limitations"]
    structure_changes: Dict[str, Dict[str, Any]] = {}
    for field in fields:
        before = str(from_structure.get(field) or "").strip()
        after = str(to_structure.get(field) or "").strip()
        structure_changes[field] = {
            "from": before,
            "to": after,
            "changed": before != after,
        }

    title_diff = _unified_text_diff(from_paper.get("title"), to_paper.get("title"), f"v{from_version}", f"v{to_version}")
    summary_diff = _unified_text_diff(
        from_paper.get("summary"),
        to_paper.get("summary"),
        f"v{from_version}",
        f"v{to_version}",
    )
    return {
        "paper_id": to_paper.get("id"),
        "arxiv_base_id": to_paper.get("arxiv_base_id") or _split_arxiv_version(to_paper.get("id"))[0],
        "from_version": from_version,
        "to_version": to_version,
        "available_versions": available_versions,
        "from": {
            "id": from_paper.get("id"),
            "title": from_paper.get("title"),
            "published": from_paper.get("published"),
        },
        "to": {
            "id": to_paper.get("id"),
            "title": to_paper.get("title"),
            "published": to_paper.get("published"),
        },
        "title_changed": str(from_paper.get("title") or "") != str(to_paper.get("title") or ""),
        "summary_changed": str(from_paper.get("summary") or "") != str(to_paper.get("summary") or ""),
        "title_diff": title_diff,
        "summary_diff": summary_diff,
        "structure_changes": structure_changes,
        "changed_structure_fields": [name for name, meta in structure_changes.items() if bool(meta.get("changed"))],
    }

@app.get("/api/papers/{paper_id:path}/structure")
def get_paper_structure(paper_id: str, refresh: bool = False):
    """Returns structured summary fields for a paper card."""
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if paper.get("structure") and not refresh:
        return {"paper_id": paper["id"], "structure": paper.get("structure"), "cached": True}

    structure_map = _ensure_structures_for_papers([paper], refresh=bool(refresh))
    structure = structure_map.get(paper.get("id")) or {}
    return {"paper_id": paper["id"], "structure": structure, "cached": False}


@app.post("/api/papers/{paper_id:path}/structure/refresh")
def refresh_paper_structure(paper_id: str):
    storage.init_db()
    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    structure_map = _ensure_structures_for_papers([paper], refresh=True)
    structure = structure_map.get(paper.get("id")) or {}
    return {"paper_id": paper.get("id"), "structure": structure, "cached": False, "refreshed": True}

@app.get("/api/papers/{paper_id:path}/reproducibility")
def get_reproducibility_scorecard(paper_id: str):
    storage.init_db()
    return _compute_reproducibility_scorecard(paper_id)

@app.get("/api/papers/{paper_id:path}/pdf")
def get_paper_pdf(paper_id: str):
    """Serves a local PDF copy when available; otherwise redirects to arXiv PDF URL."""
    normalized_id = normalize_paper_id(paper_id)
    paper = storage.get_paper_by_id(normalized_id) or storage.get_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found.")

    pdf_path = find_local_pdf_path(paper['id'])
    if not pdf_path:
        try:
            downloader.download_pdf(paper['id'])
            pdf_path = find_local_pdf_path(paper['id'])
        except Exception as e:
            print(f"PDF download failed for {paper['id']}: {e}")

    if pdf_path and os.path.exists(pdf_path):
        return FileResponse(pdf_path, media_type="application/pdf", filename=os.path.basename(pdf_path))

    pdf_url = paper.get("pdf_url")
    if pdf_url:
        return RedirectResponse(url=pdf_url)
    raise HTTPException(status_code=404, detail="PDF not available.")

@app.get("/api/alerts")
def get_alerts(limit: int = 100, unseen_only: bool = False):
    storage.init_db()
    settings = storage.get_alert_settings()
    effective_limit = min(limit, int(settings.get("max_results", 100)))
    return storage.get_alerts(limit=effective_limit, unseen_only=unseen_only)

@app.get("/api/alerts/count")
def get_alert_count():
    storage.init_db()
    return {"unseen": storage.count_unseen_alerts()}

@app.post("/api/alerts/mark-seen")
def mark_alerts_seen(req: MarkAlertsRequest):
    storage.init_db()
    storage.mark_alerts_seen(req.ids)
    return {"success": True}

@app.get("/api/alerts/settings")
def get_alert_settings():
    storage.init_db()
    return storage.get_alert_settings()

@app.post("/api/alerts/settings")
def set_alert_settings(req: AlertSettingsRequest):
    storage.init_db()
    payload = {
        "citation_threshold": max(0, int(req.citation_threshold)),
        "max_results": max(10, int(req.max_results)),
    }
    storage.set_alert_settings(payload)
    return {"success": True, "settings": storage.get_alert_settings()}

@app.post("/api/alerts/run")
def run_alert_scan():
    storage.init_db()
    papers = storage.get_papers_by_status("new")
    created = generate_alerts_for_papers(papers)
    return {"created": created, "unseen": storage.count_unseen_alerts()}


@app.post("/api/brief")
async def get_morning_brief():
    """Generates a morning brief (summary of top 5 unread/new papers)."""
    storage.init_db()
    
    # Get top 50 unread papers to filter from
    # Re-using get_papers_by_status
    all_papers = storage.get_papers_by_status('new')
    # Sort by published date descending
    all_papers.sort(key=lambda x: x['published'], reverse=True)
    papers = all_papers[:50] # Give AI service a pool of 50 candidates
    
    if not papers:
        # Fallback to liked if no new
        all_liked = storage.get_papers_by_status('liked')
        all_liked.sort(key=lambda x: x['published'], reverse=True)
        papers = all_liked[:20]
        
    # Cache by day + paper signature to keep the brief stable during the day.
    signature_src = "|".join(
        f"{p.get('id','')}::{p.get('published','')}" for p in papers[:50]
    )
    cache_key = f"brief:{datetime.now().date().isoformat()}:{hashlib.sha1(signature_src.encode('utf-8')).hexdigest()}"
    cached = storage.get_ai_cache(cache_key, max_age_seconds=6 * 3600)
    if cached:
        return {"brief": cached, "cached": True}

    brief = generate_brief(papers, config.KEYWORDS)
    storage.set_ai_cache(cache_key, brief)
    return {"brief": brief, "cached": False}

from . import audio_service

class PodcastRequest(BaseModel):
    text: str # This is usually title/summary/content mix
    paper_data: Optional[Dict] = None # Full paper data for scripting
    style: Optional[str] = "monologue" # 'monologue' or 'conversation'

class ExportRequest(BaseModel):
    paper_id: str
    chat_history: Optional[str] = None
    notes: Optional[str] = None

class BundleExportRequest(BaseModel):
    paper_ids: List[str]
    include_brief: bool = True
    include_benchmarks: bool = True

class SynthesizeRequest(BaseModel):
    paper_ids: List[str]

class AgentRequest(BaseModel):
    topic: str
    max_depth: Optional[int] = 2

class ChatLibraryRequest(BaseModel):
    query: str

@app.post("/api/podcast")
async def get_podcast(req: PodcastRequest):
    """Generates and serves audio file using local Mac TTS."""
    
    if req.style == "conversation" and req.paper_data:
        # Generate script first
        script = ai_service.generate_podcast_script(req.paper_data)
        if script:
            audio_path = audio_service.generate_conversation_audio(script)
            if audio_path and os.path.exists(audio_path):
                 return FileResponse(audio_path, media_type="audio/wav")
        # Fallback if script or audio generation fails
        print("Fallback to monologue...")

    # Strip markdown for better speech
    clean_text = req.text.replace('#', '').replace('*', '').replace('-', '')
    
    # Returns path to file now
    audio_path = audio_service.stream_speech(clean_text)
    
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(status_code=500, detail="Failed to generate audio.")
        
    return FileResponse(audio_path, media_type="audio/mp4")

@app.post("/api/export")
def api_export(req: ExportRequest):
    """Exports paper to Obsidian/Markdown."""
    storage.init_db()
    start_ts = time.perf_counter()
    
    # 1. Get paper details
    # Attempt to handle potential short ID or full url if needed
    paper_id = req.paper_id
    if not paper_id.startswith("http"):
        # Assuming URL ID is stored, construct it or try search
        paper_id = f"http://arxiv.org/abs/{paper_id}"

    paper = storage.get_paper_by_id(paper_id)
    if not paper:
        _log_request_timing("request.export", start_ts, status="error", error="paper_not_found", paper_id=paper_id)
        raise HTTPException(status_code=404, detail="Paper not found")
        
    # 2. Get Vault Path
    vault_path = config.VAULT_PATH
    if not vault_path:
        _log_request_timing("request.export", start_ts, status="error", error="vault_not_configured", paper_id=paper_id)
        raise HTTPException(status_code=400, detail="Vault path not configured. Check settings.")
         
    # 3. Export
    try:
        path = export_service.export_paper_to_markdown(paper, vault_path, req.chat_history, req.notes)
        _log_request_timing(
            "request.export",
            start_ts,
            status="ok",
            paper_id=paper.get("id"),
        )
        return {"success": True, "path": path}
    except Exception as e:
        print(f"Export Error: {e}")
        _log_request_timing("request.export", start_ts, status="error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

def _paper_markdown_preview(paper: Dict[str, Any]) -> str:
    title = paper.get("title", "Untitled")
    authors = paper.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    authors_str = ", ".join(authors)
    published = str(paper.get("published") or "")[:10]
    summary = paper.get("summary") or "No summary available."
    pdf_url = paper.get("pdf_url") or ""
    return (
        f"# {title}\n\n"
        f"**Authors:** {authors_str}\n\n"
        f"**Published:** {published}\n\n"
        f"**PDF:** {pdf_url}\n\n"
        f"## Summary\n{summary}\n"
    )

def _benchmarks_to_markdown(payload: Dict[str, Any]) -> str:
    if not payload:
        return "No benchmark data available.\n"
    columns = payload.get("columns") or []
    rows = payload.get("rows") or []
    if not columns or not rows:
        return "No benchmark data available.\n"
    headers = ["Dataset", "Metric"] + [c.get("title") or c.get("id") for c in columns]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        values = []
        values.append(str(row.get("dataset") or ""))
        values.append(str(row.get("metric") or ""))
        row_values = row.get("values") or {}
        for c in columns:
            values.append(str(row_values.get(c.get("id"), "n/a")))
        lines.append("| " + " | ".join(values) + " |")
    notes = payload.get("notes") or []
    if notes:
        lines.append("\n## Notes\n" + "\n".join(f"- {n}" for n in notes))
    return "\n".join(lines) + "\n"

def _export_history_status(record: Dict[str, Any]) -> str:
    expires_at = record.get("expires_at")
    expired = False
    if expires_at:
        dt = _parse_iso_datetime(expires_at)
        if dt and dt < datetime.now():
            expired = True
    path = record.get("path")
    if not path or not os.path.exists(path):
        return "expired" if expired else "missing"
    return "expired" if expired else "available"

@app.post("/api/export/bundle")
def export_bundle(req: BundleExportRequest):
    storage.init_db()
    start_ts = time.perf_counter()
    paper_ids = normalize_paper_ids(req.paper_ids or [])
    if not paper_ids:
        _log_request_timing("request.export_bundle", start_ts, status="error", error="no_papers")
        raise HTTPException(status_code=400, detail="No papers selected.")

    cache_source = json.dumps(
        {
            "paper_ids": sorted(paper_ids),
            "include_brief": bool(req.include_brief),
            "include_benchmarks": bool(req.include_benchmarks),
        },
        sort_keys=True,
    )
    cache_key = hashlib.sha1(cache_source.encode("utf-8")).hexdigest()
    cached = _bundle_cache_get(cache_key)
    if cached:
        token = cached.get("token") or str(uuid.uuid4())
        filename = cached.get("filename") or f"arxiv_bundle_{datetime.now().strftime('%Y-%m-%d')}.zip"
        path = cached.get("path")
        if token not in DOWNLOAD_TOKENS:
            DOWNLOAD_TOKENS[token] = {
                "path": path,
                "media_type": "application/zip",
                "filename": filename,
            }
        created_at_ts = cached.get("created_at_ts")
        if created_at_ts is None:
            created_at_ts = datetime.now().timestamp()
        expires_at = datetime.fromtimestamp(created_at_ts + BUNDLE_CACHE_TTL_SEC).isoformat()
        size_bytes = cached.get("size_bytes")
        if (size_bytes is None or int(size_bytes) == 0) and path and os.path.exists(path):
            try:
                size_bytes = os.path.getsize(path)
            except Exception:
                size_bytes = 0
        storage.add_export_history(
            kind="bundle",
            cache_key=cache_key,
            token=token,
            filename=filename,
            path=path,
            size_bytes=size_bytes or 0,
            expires_at=expires_at,
            meta={
                "paper_count": len(paper_ids),
                "include_brief": bool(req.include_brief),
                "include_benchmarks": bool(req.include_benchmarks),
                "cached": True,
            },
        )
        _log_request_timing(
            "request.export_bundle",
            start_ts,
            status="ok",
            cached=True,
            paper_count=len(paper_ids),
        )
        return {"token": token, "filename": filename, "cached": True}

    papers = storage.get_papers_by_ids(paper_ids)
    if not papers:
        _log_request_timing("request.export_bundle", start_ts, status="error", error="papers_not_found")
        raise HTTPException(status_code=404, detail="Papers not found.")
    ordered = _order_papers_for_ids(papers, paper_ids)
    if ordered:
        papers = ordered

    manifest: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "paper_count": len(papers),
        "includes": {
            "brief": bool(req.include_brief),
            "benchmarks": bool(req.include_benchmarks),
        },
    }

    brief_text = ""
    if req.include_brief:
        try:
            brief_text = generate_brief(papers, config.KEYWORDS)
        except Exception as e:
            brief_text = ""
            manifest["brief_error"] = str(e)

    benchmarks_payload: Dict[str, Any] = {}
    if req.include_benchmarks and len(papers) >= 2:
        try:
            benchmarks_payload = _compute_benchmark_table([p.get("id") for p in papers if p.get("id")])
        except Exception as e:
            benchmarks_payload = {}
            manifest["benchmarks_error"] = str(e)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix="arxiv_bundle_") as tmp:
        bundle_path = tmp.name

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("papers.json", json.dumps(papers, indent=2))
        if brief_text:
            zf.writestr("brief.md", brief_text)
        if benchmarks_payload:
            zf.writestr("benchmarks.json", json.dumps(benchmarks_payload, indent=2))
            zf.writestr("benchmarks.md", _benchmarks_to_markdown(benchmarks_payload))
        for idx, paper in enumerate(papers, start=1):
            name = export_service.sanitize_filename(paper.get("title", f"paper-{idx}"))
            if not name:
                name = f"paper-{idx}"
            zf.writestr(f"papers/{idx:02d}-{name}.md", _paper_markdown_preview(paper))

    token = str(uuid.uuid4())
    filename = f"arxiv_bundle_{datetime.now().strftime('%Y-%m-%d')}.zip"
    DOWNLOAD_TOKENS[token] = {
        "path": bundle_path,
        "media_type": "application/zip",
        "filename": filename,
    }
    _bundle_cache_set(cache_key, token, bundle_path, filename)
    expires_at = datetime.fromtimestamp(datetime.now().timestamp() + BUNDLE_CACHE_TTL_SEC).isoformat()
    storage.add_export_history(
        kind="bundle",
        cache_key=cache_key,
        token=token,
        filename=filename,
        path=bundle_path,
        size_bytes=os.path.getsize(bundle_path) if os.path.exists(bundle_path) else 0,
        expires_at=expires_at,
        meta={
            "paper_count": len(papers),
            "include_brief": bool(req.include_brief),
            "include_benchmarks": bool(req.include_benchmarks),
            "cached": False,
        },
    )

    _log_request_timing(
        "request.export_bundle",
        start_ts,
        status="ok",
        cached=False,
        paper_count=len(papers),
    )
    return {"token": token, "filename": filename, "cached": False}

@app.get("/api/export/history")
def export_history(limit: int = 50, kind: Optional[str] = None):
    storage.init_db()
    records = storage.list_export_history(limit=limit, kind=kind)
    for rec in records:
        status = _export_history_status(rec)
        rec["status"] = status
        rec["downloadable"] = status == "available"
    return records

@app.post("/api/export/history/{export_id}/redownload")
def redownload_export(export_id: str):
    storage.init_db()
    record = storage.get_export_history(export_id)
    if not record:
        raise HTTPException(status_code=404, detail="Export history not found.")
    status = _export_history_status(record)
    if status != "available":
        raise HTTPException(status_code=410, detail="Export expired or missing.")
    token = str(uuid.uuid4())
    DOWNLOAD_TOKENS[token] = {
        "path": record.get("path"),
        "media_type": "application/zip",
        "filename": record.get("filename") or "export.zip",
    }
    storage.update_export_history(export_id, token=token)
    return {"token": token, "filename": record.get("filename"), "status": status}

@app.post("/api/backup")
def create_backup():
    storage.init_db()
    start_ts = time.perf_counter()
    db_path = os.path.abspath(storage.DB_PATH)
    if not os.path.exists(db_path):
        _log_request_timing("request.backup", start_ts, status="error", error="db_not_found")
        raise HTTPException(status_code=404, detail="Database not found.")
    config_path = os.path.abspath(config.CONFIG_FILE)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = os.path.join(tmpdir, os.path.basename(db_path))
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(tmp_db)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix="arxiv_backup_") as tmp:
            backup_zip = tmp.name

        with zipfile.ZipFile(backup_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db, arcname=os.path.basename(db_path))
            if os.path.exists(config_path):
                zf.write(config_path, arcname=os.path.basename(config_path))

    token = str(uuid.uuid4())
    filename = f"arxiv_backup_{datetime.now().strftime('%Y-%m-%d')}.zip"
    DOWNLOAD_TOKENS[token] = {
        "path": backup_zip,
        "media_type": "application/zip",
        "filename": filename,
    }
    size_bytes = os.path.getsize(backup_zip) if os.path.exists(backup_zip) else 0
    expires_at = (datetime.now() + timedelta(seconds=BACKUP_TTL_SEC)).isoformat()
    storage.add_export_history(
        kind="backup",
        token=token,
        filename=filename,
        path=backup_zip,
        size_bytes=size_bytes,
        expires_at=expires_at,
        meta={
            "db": os.path.basename(db_path),
            "config_included": os.path.exists(config_path),
        },
    )
    _log_request_timing("request.backup", start_ts, status="ok", size_bytes=size_bytes)
    return {"token": token, "filename": filename, "expires_at": expires_at, "size_bytes": size_bytes}

@app.post("/api/restore")
def restore_backup(file: UploadFile = File(...)):
    storage.init_db()
    start_ts = time.perf_counter()
    if not file:
        _log_request_timing("request.restore", start_ts, status="error", error="no_file")
        raise HTTPException(status_code=400, detail="No backup file provided.")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_zip = os.path.join(tmpdir, "restore.zip")
        with open(tmp_zip, "wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                zf.extractall(tmpdir)
        except Exception:
            _log_request_timing("request.restore", start_ts, status="error", error="invalid_zip")
            raise HTTPException(status_code=400, detail="Invalid backup archive.")

        db_path = os.path.abspath(storage.DB_PATH)
        config_path = os.path.abspath(config.CONFIG_FILE)
        db_name = os.path.basename(db_path)
        cfg_name = os.path.basename(config_path)

        restored_db = os.path.join(tmpdir, db_name)
        restored_cfg = os.path.join(tmpdir, cfg_name)
        config_in_backup = os.path.exists(restored_cfg)

        if not os.path.exists(restored_db):
            _log_request_timing("request.restore", start_ts, status="error", error="db_missing")
            raise HTTPException(status_code=400, detail="Backup is missing the database file.")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        if os.path.exists(db_path):
            shutil.copy2(db_path, f"{db_path}.bak.{timestamp}")
        if os.path.exists(config_path):
            shutil.copy2(config_path, f"{config_path}.bak.{timestamp}")

        shutil.copy2(restored_db, db_path)
        if config_in_backup:
            shutil.copy2(restored_cfg, config_path)

        for suffix in ("-wal", "-shm"):
            sidecar = f"{db_path}{suffix}"
            if os.path.exists(sidecar):
                try:
                    os.remove(sidecar)
                except Exception:
                    pass

    config.load_config()
    _bump_api_cache_epochs("papers", "search", "graph", "stats", "alerts", "digest")
    _log_request_timing("request.restore", start_ts, status="ok")
    return {"status": "ok", "restored_config": bool(config_in_backup)}

@app.post("/api/synthesize")
def synthesize_papers(req: SynthesizeRequest):
    """Generates a comparative literature review from selected papers."""
    storage.init_db()
    if len(req.paper_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 papers.")

    papers = storage.get_papers_by_ids(req.paper_ids)
    if len(papers) < 2:
        raise HTTPException(status_code=400, detail="Could not find enough selected papers.")

    try:
        review = ai_service.generate_literature_review(papers)
        return {"review": review}
    except Exception as e:
        print(f"Synthesis Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/agent/survey")
def start_survey(req: SurveyRequest, background_tasks: BackgroundTasks):
    """Starts a deep background survey job."""
    job_id = agent_service.start_survey_agent(req.topic)
    agent = agent_service.JOBS[job_id]
    # Run in background
    background_tasks.add_task(agent.run)

    return {"job_id": job_id}

class AgentStartRequest(BaseModel):
    topic: str

@app.post("/api/agent/start")
def start_research_agent(req: AgentStartRequest, background_tasks: BackgroundTasks):
    """Starts a deep research agent job."""
    job_id = agent_service.start_agent(req.topic)
    agent = agent_service.JOBS[job_id]
    background_tasks.add_task(agent.run)
    return {"job_id": job_id}

class BibtexRequest(BaseModel):
    paper_ids: List[str]

# Simple in-memory storage for download tokens
DOWNLOAD_TOKENS: Dict[str, Any] = {}
BUNDLE_CACHE_TTL_SEC = 6 * 3600
BUNDLE_CACHE_MAX_ENTRIES = 25
BUNDLE_CACHE_MAX_BYTES = 300 * 1024 * 1024
BACKUP_TTL_SEC = 24 * 3600
_BUNDLE_CACHE_LOCK = threading.Lock()
_BUNDLE_CACHE: Dict[str, Dict[str, Any]] = {}

@app.post("/api/export/bibtex")
def export_bibtex(req: BibtexRequest):
    """Generates BibTeX file for selected papers and returns a download token."""
    storage.init_db()
    start_ts = time.perf_counter()
    
    papers = storage.get_papers_by_ids(req.paper_ids)
    if not papers:
        _log_request_timing("request.export_bibtex", start_ts, status="error", error="no_valid_papers")
        raise HTTPException(status_code=400, detail="No valid papers found.")
        
    bib_content = export_service.generate_bibtex(papers)
    
    # Save to temp file
    import tempfile
    import uuid
    # Create temp file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.bib', prefix='arxiv_', encoding='utf-8') as tmp:
        tmp.write(bib_content)
        tmp_path = tmp.name
        
    # Generate Token
    token = str(uuid.uuid4())
    filename = f"arxiv_export_{datetime.now().strftime('%Y-%m-%d')}.bib"
    DOWNLOAD_TOKENS[token] = {
        "path": tmp_path,
        "media_type": "application/x-bibtex",
        "filename": filename,
    }
    
    _log_request_timing(
        "request.export_bibtex",
        start_ts,
        status="ok",
        paper_count=len(papers),
    )
    return {"token": token, "filename": filename}

def _notion_text_chunks(text: str, max_len: int = 1800) -> List[str]:
    if not text:
        return []
    chunks = []
    remaining = str(text)
    while remaining:
        chunks.append(remaining[:max_len])
        remaining = remaining[max_len:]
    return chunks

def _notion_block_paragraph(text: str) -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }

def _notion_block_heading(text: str) -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }

@app.post("/api/export/notion")
def export_notion(req: NotionExportRequest):
    storage.init_db()
    ids = normalize_paper_ids(req.paper_ids or [])
    if not ids:
        raise HTTPException(status_code=400, detail="No papers selected.")
    token = (config.NOTION_TOKEN or "").strip()
    db_id = (config.NOTION_DATABASE_ID or "").strip()
    if not token or not db_id:
        raise HTTPException(status_code=400, detail="Notion token or database ID not configured.")

    papers = storage.get_papers_by_ids(ids)
    if not papers:
        raise HTTPException(status_code=404, detail="Papers not found.")

    notes_map = storage.get_paper_notes_map([p.get("id") for p in papers if p.get("id")])
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    created = []
    failed = []
    for p in papers:
        title = str(p.get("title") or p.get("id") or "Untitled")[:200]
        summary = str(p.get("summary") or "")
        notes = notes_map.get(p.get("id") or "", "")
        authors = p.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        meta_line = f"Authors: {', '.join(authors[:8])}"
        published = (p.get("published") or "")[:10]
        if published:
            meta_line += f" • Published: {published}"
        pdf_url = p.get("pdf_url") or ""
        if pdf_url:
            meta_line += f" • PDF: {pdf_url}"

        children: List[Dict[str, Any]] = []
        children.append(_notion_block_paragraph(meta_line))
        if summary:
            children.append(_notion_block_heading("Summary"))
            for chunk in _notion_text_chunks(summary):
                children.append(_notion_block_paragraph(chunk))
        if notes:
            children.append(_notion_block_heading("Notes"))
            for chunk in _notion_text_chunks(notes):
                children.append(_notion_block_paragraph(chunk))

        payload = {
            "parent": {"database_id": db_id},
            "properties": {
                "Name": {
                    "title": [{"type": "text", "text": {"content": title}}],
                }
            },
            "children": children[:100],
        }

        try:
            resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload, timeout=15)
            if resp.status_code >= 400:
                failed.append({
                    "paper_id": p.get("id"),
                    "title": title,
                    "error": resp.text,
                })
            else:
                created.append(p.get("id"))
        except Exception as e:
            failed.append({
                "paper_id": p.get("id"),
                "title": title,
                "error": str(e),
            })
        time.sleep(0.35)

    return {"created": created, "failed": failed, "count": len(created)}

def _bundle_cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _BUNDLE_CACHE_LOCK:
        entry = _BUNDLE_CACHE.get(key)
    if not entry:
        return None
    created_at = entry.get("created_at_ts", 0.0)
    if (datetime.now().timestamp() - created_at) > BUNDLE_CACHE_TTL_SEC:
        _bundle_cache_drop(key, entry, remove_file=True)
        return None
    path = entry.get("path")
    if not path or not os.path.exists(path):
        _bundle_cache_drop(key, entry, remove_file=False)
        return None
    return entry

def _bundle_cache_drop(key: str, entry: Dict[str, Any], remove_file: bool = True) -> None:
    with _BUNDLE_CACHE_LOCK:
        _BUNDLE_CACHE.pop(key, None)
    storage.delete_bundle_cache_entry(key)
    token = entry.get("token")
    if token:
        DOWNLOAD_TOKENS.pop(token, None)
    path = entry.get("path")
    if remove_file and path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass

def _bundle_cache_prune() -> None:
    now_ts = datetime.now().timestamp()
    with _BUNDLE_CACHE_LOCK:
        items = list(_BUNDLE_CACHE.items())

    valid_entries = []
    total_bytes = 0
    for key, entry in items:
        created_at = entry.get("created_at_ts", 0.0)
        if (now_ts - created_at) > BUNDLE_CACHE_TTL_SEC:
            _bundle_cache_drop(key, entry, remove_file=True)
            continue
        path = entry.get("path")
        if not path or not os.path.exists(path):
            _bundle_cache_drop(key, entry, remove_file=False)
            continue
        size_bytes = entry.get("size_bytes")
        if size_bytes is None:
            try:
                size_bytes = os.path.getsize(path)
            except Exception:
                size_bytes = 0
            entry["size_bytes"] = size_bytes
        total_bytes += int(size_bytes or 0)
        valid_entries.append((created_at, key, entry, int(size_bytes or 0)))

    if not valid_entries:
        return

    valid_entries.sort(key=lambda row: row[0])  # oldest first
    while len(valid_entries) > BUNDLE_CACHE_MAX_ENTRIES or total_bytes > BUNDLE_CACHE_MAX_BYTES:
        created_at, key, entry, size_bytes = valid_entries.pop(0)
        total_bytes = max(0, total_bytes - int(size_bytes or 0))
        _bundle_cache_drop(key, entry, remove_file=True)

def _bundle_cache_set(key: str, token: str, path: str, filename: str):
    size_bytes = 0
    if path and os.path.exists(path):
        try:
            size_bytes = os.path.getsize(path)
        except Exception:
            size_bytes = 0
    created_at_ts = datetime.now().timestamp()
    with _BUNDLE_CACHE_LOCK:
        _BUNDLE_CACHE[key] = {
            "token": token,
            "path": path,
            "filename": filename,
            "size_bytes": size_bytes,
            "created_at_ts": created_at_ts,
        }
    storage.upsert_bundle_cache_entry(
        cache_key=key,
        token=token,
        path=path,
        filename=filename,
        size_bytes=size_bytes,
        created_at_ts=created_at_ts,
    )
    _bundle_cache_prune()

def _load_bundle_cache_from_storage() -> None:
    try:
        entries = storage.list_bundle_cache_entries(limit=500)
    except Exception:
        entries = []
    now_ts = datetime.now().timestamp()
    for entry in entries:
        key = entry.get("cache_key")
        token = entry.get("token")
        path = entry.get("path")
        filename = entry.get("filename")
        size_bytes = entry.get("size_bytes") or 0
        created_at = entry.get("created_at")
        created_dt = _parse_iso_datetime(created_at)
        created_at_ts = created_dt.timestamp() if created_dt else now_ts
        if (now_ts - created_at_ts) > BUNDLE_CACHE_TTL_SEC:
            storage.delete_bundle_cache_entry(key)
            continue
        if not path or not os.path.exists(path):
            storage.delete_bundle_cache_entry(key)
            continue
        with _BUNDLE_CACHE_LOCK:
            _BUNDLE_CACHE[key] = {
                "token": token,
                "path": path,
                "filename": filename,
                "size_bytes": size_bytes,
                "created_at_ts": created_at_ts,
            }
        if token:
            DOWNLOAD_TOKENS[token] = {
                "path": path,
                "media_type": "application/zip",
                "filename": filename,
            }
    _bundle_cache_prune()

@app.get("/api/download/{token}")
def download_file(token: str):
    """Serves a file associated with a token."""
    if token not in DOWNLOAD_TOKENS:
        raise HTTPException(status_code=404, detail="Download link expired or invalid.")
        
    entry = DOWNLOAD_TOKENS[token]
    if isinstance(entry, dict):
        file_path = entry.get("path")
        media_type = entry.get("media_type")
        filename = entry.get("filename")
    else:
        file_path = entry
        media_type = None
        filename = None
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found.")
        
    # We could delete after download, but simple GET might get retried. 
    # Let's keep it for the session or until restart.

    return FileResponse(
        file_path,
        media_type=media_type or 'application/octet-stream',
        filename=filename or "export.bin",
    )


@app.post("/api/chat/library")
def chat_library(req: ChatLibraryRequest):
    """
    Answers a question using the entire library context (RAG).
    """
    storage.init_db()
    try:
        answer = ai_service.chat_with_library(req.query)
        return {"response": answer}
    except Exception as e:
        print(f"Library Chat Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Smart Folders API
class FolderRequest(BaseModel):
    name: str
    query: str
    mode: str = "sql"
    description: Optional[str] = None
    goal: Optional[str] = None
    target_count: int = 0
    status: str = "active"

class FolderUpdateRequest(BaseModel):
    name: Optional[str] = None
    query: Optional[str] = None
    mode: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[str] = None
    target_count: Optional[int] = None
    status: Optional[str] = None

@app.get("/api/folders")
def list_folders():
    storage.init_db()
    return storage.get_folders()

@app.post("/api/folders")
def create_folder(req: FolderRequest):
    storage.init_db()
    fid = storage.create_folder(
        req.name,
        req.query,
        req.mode,
        description=req.description,
        goal=req.goal,
        target_count=req.target_count,
        status=req.status,
    )
    return {"id": fid}

@app.put("/api/folders/{id}")
def update_folder_endpoint(id: str, req: FolderUpdateRequest):
    storage.init_db()
    folder = storage.get_folder(id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    updates: Dict[str, Any] = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.query is not None:
        updates["query"] = req.query
    if req.mode is not None:
        updates["mode"] = req.mode
    if req.description is not None:
        updates["description"] = req.description
    if req.goal is not None:
        updates["goal"] = req.goal
    if req.target_count is not None:
        updates["target_count"] = req.target_count
    if req.status is not None:
        updates["status"] = req.status
    updated = storage.update_folder(id, updates)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update folder")
    return {"folder": updated}

@app.delete("/api/folders/{id}")
def delete_folder_endpoint(id: str):
    storage.init_db()
    storage.delete_folder(id)
    return {"status": "ok"}

@app.post("/api/folders/{id}/share")
def share_folder(id: str):
    storage.init_db()
    folder = storage.get_folder(id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    token = storage.create_share_token("collection", str(id), ttl_days=SHARE_TOKEN_TTL_DAYS)
    return {"token": token}

@app.get("/api/folders/{id}/schedule")
def get_folder_schedule(id: str):
    storage.init_db()
    folder = storage.get_folder(id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    schedule = storage.get_folder_digest_schedule(id)
    return {"schedule": schedule}

@app.post("/api/folders/{id}/schedule")
def set_folder_schedule(id: str, req: FolderScheduleRequest):
    storage.init_db()
    folder = storage.get_folder(id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    schedule = storage.set_folder_digest_schedule(
        id,
        cadence=req.cadence,
        max_items=req.max_items,
        enabled=req.enabled,
    )
    return {"schedule": schedule}

@app.delete("/api/folders/{id}/schedule")
def delete_folder_schedule(id: str):
    storage.init_db()
    folder = storage.get_folder(id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    ok = storage.delete_folder_digest_schedule(id)
    return {"ok": ok}

@app.post("/api/folders/{id}/digest")
def run_folder_digest(id: str, req: Optional[FolderDigestRunRequest] = None):
    storage.init_db()
    folder = storage.get_folder(id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    schedule = storage.get_folder_digest_schedule(id) or {}
    cadence = (req.cadence if req else None) or schedule.get("cadence") or "daily"
    max_items = (req.max_items if req else None) or schedule.get("max_items") or 10
    digest = _generate_folder_digest_run(folder, cadence=cadence, max_items=int(max_items), persist=True)
    if schedule:
        storage.update_folder_digest_last_run(id, datetime.now().isoformat())
    return {"digest": digest}

@app.get("/api/folders/{id}/papers")
def get_folder_papers(id: str, request: Request):
    storage.init_db()
    folder = storage.get_folder(id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    cache_key = f"folder:{id}:papers"
    etag = _etag_for_cache_key(cache_key, "papers")
    inm = request.headers.get("if-none-match")
    if _etag_matches(inm, etag) and _client_cache_warm(request):
        return Response(status_code=304, headers={"ETag": etag})
    payload = _get_folder_papers(folder, limit=50, include_private=True)
    return JSONResponse(content=payload, headers={"ETag": etag})

def _get_folder_papers(folder: Dict[str, Any], limit: int = 50, include_private: bool = True) -> List[Dict[str, Any]]:
    if not folder:
        return []
    if folder.get('mode') != 'sql':
        return []

    query = folder.get('query', '')
    if not query:
        return []
    search_results = storage.search_papers(query, limit=limit)
    ids = [r['id'] for r in search_results]
    if not ids:
        return []

    papers = storage.get_papers_by_ids(ids)
    snippet_map = {r['id']: r['snippet'] for r in search_results}
    paper_map = {p['id']: p for p in papers}
    ordered = []
    for pid in ids:
        p = paper_map.get(pid)
        if not p:
            continue
        if pid in snippet_map:
            p['search_snippet'] = snippet_map[pid]
        ordered.append(p)

    ordered = _attach_version_metadata(ordered, dedupe_latest=False)
    _attach_version_notes(ordered)
    _attach_version_change_fields(ordered)
    _attach_match_reasons(ordered)
    if include_private:
        _attach_reading_meta(ordered)
    return ordered

@app.post("/api/agent/research")
def start_research_agent(req: AgentRequest, background_tasks: BackgroundTasks):
    """Starts a Deep Research Agent job."""
    job_id = agent_service.start_agent(req.topic)
    agent = agent_service.JOBS[job_id]
    
    # Run in a separate thread to avoid blocking the asyncio loop
    # Since agent.run is now synchronous and blocking
    import threading
    t = threading.Thread(target=agent.run)
    t.start()
    
    return {"job_id": job_id, "status": "started"}

@app.get("/api/agent/{job_id}")
def get_agent_status(job_id: str):
    """Polls the status of an agent."""
    if job_id not in agent_service.JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
        
    agent = agent_service.JOBS[job_id]
    return {
        "id": agent.id,
        "status": agent.status,
        "logs": agent.logs, # Return full logs for now
        "result": agent.result,
        "papers_found": len(agent.findings)
    }

@app.get("/health")
def health():
    db_status = storage.db_healthcheck()
    embedding_status = storage.get_embedding_status()
    fts_status = storage.get_fts_status()
    with _JOB_LOCK:
        jobs = list(_JOBS.values())
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
            "queue_size": _JOB_QUEUE.qsize(),
        },
        "fetch_pipeline": {
            "active": bool(_FETCH_PIPELINE_ACTIVE),
            "tasks": int(_FETCH_PIPELINE_TASKS or 0),
            "started_at": _FETCH_PIPELINE_STARTED_AT,
        },
    }
    return payload

@app.get("/api/changes")
def get_change_summary(since: Optional[str] = None):
    storage.init_db()
    now = datetime.now()
    since_dt = _parse_iso_datetime(since) if since else None
    if not since_dt:
        since_dt = now - timedelta(days=1)
    payload = storage.get_changes_since(since_dt.isoformat())
    payload["since"] = since_dt.isoformat()
    payload["as_of"] = now.isoformat()
    return payload

@app.post("/api/discover")
def discover_new_papers():
    return _run_discover_pipeline()

@app.post("/api/compare")
def compare_papers_endpoint(req: CompareRequest):
    """Battle Mode: Compares exactly 2 papers."""
    if len(req.paper_ids) != 2:
        raise HTTPException(status_code=400, detail="Must select exactly 2 papers for Battle Mode.")
        
    storage.init_db()
    papers = storage.get_papers_by_ids(req.paper_ids)
    
    if len(papers) != 2:
         raise HTTPException(status_code=400, detail="Could not find both papers.")
         
    try:
        comparison = ai_service.compare_papers(papers)
        return {"result": comparison}
    except Exception as e:
        print(f"Comparison Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cross-paper-qa")
def cross_paper_qa_endpoint(req: CrossPaperQARequest):
    try:
        return _run_cross_paper_qa(
            paper_ids=req.paper_ids,
            question=req.question,
            top_k=req.top_k,
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Cross Paper QA Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/related-graph")
def related_graph_endpoint(req: RelatedGraphRequest):
    storage.init_db()
    normalized_ids = normalize_paper_ids(req.paper_ids or [])
    if len(normalized_ids) < 1:
        raise HTTPException(status_code=400, detail="Select at least 1 paper.")
    graph = storage.build_related_graph(
        normalized_ids,
        limit_per_anchor=max(1, min(int(req.limit_per_anchor or 8), 20)),
        min_score=max(0.0, min(float(req.min_score or 0.68), 1.0)),
    )
    graph["anchors"] = normalized_ids
    graph["anchor_count"] = len(normalized_ids)
    graph["node_count"] = len(graph.get("nodes") or [])
    graph["edge_count"] = len(graph.get("edges") or [])
    return graph

@app.post("/api/compare/matrix")
def compare_matrix_endpoint(req: CompareRequest):
    try:
        return _compute_compare_matrix(req.paper_ids)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Compare Matrix Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/compare/diff")
def compare_diff_endpoint(req: CompareRequest):
    try:
        return _compute_compare_diff(req.paper_ids)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Compare Diff Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/benchmarks/extract")
def benchmark_extract_endpoint(req: CompareRequest):
    try:
        return _compute_benchmark_table(req.paper_ids)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Benchmark Extract Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/galaxy")
def get_galaxy_map():
    """
    Returns 2D coordinates for all papers using PCA.
    """
    import numpy as np
    try:
        from sklearn.decomposition import PCA
    except ImportError:
        raise HTTPException(status_code=500, detail="scikit-learn not installed.")
        
    data = storage.get_all_embeddings()
    if not data or len(data) < 3:
        return {"nodes": []}
        
    # Prepare Matrix
    vectors = np.array([d['vector'] for d in data])
    
    # Run PCA
    # We only need 2 components
    pca = PCA(n_components=2)
    coords = pca.fit_transform(vectors)
    
    # Prepare Response
    nodes = []
    for i, item in enumerate(data):
        nodes.append({
            "id": item['id'],
            "title": item['title'],
            "x": float(coords[i][0]),
            "y": float(coords[i][1]),
            "category": item['category'].split()[0] if item['category'] else 'unknown'
        })
        
    return {"nodes": nodes}

class BatchTagRequest(BaseModel):
    paper_ids: List[str]
    concepts: Optional[List[str]] = None
    mode: str = "merge"
    use_ai: bool = False

class TagRequest(BaseModel):
    paper_id: str

def _resolve_paper_by_id(paper_id: str) -> Optional[Dict[str, Any]]:
    if not paper_id:
        return None
    candidate_ids = []
    if paper_id.startswith("http"):
        candidate_ids.append(paper_id)
    else:
        candidate_ids.append(f"http://arxiv.org/abs/{paper_id}")
        candidate_ids.append(paper_id)
    papers = storage.get_papers_by_ids(candidate_ids)
    return papers[0] if papers else None

@app.post("/api/tag")
async def tag_paper(req: TagRequest):
    """Auto-tags a specific paper with concepts."""
    storage.init_db()
    
    paper_id = req.paper_id

    paper = _resolve_paper_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
        
    concepts = ai_service.extract_concepts(paper)
    
    if concepts:
        storage.update_paper_concepts(paper['id'], concepts)
        
    return {"id": paper['id'], "concepts": concepts}

@app.post("/api/tag/batch")
async def tag_papers_batch(req: BatchTagRequest):
    """Batch tag multiple papers (manual or AI concepts)."""
    storage.init_db()
    paper_ids = [pid for pid in (req.paper_ids or []) if pid]
    if not paper_ids:
        raise HTTPException(status_code=400, detail="No paper IDs provided.")

    use_ai = bool(req.use_ai) or not req.concepts
    concepts_input = [str(c).strip() for c in (req.concepts or []) if str(c).strip()]
    mode = (req.mode or "merge").lower()
    if mode not in {"merge", "replace"}:
        mode = "merge"

    updated = 0
    concepts_map: Dict[str, Any] = {}

    for pid in paper_ids:
        paper = _resolve_paper_by_id(pid)
        if not paper:
            continue

        if use_ai:
            concepts = ai_service.extract_concepts(paper)
        else:
            if mode == "replace":
                concepts = concepts_input
            else:
                existing = paper.get("concepts") or []
                merged = list(dict.fromkeys([*existing, *concepts_input]))
                concepts = merged

        if concepts is None:
            continue

        storage.update_paper_concepts(paper["id"], concepts)
        concepts_map[paper["id"]] = concepts
        updated += 1

    return {"updated": updated, "concepts": concepts_map}

@app.get("/api/concepts/graph")
def get_concept_network():
    """Returns the co-occurrence graph of concepts."""
    storage.init_db()
    return storage.get_concept_graph()

# Serve frontend
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
