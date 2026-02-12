import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import numpy as np
import io
import threading
import os
import re
from . import config

DB_PATH = "arxiv_data.db"
SHARE_TOKEN_DEFAULT_TTL_DAYS = 30
NOTES_HISTORY_LIMIT = 20

_DB_INITIALIZED_PATH: Optional[str] = None
_DB_INITIALIZED_SIGNATURE: Optional[tuple[int, int]] = None

def _connect():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-20000")
        conn.execute("PRAGMA temp_store=MEMORY")
    except Exception:
        pass
    return conn

# In-memory semantic index cache to avoid loading all vectors on every query.
_EMBEDDING_CACHE_LOCK = threading.Lock()
_EMBEDDING_CACHE_SIGNATURE = None
_EMBEDDING_CACHE_IDS: List[str] = []
_EMBEDDING_CACHE_MATRIX = None
_EMBEDDING_CACHE_ID_TO_INDEX: Dict[str, int] = {}

def _chunked(values: List[Any], size: int):
    for i in range(0, len(values), size):
        yield values[i:i + size]

def _serialize_list_field(value: Any) -> str:
    if value is None:
        return json.dumps([])
    if isinstance(value, list):
        return json.dumps(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return json.dumps(parsed)
        except Exception:
            pass
        return json.dumps([value])
    return json.dumps([str(value)])

def _compute_match_score(title: str, summary: str, keywords: List[str]) -> int:
    if not keywords:
        return 0
    text = f"{title or ''} {summary or ''}".lower()
    return sum(1 for kw in keywords if kw and kw in text)


def _split_arxiv_version(paper_id: str) -> tuple[str, int]:
    """Splits a paper id into (base_id, version)."""
    pid = str(paper_id or "").strip()
    if not pid:
        return "", 0

    is_url = pid.startswith("http")
    segment = pid.split("/")[-1]
    base_pid = pid
    version = 1
    match = re.search(r"(v(\d+))$", segment)
    if match:
        version = int(match.group(2))
        base_segment = segment[: -len(match.group(1))]
        if is_url:
            base_pid = pid[: -len(segment)] + base_segment
        else:
            base_pid = base_segment
    return base_pid, max(1, int(version or 1))

def _invalidate_embedding_cache():
    global _EMBEDDING_CACHE_SIGNATURE, _EMBEDDING_CACHE_IDS, _EMBEDDING_CACHE_MATRIX, _EMBEDDING_CACHE_ID_TO_INDEX
    with _EMBEDDING_CACHE_LOCK:
        _EMBEDDING_CACHE_SIGNATURE = None
        _EMBEDDING_CACHE_IDS = []
        _EMBEDDING_CACHE_MATRIX = None
        _EMBEDDING_CACHE_ID_TO_INDEX = {}

def _load_embedding_matrix():
    """
    Loads embedding ids/matrix from DB and caches them until the embedding table changes.
    Cache key: (COUNT(*), MAX(updated_at)).
    """
    global _EMBEDDING_CACHE_SIGNATURE, _EMBEDDING_CACHE_IDS, _EMBEDDING_CACHE_MATRIX, _EMBEDDING_CACHE_ID_TO_INDEX

    conn = _connect()
    c = conn.cursor()

    c.execute("SELECT COUNT(*), COALESCE(MAX(updated_at), '') FROM paper_embeddings")
    signature_row = c.fetchone()
    signature = (signature_row[0], signature_row[1]) if signature_row else (0, "")

    with _EMBEDDING_CACHE_LOCK:
        if signature == _EMBEDDING_CACHE_SIGNATURE and _EMBEDDING_CACHE_MATRIX is not None:
            conn.close()
            return _EMBEDDING_CACHE_IDS, _EMBEDDING_CACHE_MATRIX, _EMBEDDING_CACHE_ID_TO_INDEX

    c.execute("SELECT paper_id, embedding FROM paper_embeddings")
    rows = c.fetchall()
    conn.close()

    if not rows:
        with _EMBEDDING_CACHE_LOCK:
            _EMBEDDING_CACHE_SIGNATURE = signature
            _EMBEDDING_CACHE_IDS = []
            _EMBEDDING_CACHE_MATRIX = np.array([])
            _EMBEDDING_CACHE_ID_TO_INDEX = {}
        return [], np.array([]), {}

    ids = []
    vectors = []
    expected_dim = None

    for paper_id, blob in rows:
        vec = np.frombuffer(blob, dtype=np.float32)
        if vec.size == 0:
            continue
        if expected_dim is None:
            expected_dim = vec.size
        if vec.size != expected_dim:
            continue
        ids.append(paper_id)
        vectors.append(vec)

    matrix = np.vstack(vectors) if vectors else np.array([])

    with _EMBEDDING_CACHE_LOCK:
        _EMBEDDING_CACHE_SIGNATURE = signature
        _EMBEDDING_CACHE_IDS = ids
        _EMBEDDING_CACHE_MATRIX = matrix
        _EMBEDDING_CACHE_ID_TO_INDEX = {pid: idx for idx, pid in enumerate(ids)}

    return ids, matrix, _EMBEDDING_CACHE_ID_TO_INDEX

def _deserialize_paper_dict(p: Dict[str, Any]) -> Dict[str, Any]:
    """Normalizes serialized JSON fields in a paper row dict."""
    if p.get('categories') and isinstance(p['categories'], str):
        try:
            p['categories'] = json.loads(p['categories'])
        except Exception:
            p['categories'] = p['categories'].split(',')

    if p.get('authors') and isinstance(p['authors'], str):
        try:
            p['authors'] = json.loads(p['authors'])
        except Exception:
            p['authors'] = [p['authors']]

    if p.get('concepts') and isinstance(p['concepts'], str):
        try:
            p['concepts'] = json.loads(p['concepts'])
        except Exception:
            p['concepts'] = []

    if p.get('structure') and isinstance(p['structure'], str):
        try:
            p['structure'] = json.loads(p['structure'])
        except Exception:
            p['structure'] = None

    return p

def init_db():
    """Initializes the SQLite database."""
    global _DB_INITIALIZED_PATH, _DB_INITIALIZED_SIGNATURE
    db_path_abs = os.path.abspath(DB_PATH)
    current_sig = None
    try:
        st = os.stat(DB_PATH)
        current_sig = (int(st.st_mtime_ns), int(st.st_size))
    except Exception:
        current_sig = None

    if _DB_INITIALIZED_PATH == db_path_abs and _DB_INITIALIZED_SIGNATURE == current_sig:
        return

    conn = _connect()
    c = conn.cursor()
    
    # Table to store papers
    c.execute('''
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            summary TEXT,
            authors TEXT,
            published TEXT,
            pdf_url TEXT,
            categories TEXT,
            fetched_at TEXT,
            citation_count INTEGER DEFAULT 0,
            match_score INTEGER DEFAULT 0,
            novelty_score REAL,
            ranker_score REAL,
            arxiv_base_id TEXT,
            arxiv_version INTEGER DEFAULT 1
        )
    ''')
    
    # Migration: Add citation_count if missing
    try:
        c.execute("ALTER TABLE papers ADD COLUMN citation_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Already exists
    # Migration: Add citation_updated_at if missing
    try:
        c.execute("ALTER TABLE papers ADD COLUMN citation_updated_at TEXT")
    except sqlite3.OperationalError:
        pass # Already exists
        
    # Migration: Add concepts if missing
    try:
        c.execute("ALTER TABLE papers ADD COLUMN concepts TEXT")
    except sqlite3.OperationalError:
        pass # Already exists
    # Migration: Add structure if missing
    try:
        c.execute("ALTER TABLE papers ADD COLUMN structure TEXT")
    except sqlite3.OperationalError:
        pass # Already exists

    # Migration: Add match_score if missing
    try:
        c.execute("ALTER TABLE papers ADD COLUMN match_score INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Already exists

    # Migration: Add novelty_score if missing
    try:
        c.execute("ALTER TABLE papers ADD COLUMN novelty_score REAL")
    except sqlite3.OperationalError:
        pass # Already exists
    # Migration: Add ranker_score if missing
    try:
        c.execute("ALTER TABLE papers ADD COLUMN ranker_score REAL")
    except sqlite3.OperationalError:
        pass # Already exists
    # Migration: Add version-normalized columns for fast version grouping
    try:
        c.execute("ALTER TABLE papers ADD COLUMN arxiv_base_id TEXT")
    except sqlite3.OperationalError:
        pass # Already exists
    try:
        c.execute("ALTER TABLE papers ADD COLUMN arxiv_version INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass # Already exists
    
    # Table to store interactions (e.g., likes, dismissals)
    # status: 'new', 'liked', 'dismissed', 'read'
    c.execute('''
        CREATE TABLE IF NOT EXISTS interactions (
            paper_id TEXT PRIMARY KEY,
            status TEXT,
            updated_at TEXT,
            FOREIGN KEY(paper_id) REFERENCES papers(id)
        )
    ''')

    # Table to store followed authors
    c.execute('''
        CREATE TABLE IF NOT EXISTS follows (
            name TEXT PRIMARY KEY,
            created_at TEXT
        )
    ''')

    # Table to store bookmarks
    c.execute('''
        CREATE TABLE IF NOT EXISTS bookmarks (
            paper_id TEXT PRIMARY KEY,
            created_at TEXT
        )
    ''')

    # Table to store vector embeddings (blob)
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_embeddings (
            paper_id TEXT PRIMARY KEY,
            embedding BLOB,
            updated_at TEXT,
            FOREIGN KEY(paper_id) REFERENCES papers(id)
        )
    ''')

    # Reading status tracking
    c.execute('''
        CREATE TABLE IF NOT EXISTS reading_status (
            paper_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            progress INTEGER DEFAULT 0,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(paper_id) REFERENCES papers(id)
        )
    ''')

    # Paper notes
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_notes (
            paper_id TEXT PRIMARY KEY,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(paper_id) REFERENCES papers(id)
        )
    ''')

    # Notes history (last N versions)
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_notes_history (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            notes TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(paper_id) REFERENCES papers(id)
        )
    ''')

    # Team comments / mentions
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_comments (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            author TEXT NOT NULL,
            body TEXT NOT NULL,
            mentions TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(paper_id) REFERENCES papers(id)
        )
    ''')

    # Comment mentions inbox
    c.execute('''
        CREATE TABLE IF NOT EXISTS comment_mentions (
            id TEXT PRIMARY KEY,
            mention TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            comment_id TEXT NOT NULL,
            author TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(paper_id) REFERENCES papers(id),
            FOREIGN KEY(comment_id) REFERENCES paper_comments(id)
        )
    ''')

    # Virtual table for Full Text Search
    try:
        c.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5(paper_id, content)
        ''')
    except:
        c.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts4(paper_id, content)
        ''')
    
    # Table for Smart Folders
    c.execute('''
        CREATE TABLE IF NOT EXISTS smart_folders (
            id TEXT PRIMARY KEY,
            name TEXT,
            query TEXT,
            mode TEXT,
            created_at TEXT
        )
    ''')

    # Collection digest schedules (per smart folder)
    c.execute('''
        CREATE TABLE IF NOT EXISTS collection_digest_schedules (
            folder_id TEXT PRIMARY KEY,
            cadence TEXT NOT NULL DEFAULT 'daily',
            max_items INTEGER DEFAULT 10,
            enabled INTEGER DEFAULT 1,
            last_run_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(folder_id) REFERENCES smart_folders(id)
        )
    ''')

    # Smart alerts storage
    c.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            seen INTEGER DEFAULT 0,
            UNIQUE(paper_id, alert_type)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS alert_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS saved_search_agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            query TEXT NOT NULL,
            cadence TEXT NOT NULL DEFAULT 'daily',
            max_results INTEGER DEFAULT 8,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_run_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS saved_search_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER NOT NULL,
            summary TEXT NOT NULL,
            matches_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(agent_id) REFERENCES saved_search_agents(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS saved_search_seen (
            agent_id INTEGER NOT NULL,
            paper_id TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            PRIMARY KEY(agent_id, paper_id),
            FOREIGN KEY(agent_id) REFERENCES saved_search_agents(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS ai_cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS digest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cadence TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            paper_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    ''')
    # Migration: add optional source fields to digest_runs
    try:
        c.execute("ALTER TABLE digest_runs ADD COLUMN source_type TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE digest_runs ADD COLUMN source_id TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE digest_runs ADD COLUMN source_name TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute('''
        CREATE TABLE IF NOT EXISTS digest_items (
            digest_id INTEGER NOT NULL,
            item_rank INTEGER NOT NULL,
            paper_id TEXT NOT NULL,
            title TEXT NOT NULL,
            reason TEXT NOT NULL,
            score REAL DEFAULT 0,
            PRIMARY KEY(digest_id, paper_id),
            FOREIGN KEY(digest_id) REFERENCES digest_runs(id)
        )
    ''')
    # Migration: add digest contributor metadata
    try:
        c.execute("ALTER TABLE digest_items ADD COLUMN contributors TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute('''
        CREATE TABLE IF NOT EXISTS digest_reads (
            digest_id INTEGER PRIMARY KEY,
            read_at TEXT NOT NULL,
            FOREIGN KEY(digest_id) REFERENCES digest_runs(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS share_tokens (
            token TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            payload_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT
        )
    ''')
    # Migration: Add expires_at if missing
    try:
        c.execute("ALTER TABLE share_tokens ADD COLUMN expires_at TEXT")
    except sqlite3.OperationalError:
        pass # Already exists
    c.execute('''
        CREATE TABLE IF NOT EXISTS scheduler_locks (
            name TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_fetch_runs (
            date TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            fetched INTEGER DEFAULT 0,
            new_count INTEGER DEFAULT 0,
            reason TEXT,
            forced INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS bundle_cache (
            cache_key TEXT PRIMARY KEY,
            token TEXT NOT NULL,
            path TEXT NOT NULL,
            filename TEXT NOT NULL,
            size_bytes INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS inbox_rules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            action TEXT NOT NULL,
            label TEXT,
            keywords TEXT,
            authors TEXT,
            venues TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    # Migration: inbox rules v2 fields
    try:
        c.execute("ALTER TABLE inbox_rules ADD COLUMN scope TEXT DEFAULT 'papers'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE inbox_rules ADD COLUMN target_kind TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE inbox_rules ADD COLUMN snooze_days INTEGER DEFAULT 3")
    except sqlite3.OperationalError:
        pass
    c.execute('''
        CREATE TABLE IF NOT EXISTS inbox_rule_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id TEXT,
            scope TEXT,
            target_kind TEXT,
            action TEXT,
            item_ref TEXT,
            item_kind TEXT,
            result TEXT,
            meta_json TEXT,
            created_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS day_run_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            status TEXT NOT NULL,
            options_json TEXT,
            summary TEXT,
            payload_json TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS day_run_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            options_json TEXT NOT NULL,
            run_count INTEGER DEFAULT 0,
            last_used_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_labels (
            paper_id TEXT NOT NULL,
            label TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (paper_id, label, source)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS pinned_papers (
            paper_id TEXT PRIMARY KEY,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    # Migration: add optional pin expiry
    try:
        c.execute("ALTER TABLE pinned_papers ADD COLUMN expires_at TEXT")
    except sqlite3.OperationalError:
        pass

    # Paper follow-ups
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_followups (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            remind_at TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            done_at TEXT,
            FOREIGN KEY(paper_id) REFERENCES papers(id)
        )
    ''')

    # Cross-paper links
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_links (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            related_id TEXT NOT NULL,
            relation TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(paper_id) REFERENCES papers(id),
            FOREIGN KEY(related_id) REFERENCES papers(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_reading_time (
            paper_id TEXT PRIMARY KEY,
            page_count INTEGER DEFAULT 0,
            minutes INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS reading_plan_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_date TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            options_json TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS reading_plan_deferred (
            paper_id TEXT PRIMARY KEY,
            defer_until TEXT NOT NULL,
            reason TEXT,
            updated_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS reading_plan_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_date TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            action TEXT NOT NULL,
            minutes INTEGER DEFAULT 0,
            meta_json TEXT,
            created_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS version_update_states (
            arxiv_base_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            snooze_until TEXT,
            note TEXT,
            updated_at TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS export_history (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            cache_key TEXT,
            token TEXT,
            path TEXT,
            filename TEXT NOT NULL,
            size_bytes INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            meta TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS job_queue (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            result TEXT,
            error TEXT,
            cancel_requested INTEGER DEFAULT 0,
            cancel_requested_at TEXT
        )
    ''')

    # Query hot paths
    c.execute("CREATE INDEX IF NOT EXISTS idx_interactions_status_updated ON interactions(status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_papers_fetched_at ON papers(fetched_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_papers_base_version ON papers(arxiv_base_id, arxiv_version DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_interactions_paper_id ON interactions(paper_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_created_at ON bookmarks(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_seen_created ON alerts(seen, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_saved_search_agents_updated ON saved_search_agents(updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_saved_search_runs_agent_created ON saved_search_runs(agent_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_saved_search_seen_paper ON saved_search_seen(paper_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_collection_digest_schedules_updated ON collection_digest_schedules(updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_collection_digest_schedules_enabled ON collection_digest_schedules(enabled)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_cache_updated ON ai_cache(updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_digest_runs_cadence_created ON digest_runs(cadence, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_digest_items_digest_rank ON digest_items(digest_id, item_rank)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_digest_reads_read_at ON digest_reads(read_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_share_tokens_created ON share_tokens(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_share_tokens_expires ON share_tokens(expires_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_scheduler_locks_heartbeat ON scheduler_locks(heartbeat_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_job_queue_status_updated ON job_queue(status, updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_job_queue_created ON job_queue(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_daily_fetch_runs_created ON daily_fetch_runs(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bundle_cache_created ON bundle_cache(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_export_history_created ON export_history(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_export_history_kind ON export_history(kind)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_export_history_expires ON export_history(expires_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inbox_rules_updated ON inbox_rules(updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inbox_rules_scope_enabled ON inbox_rules(scope, enabled)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inbox_rules_target_kind ON inbox_rules(target_kind)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inbox_rule_audit_created ON inbox_rule_audit(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inbox_rule_audit_rule ON inbox_rule_audit(rule_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_day_run_history_requested ON day_run_history(requested_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_day_run_history_date ON day_run_history(run_date DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_day_run_presets_updated ON day_run_presets(updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_day_run_presets_name ON day_run_presets(name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_paper_labels_paper ON paper_labels(paper_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pinned_papers_updated ON pinned_papers(updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pinned_papers_expires ON pinned_papers(expires_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_paper_reading_time_updated ON paper_reading_time(updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_reading_status_updated ON reading_status(updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_reading_plan_snapshots_date_created ON reading_plan_snapshots(plan_date, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_reading_plan_snapshots_created ON reading_plan_snapshots(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_reading_plan_deferred_until ON reading_plan_deferred(defer_until)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_reading_plan_activity_date_created ON reading_plan_activity(plan_date, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_reading_plan_activity_paper_created ON reading_plan_activity(paper_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_version_update_states_status_snooze ON version_update_states(status, snooze_until)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_version_update_states_updated ON version_update_states(updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_paper_notes_updated ON paper_notes(updated_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_paper_notes_history_paper ON paper_notes_history(paper_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_paper_comments_paper ON paper_comments(paper_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_comment_mentions_handle_created ON comment_mentions(mention, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_followups_due ON paper_followups(done_at, remind_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_paper_links_paper ON paper_links(paper_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_paper_links_related ON paper_links(related_id, created_at DESC)")

    # Backfill version-normalized columns for existing rows.
    try:
        c.execute(
            '''
            SELECT id
            FROM papers
            WHERE arxiv_base_id IS NULL
               OR arxiv_base_id = ''
               OR arxiv_version IS NULL
               OR arxiv_version <= 0
            '''
        )
        pending = [r[0] for r in c.fetchall() if r and r[0]]
        if pending:
            updates = []
            for pid in pending:
                base_id, version = _split_arxiv_version(pid)
                updates.append((base_id, int(version or 1), pid))
            c.executemany(
                "UPDATE papers SET arxiv_base_id = ?, arxiv_version = ? WHERE id = ?",
                updates,
            )
    except Exception:
        pass

    conn.commit()
    conn.close()
    _DB_INITIALIZED_PATH = db_path_abs
    try:
        st = os.stat(DB_PATH)
        _DB_INITIALIZED_SIGNATURE = (int(st.st_mtime_ns), int(st.st_size))
    except Exception:
        _DB_INITIALIZED_SIGNATURE = None

def create_folder(name: str, query: str, mode: str = 'sql') -> str:
    conn = _connect()
    c = conn.cursor()
    import uuid
    folder_id = str(uuid.uuid4())
    c.execute("INSERT INTO smart_folders (id, name, query, mode, created_at) VALUES (?, ?, ?, ?, ?)",
              (folder_id, name, query, mode, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return folder_id

def get_folders() -> List[Dict]:
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, name, query, mode, created_at FROM smart_folders ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [{
        "id": r[0], "name": r[1], "query": r[2], "mode": r[3], "created_at": r[4]
    } for r in rows]

def delete_folder(folder_id: str):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM smart_folders WHERE id = ?", (folder_id,))
    c.execute("DELETE FROM collection_digest_schedules WHERE folder_id = ?", (folder_id,))
    conn.commit()
    conn.close()

def get_folder(folder_id: str) -> Dict:
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, name, query, mode FROM smart_folders WHERE id = ?", (folder_id,))
    r = c.fetchone()
    conn.close()
    if r:
        return {"id": r[0], "name": r[1], "query": r[2], "mode": r[3]}
    return None

def get_folder_digest_schedule(folder_id: str) -> Optional[Dict[str, Any]]:
    if not folder_id:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT folder_id, cadence, max_items, enabled, last_run_at, created_at, updated_at
        FROM collection_digest_schedules
        WHERE folder_id = ?
        ''',
        (folder_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def list_folder_digest_schedules(enabled_only: bool = False) -> List[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if enabled_only:
        c.execute(
            '''
            SELECT folder_id, cadence, max_items, enabled, last_run_at, created_at, updated_at
            FROM collection_digest_schedules
            WHERE enabled = 1
            ORDER BY updated_at DESC
            '''
        )
    else:
        c.execute(
            '''
            SELECT folder_id, cadence, max_items, enabled, last_run_at, created_at, updated_at
            FROM collection_digest_schedules
            ORDER BY updated_at DESC
            '''
        )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def set_folder_digest_schedule(folder_id: str, cadence: str, max_items: int = 10, enabled: bool = True) -> Dict[str, Any]:
    if not folder_id:
        return {}
    cadence = (cadence or 'daily').lower()
    if cadence not in {'daily', 'weekly'}:
        cadence = 'daily'
    max_items = max(3, min(int(max_items or 10), 30))
    enabled_value = 1 if enabled else 0
    now = datetime.now().isoformat()

    conn = _connect()
    c = conn.cursor()
    c.execute(
        "SELECT created_at FROM collection_digest_schedules WHERE folder_id = ?",
        (folder_id,),
    )
    row = c.fetchone()
    if row:
        c.execute(
            '''
            UPDATE collection_digest_schedules
            SET cadence = ?, max_items = ?, enabled = ?, updated_at = ?
            WHERE folder_id = ?
            ''',
            (cadence, max_items, enabled_value, now, folder_id),
        )
    else:
        c.execute(
            '''
            INSERT INTO collection_digest_schedules (folder_id, cadence, max_items, enabled, last_run_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (folder_id, cadence, max_items, enabled_value, None, now, now),
        )
    conn.commit()
    conn.close()
    return get_folder_digest_schedule(folder_id) or {}

def delete_folder_digest_schedule(folder_id: str) -> bool:
    if not folder_id:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM collection_digest_schedules WHERE folder_id = ?", (folder_id,))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok

def update_folder_digest_last_run(folder_id: str, run_at: Optional[str] = None) -> bool:
    if not folder_id:
        return False
    ts = run_at or datetime.now().isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        UPDATE collection_digest_schedules
        SET last_run_at = ?, updated_at = ?
        WHERE folder_id = ?
        ''',
        (ts, ts, folder_id),
    )
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok

def save_papers(papers: List[Dict[str, Any]]):
    """Saves a list of papers to the database if they don't exist."""
    if not papers:
        return 0

    # Deduplicate incoming records by id while preserving order.
    unique_papers = []
    seen_ids = set()
    for p in papers:
        pid = p.get("id")
        if not pid or pid in seen_ids:
            continue
        seen_ids.add(pid)
        unique_papers.append(p)

    if not unique_papers:
        return 0

    conn = _connect()
    c = conn.cursor()

    keywords = [k.lower() for k in config.KEYWORDS if k]
    incoming_ids = [p["id"] for p in unique_papers]
    existing_ids = set()
    for chunk in _chunked(incoming_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(f"SELECT id FROM papers WHERE id IN ({placeholders})", chunk)
        existing_ids.update(r[0] for r in c.fetchall())

    new_papers = [p for p in unique_papers if p["id"] not in existing_ids]
    if not new_papers:
        conn.close()
        return 0

    now = datetime.now().isoformat()
    paper_rows = []
    interaction_rows = []
    fts_rows: List[tuple[str, str]] = []
    for p in new_papers:
        paper_id = p["id"]
        match_score = p.get("match_score")
        if match_score is None:
            match_score = _compute_match_score(p.get("title", ""), p.get("summary", ""), keywords)
        base_id, version = _split_arxiv_version(paper_id)
        title = p.get("title", "")
        summary = p.get("summary", "")
        authors = p.get("authors") or []
        if isinstance(authors, list):
            authors_text = " ".join(str(a) for a in authors)
        else:
            authors_text = str(authors)
        categories = p.get("categories") or []
        if isinstance(categories, list):
            categories_text = " ".join(str(c) for c in categories)
        else:
            categories_text = str(categories)
        fts_rows.append((paper_id, f"{title} {summary} {authors_text} {categories_text}".strip()))
        paper_rows.append((
            paper_id,
            p.get("title", ""),
            p.get("summary", ""),
            _serialize_list_field(p.get("authors")),
            p.get("published", ""),
            p.get("pdf_url", ""),
            _serialize_list_field(p.get("categories")),
            now,
            base_id,
            int(version or 1),
            _serialize_list_field(p.get("concepts", [])),
            None,
            int(match_score or 0),
            p.get("novelty_score"),
            p.get("ranker_score"),
        ))
        interaction_rows.append((paper_id, "new", now))

    c.executemany('''
        INSERT INTO papers (
            id, title, summary, authors, published, pdf_url, categories, fetched_at,
            citation_count, arxiv_base_id, arxiv_version, concepts, structure, match_score, novelty_score, ranker_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
    ''', paper_rows)
    c.executemany(
        "INSERT OR IGNORE INTO interactions (paper_id, status, updated_at) VALUES (?, ?, ?)",
        interaction_rows,
    )

    conn.commit()
    conn.close()
    if fts_rows:
        index_papers_text(fts_rows)
    return len(new_papers)

def get_papers_by_status(status: str = 'new') -> List[Dict[str, Any]]:
    """Retrieves papers with a specific interaction status."""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('''
        SELECT p.*, i.status 
        FROM papers p
        JOIN interactions i ON p.id = i.paper_id
        WHERE i.status = ?
    ''', (status,))
    
    rows = c.fetchall()
    papers = []
    for row in rows:
        p = dict(row)
        papers.append(_deserialize_paper_dict(p))
        
    conn.close()
    return papers


def get_papers_page_by_status(
    status: str = "new",
    limit: int = 100,
    offset: int = 0,
    published_date: Optional[str] = None,
    dedupe_latest: bool = False,
) -> tuple[List[Dict[str, Any]], int]:
    """
    Returns a paged slice for a status, plus total count.
    When dedupe_latest=True, keeps only latest version per arXiv base id.
    """
    lim = max(1, min(int(limit), 500))
    off = max(0, int(offset))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    date_clause = ""
    params: List[Any] = [status]
    if published_date:
        date_clause = " AND substr(p.published, 1, 10) = ?"
        params.append(str(published_date))

    if not dedupe_latest:
        c.execute(
            f'''
            SELECT COUNT(*)
            FROM papers p
            JOIN interactions i ON p.id = i.paper_id
            WHERE i.status = ?{date_clause}
            ''',
            params,
        )
        total_row = c.fetchone()
        total = int(total_row[0]) if total_row else 0
        c.execute(
            f'''
            SELECT p.*, i.status
            FROM papers p
            JOIN interactions i ON p.id = i.paper_id
            WHERE i.status = ?{date_clause}
            ORDER BY p.published DESC
            LIMIT ? OFFSET ?
            ''',
            [*params, lim, off],
        )
        rows = c.fetchall()
        conn.close()
        out = []
        for row in rows:
            rec = dict(row)
            out.append(_deserialize_paper_dict(rec))
        return out, total

    base_expr = "COALESCE(NULLIF(p.arxiv_base_id, ''), p.id)"
    ranked_sql = f'''
        SELECT
            p.*,
            i.status,
            ROW_NUMBER() OVER (
                PARTITION BY {base_expr}
                ORDER BY COALESCE(p.arxiv_version, 1) DESC, p.published DESC
            ) AS _rn
        FROM papers p
        JOIN interactions i ON p.id = i.paper_id
        WHERE i.status = ?{date_clause}
    '''
    try:
        c.execute(f"SELECT COUNT(*) FROM ({ranked_sql}) q WHERE q._rn = 1", params)
        total_row = c.fetchone()
        total = int(total_row[0]) if total_row else 0
        c.execute(
            f'''
            SELECT *
            FROM ({ranked_sql}) q
            WHERE q._rn = 1
            ORDER BY q.published DESC
            LIMIT ? OFFSET ?
            ''',
            [*params, lim, off],
        )
        rows = c.fetchall()
        conn.close()
        out = []
        for row in rows:
            rec = dict(row)
            rec.pop("_rn", None)
            out.append(_deserialize_paper_dict(rec))
        return out, total
    except sqlite3.OperationalError:
        # Fallback for SQLite builds without window functions.
        conn.close()
        rows = get_papers_by_status(status=status)
        if published_date:
            rows = [p for p in rows if str(p.get("published", "")).startswith(str(published_date))]
        latest: Dict[str, Dict[str, Any]] = {}
        for p in rows:
            base_id = p.get("arxiv_base_id") or _split_arxiv_version(p.get("id"))[0]
            ver = int(p.get("arxiv_version") or _split_arxiv_version(p.get("id"))[1] or 1)
            existing = latest.get(base_id)
            if not existing:
                latest[base_id] = p
                continue
            existing_ver = int(existing.get("arxiv_version") or _split_arxiv_version(existing.get("id"))[1] or 1)
            if ver > existing_ver:
                latest[base_id] = p
            elif ver == existing_ver and str(p.get("published", "")) > str(existing.get("published", "")):
                latest[base_id] = p
        deduped = sorted(latest.values(), key=lambda x: x.get("published", ""), reverse=True)
        total = len(deduped)
        return deduped[off: off + lim], total

def get_bookmarked_papers_page(
    limit: int = 100,
    offset: int = 0,
    published_date: Optional[str] = None,
    dedupe_latest: bool = False,
) -> tuple[List[Dict[str, Any]], int]:
    """
    Returns a paged slice for bookmarked papers, plus total count.
    """
    lim = max(1, min(int(limit), 500))
    off = max(0, int(offset))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    date_clause = ""
    params: List[Any] = []
    if published_date:
        date_clause = " AND substr(p.published, 1, 10) = ?"
        params.append(str(published_date))

    if not dedupe_latest:
        c.execute(
            f'''
            SELECT COUNT(*)
            FROM papers p
            JOIN bookmarks b ON p.id = b.paper_id
            WHERE 1 = 1{date_clause}
            ''',
            params,
        )
        total_row = c.fetchone()
        total = int(total_row[0]) if total_row else 0
        c.execute(
            f'''
            SELECT p.*, COALESCE(i.status, 'new') AS status
            FROM papers p
            JOIN bookmarks b ON p.id = b.paper_id
            LEFT JOIN interactions i ON p.id = i.paper_id
            WHERE 1 = 1{date_clause}
            ORDER BY p.published DESC
            LIMIT ? OFFSET ?
            ''',
            [*params, lim, off],
        )
        rows = c.fetchall()
        conn.close()
        out = []
        for row in rows:
            rec = dict(row)
            out.append(_deserialize_paper_dict(rec))
        return out, total

    base_expr = "COALESCE(NULLIF(p.arxiv_base_id, ''), p.id)"
    ranked_sql = f'''
        SELECT
            p.*,
            COALESCE(i.status, 'new') AS status,
            ROW_NUMBER() OVER (
                PARTITION BY {base_expr}
                ORDER BY COALESCE(p.arxiv_version, 1) DESC, p.published DESC
            ) AS _rn
        FROM papers p
        JOIN bookmarks b ON p.id = b.paper_id
        LEFT JOIN interactions i ON p.id = i.paper_id
        WHERE 1 = 1{date_clause}
    '''
    try:
        c.execute(f"SELECT COUNT(*) FROM ({ranked_sql}) q WHERE q._rn = 1", params)
        total_row = c.fetchone()
        total = int(total_row[0]) if total_row else 0
        c.execute(
            f'''
            SELECT *
            FROM ({ranked_sql}) q
            WHERE q._rn = 1
            ORDER BY q.published DESC
            LIMIT ? OFFSET ?
            ''',
            [*params, lim, off],
        )
        rows = c.fetchall()
        conn.close()
        out = []
        for row in rows:
            rec = dict(row)
            rec.pop("_rn", None)
            out.append(_deserialize_paper_dict(rec))
        return out, total
    except sqlite3.OperationalError:
        conn.close()
        rows, _total = get_bookmarked_papers_page(
            limit=5000,
            offset=0,
            published_date=published_date,
            dedupe_latest=False,
        )
        latest: Dict[str, Dict[str, Any]] = {}
        for p in rows:
            base_id = p.get("arxiv_base_id") or _split_arxiv_version(p.get("id"))[0]
            ver = int(p.get("arxiv_version") or _split_arxiv_version(p.get("id"))[1] or 1)
            existing = latest.get(base_id)
            if not existing:
                latest[base_id] = p
                continue
            existing_ver = int(existing.get("arxiv_version") or _split_arxiv_version(existing.get("id"))[1] or 1)
            if ver > existing_ver:
                latest[base_id] = p
            elif ver == existing_ver and str(p.get("published", "")) > str(existing.get("published", "")):
                latest[base_id] = p
        deduped = sorted(latest.values(), key=lambda x: x.get("published", ""), reverse=True)
        total = len(deduped)
        return deduped[off: off + lim], total

def update_interaction(paper_id: str, status: str):
    """Updates the status of a paper."""
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''
        INSERT INTO interactions (paper_id, status, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
    ''', (paper_id, status, now))
    conn.commit()
    conn.close()

def batch_update_interactions(rows: List[tuple[str, str]]) -> int:
    if not rows:
        return 0
    now = datetime.now().isoformat()
    payload = [(str(pid), str(status), now) for pid, status in rows if pid and status]
    if not payload:
        return 0
    conn = _connect()
    c = conn.cursor()
    c.executemany(
        '''
        INSERT INTO interactions (paper_id, status, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
        ''',
        payload,
    )
    conn.commit()
    changed = int(c.rowcount or 0)
    conn.close()
    return changed

def update_citations(citation_map: Dict[str, int]):
    """Bulk-updates citation counts keyed by paper id."""
    if not citation_map:
        return
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    rows = [(count, now, paper_id) for paper_id, count in citation_map.items()]
    c.executemany(
        "UPDATE papers SET citation_count = ?, citation_updated_at = ? WHERE id = ?",
        rows,
    )
    conn.commit()
    conn.close()

def get_papers_for_citation_refresh(limit: int = 250, stale_days: int = 7) -> List[str]:
    limit = max(1, int(limit))
    stale_days = max(1, int(stale_days))
    cutoff = (datetime.now() - timedelta(days=stale_days)).isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        SELECT id FROM papers
        WHERE (citation_updated_at IS NULL OR citation_updated_at < ?)
          AND (published IS NULL OR published < ?)
        ORDER BY published DESC
        LIMIT ?
        ''',
        (cutoff, cutoff, limit),
    )
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows if r and r[0]]

def get_followed_authors() -> List[str]:
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT name FROM follows")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def follow_author(name: str):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO follows (name, created_at) VALUES (?, ?)", (name, datetime.now().isoformat()))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Already exists
    conn.close()

def unfollow_author(name: str):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM follows WHERE name = ?", (name,))
    conn.commit()
    conn.close()

def get_daily_stats():
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    # Count fetched per day
    c.execute('''
        SELECT substr(fetched_at, 1, 10) as date, count(*) as count 
        FROM papers 
        GROUP BY date 
        ORDER BY date DESC 
        LIMIT 14
    ''')
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def record_daily_fetch_run(
    date: str,
    status: str,
    fetched: int = 0,
    new_count: int = 0,
    reason: Optional[str] = None,
    forced: bool = False,
) -> None:
    if not date:
        return
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        '''
        INSERT INTO daily_fetch_runs (
            date, status, fetched, new_count, reason, forced, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            status = excluded.status,
            fetched = excluded.fetched,
            new_count = excluded.new_count,
            reason = excluded.reason,
            forced = excluded.forced,
            updated_at = excluded.updated_at
        ''',
        (
            str(date),
            str(status),
            int(fetched or 0),
            int(new_count or 0),
            reason,
            1 if forced else 0,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

def get_daily_fetch_run(date: str) -> Optional[Dict[str, Any]]:
    if not date:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT date, status, fetched, new_count, reason, forced, created_at, updated_at
        FROM daily_fetch_runs
        WHERE date = ?
        ''',
        (str(date),),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def list_daily_fetch_runs(limit: int = 30, date_from: Optional[str] = None, date_to: Optional[str] = None) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit), 365))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if date_from and date_to:
        c.execute(
            '''
            SELECT date, status, fetched, new_count, reason, forced, created_at, updated_at
            FROM daily_fetch_runs
            WHERE date BETWEEN ? AND ?
            ORDER BY date DESC
            LIMIT ?
            ''',
            (date_from, date_to, lim),
        )
    elif date_from:
        c.execute(
            '''
            SELECT date, status, fetched, new_count, reason, forced, created_at, updated_at
            FROM daily_fetch_runs
            WHERE date >= ?
            ORDER BY date DESC
            LIMIT ?
            ''',
            (date_from, lim),
        )
    elif date_to:
        c.execute(
            '''
            SELECT date, status, fetched, new_count, reason, forced, created_at, updated_at
            FROM daily_fetch_runs
            WHERE date <= ?
            ORDER BY date DESC
            LIMIT ?
            ''',
            (date_to, lim),
        )
    else:
        c.execute(
            '''
            SELECT date, status, fetched, new_count, reason, forced, created_at, updated_at
            FROM daily_fetch_runs
            ORDER BY date DESC
            LIMIT ?
            ''',
            (lim,),
        )
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def record_day_run_history(
    run_date: str,
    requested_at: Optional[str],
    status: str,
    options: Optional[Dict[str, Any]] = None,
    summary: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> int:
    if not run_date:
        run_date = datetime.now().date().isoformat()
    now = datetime.now().isoformat()
    req_at = str(requested_at or now)
    try:
        options_json = json.dumps(options or {})
    except Exception:
        options_json = json.dumps({})
    try:
        payload_json = json.dumps(payload or {})
    except Exception:
        payload_json = json.dumps({})
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO day_run_history (run_date, requested_at, status, options_json, summary, payload_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (str(run_date), req_at, str(status or "unknown"), options_json, summary or "", payload_json),
    )
    run_id = int(c.lastrowid or 0)
    c.execute(
        '''
        DELETE FROM day_run_history
        WHERE id IN (
            SELECT id FROM day_run_history
            ORDER BY requested_at DESC, id DESC
            LIMIT -1 OFFSET 1000
        )
        '''
    )
    conn.commit()
    conn.close()
    return run_id

def get_day_run_history(run_id: int) -> Optional[Dict[str, Any]]:
    if int(run_id or 0) <= 0:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, run_date, requested_at, status, options_json, summary, payload_json
        FROM day_run_history
        WHERE id = ?
        LIMIT 1
        ''',
        (int(run_id),),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    rec = dict(row)
    try:
        rec["options"] = json.loads(rec.pop("options_json") or "{}")
    except Exception:
        rec["options"] = {}
    try:
        rec["payload"] = json.loads(rec.pop("payload_json") or "{}")
    except Exception:
        rec["payload"] = {}
    return rec

def list_day_run_history(limit: int = 30) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit or 30), 300))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, run_date, requested_at, status, options_json, summary, payload_json
        FROM day_run_history
        ORDER BY requested_at DESC, id DESC
        LIMIT ?
        ''',
        (lim,),
    )
    rows = c.fetchall()
    conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        try:
            rec["options"] = json.loads(rec.pop("options_json") or "{}")
        except Exception:
            rec["options"] = {}
        try:
            payload = json.loads(rec.pop("payload_json") or "{}")
        except Exception:
            payload = {}
        rec["payload"] = payload if isinstance(payload, dict) else {}
        out.append(rec)
    return out

def _parse_day_run_preset_row(row: sqlite3.Row) -> Dict[str, Any]:
    rec = dict(row)
    try:
        parsed = json.loads(rec.pop("options_json") or "{}")
    except Exception:
        parsed = {}
    rec["options"] = parsed if isinstance(parsed, dict) else {}
    rec["run_count"] = max(0, int(rec.get("run_count") or 0))
    return rec

def list_day_run_presets(limit: int = 100) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit or 100), 500))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, name, description, options_json, run_count, last_used_at, created_at, updated_at
        FROM day_run_presets
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        ''',
        (lim,),
    )
    rows = c.fetchall()
    conn.close()
    return [_parse_day_run_preset_row(row) for row in rows]

def get_day_run_preset(preset_id: int) -> Optional[Dict[str, Any]]:
    pid = int(preset_id or 0)
    if pid <= 0:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, name, description, options_json, run_count, last_used_at, created_at, updated_at
        FROM day_run_presets
        WHERE id = ?
        LIMIT 1
        ''',
        (pid,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return _parse_day_run_preset_row(row)

def create_day_run_preset(
    name: str,
    options: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    now = datetime.now().isoformat()
    clean_name = str(name or "").strip() or "Preset"
    clean_description = (str(description or "").strip() or None)
    clean_options = options if isinstance(options, dict) else {}
    try:
        options_json = json.dumps(clean_options)
    except Exception:
        options_json = json.dumps({})
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO day_run_presets (name, description, options_json, run_count, last_used_at, created_at, updated_at)
        VALUES (?, ?, ?, 0, NULL, ?, ?)
        ''',
        (clean_name, clean_description, options_json, now, now),
    )
    preset_id = int(c.lastrowid or 0)
    conn.commit()
    conn.close()
    return get_day_run_preset(preset_id)

def update_day_run_preset(preset_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pid = int(preset_id or 0)
    if pid <= 0 or not isinstance(updates, dict):
        return None
    fields: List[str] = []
    values: List[Any] = []
    if "name" in updates:
        fields.append("name = ?")
        values.append(str(updates.get("name") or "").strip() or "Preset")
    if "description" in updates:
        clean_description = str(updates.get("description") or "").strip()
        fields.append("description = ?")
        values.append(clean_description or None)
    if "options" in updates:
        clean_options = updates.get("options") if isinstance(updates.get("options"), dict) else {}
        try:
            options_json = json.dumps(clean_options)
        except Exception:
            options_json = json.dumps({})
        fields.append("options_json = ?")
        values.append(options_json)
    if not fields:
        return get_day_run_preset(pid)
    fields.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(pid)
    conn = _connect()
    c = conn.cursor()
    c.execute(
        f"UPDATE day_run_presets SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()
    changed = int(c.rowcount or 0)
    conn.close()
    if changed <= 0:
        return None
    return get_day_run_preset(pid)

def delete_day_run_preset(preset_id: int) -> bool:
    pid = int(preset_id or 0)
    if pid <= 0:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM day_run_presets WHERE id = ?", (pid,))
    conn.commit()
    deleted = int(c.rowcount or 0) > 0
    conn.close()
    return deleted

def mark_day_run_preset_used(preset_id: int) -> Optional[Dict[str, Any]]:
    pid = int(preset_id or 0)
    if pid <= 0:
        return None
    now = datetime.now().isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        UPDATE day_run_presets
        SET run_count = COALESCE(run_count, 0) + 1,
            last_used_at = ?,
            updated_at = ?
        WHERE id = ?
        ''',
        (now, now, pid),
    )
    conn.commit()
    changed = int(c.rowcount or 0)
    conn.close()
    if changed <= 0:
        return None
    return get_day_run_preset(pid)

def upsert_bundle_cache_entry(
    cache_key: str,
    token: str,
    path: str,
    filename: str,
    size_bytes: int,
    created_at_ts: Optional[float] = None,
) -> None:
    if not cache_key or not token or not path or not filename:
        return
    created_ts = float(created_at_ts) if created_at_ts is not None else datetime.now().timestamp()
    created_at = datetime.fromtimestamp(created_ts).isoformat()
    now = datetime.now().isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO bundle_cache (cache_key, token, path, filename, size_bytes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            token = excluded.token,
            path = excluded.path,
            filename = excluded.filename,
            size_bytes = excluded.size_bytes,
            updated_at = excluded.updated_at
        ''',
        (cache_key, token, path, filename, int(size_bytes or 0), created_at, now),
    )
    conn.commit()
    conn.close()

def delete_bundle_cache_entry(cache_key: str) -> bool:
    if not cache_key:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM bundle_cache WHERE cache_key = ?", (cache_key,))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok

def list_bundle_cache_entries(limit: int = 200) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit), 1000))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT cache_key, token, path, filename, size_bytes, created_at, updated_at
        FROM bundle_cache
        ORDER BY created_at DESC
        LIMIT ?
        ''',
        (lim,),
    )
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def list_inbox_rules(enabled_only: bool = False) -> List[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if enabled_only:
        c.execute(
            '''
            SELECT id, name, enabled, action, label, keywords, authors, venues,
                   scope, target_kind, snooze_days, created_at, updated_at
            FROM inbox_rules
            WHERE enabled = 1
            ORDER BY updated_at DESC
            '''
        )
    else:
        c.execute(
            '''
            SELECT id, name, enabled, action, label, keywords, authors, venues,
                   scope, target_kind, snooze_days, created_at, updated_at
            FROM inbox_rules
            ORDER BY updated_at DESC
            '''
        )
    rows = c.fetchall()
    conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        for key in ("keywords", "authors", "venues"):
            raw = rec.get(key)
            if raw:
                try:
                    rec[key] = json.loads(raw)
                except Exception:
                    rec[key] = []
            else:
                rec[key] = []
        rec["scope"] = str(rec.get("scope") or "papers")
        rec["target_kind"] = str(rec.get("target_kind") or "").strip() or None
        rec["snooze_days"] = max(1, min(int(rec.get("snooze_days") or 3), 90))
        rec["enabled"] = bool(rec.get("enabled"))
        out.append(rec)
    return out

def add_inbox_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    import uuid
    now = datetime.now().isoformat()
    rule_id = str(uuid.uuid4())
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO inbox_rules (
            id, name, enabled, action, label, keywords, authors, venues,
            scope, target_kind, snooze_days, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            rule_id,
            str(rule.get("name") or "Rule"),
            1 if rule.get("enabled", True) else 0,
            str(rule.get("action") or "label"),
            rule.get("label"),
            json.dumps(rule.get("keywords") or []),
            json.dumps(rule.get("authors") or []),
            json.dumps(rule.get("venues") or []),
            str(rule.get("scope") or "papers"),
            (str(rule.get("target_kind") or "").strip() or None),
            max(1, min(int(rule.get("snooze_days") or 3), 90)),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {
        "id": rule_id,
        "name": str(rule.get("name") or "Rule"),
        "enabled": bool(rule.get("enabled", True)),
        "action": str(rule.get("action") or "label"),
        "label": rule.get("label"),
        "keywords": rule.get("keywords") or [],
        "authors": rule.get("authors") or [],
        "venues": rule.get("venues") or [],
        "scope": str(rule.get("scope") or "papers"),
        "target_kind": (str(rule.get("target_kind") or "").strip() or None),
        "snooze_days": max(1, min(int(rule.get("snooze_days") or 3), 90)),
        "created_at": now,
        "updated_at": now,
    }

def update_inbox_rule(rule_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not rule_id:
        return None
    fields = []
    values: List[Any] = []
    if "name" in updates:
        fields.append("name = ?")
        values.append(str(updates.get("name") or "Rule"))
    if "enabled" in updates:
        fields.append("enabled = ?")
        values.append(1 if updates.get("enabled") else 0)
    if "action" in updates:
        fields.append("action = ?")
        values.append(str(updates.get("action") or "label"))
    if "label" in updates:
        fields.append("label = ?")
        values.append(updates.get("label"))
    if "keywords" in updates:
        fields.append("keywords = ?")
        values.append(json.dumps(updates.get("keywords") or []))
    if "authors" in updates:
        fields.append("authors = ?")
        values.append(json.dumps(updates.get("authors") or []))
    if "venues" in updates:
        fields.append("venues = ?")
        values.append(json.dumps(updates.get("venues") or []))
    if "scope" in updates:
        fields.append("scope = ?")
        values.append(str(updates.get("scope") or "papers"))
    if "target_kind" in updates:
        fields.append("target_kind = ?")
        values.append(str(updates.get("target_kind") or "").strip() or None)
    if "snooze_days" in updates:
        fields.append("snooze_days = ?")
        values.append(max(1, min(int(updates.get("snooze_days") or 3), 90)))
    if not fields:
        return None
    fields.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(rule_id)
    conn = _connect()
    c = conn.cursor()
    c.execute(
        f"UPDATE inbox_rules SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()
    return {"id": rule_id, **updates}

def delete_inbox_rule(rule_id: str) -> bool:
    if not rule_id:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM inbox_rules WHERE id = ?", (rule_id,))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok

def add_inbox_rule_audit(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    payload: List[tuple[Any, ...]] = []
    for row in rows:
        try:
            meta_json = json.dumps(row.get("meta") or {})
        except Exception:
            meta_json = json.dumps({})
        payload.append(
            (
                str(row.get("rule_id") or "") or None,
                str(row.get("scope") or "") or None,
                str(row.get("target_kind") or "") or None,
                str(row.get("action") or "") or None,
                str(row.get("item_ref") or "") or None,
                str(row.get("item_kind") or "") or None,
                str(row.get("result") or "") or None,
                meta_json,
                str(row.get("created_at") or now),
            )
        )
    c.executemany(
        '''
        INSERT INTO inbox_rule_audit (
            rule_id, scope, target_kind, action, item_ref, item_kind, result, meta_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        payload,
    )
    inserted = int(c.rowcount or 0)
    c.execute(
        '''
        DELETE FROM inbox_rule_audit
        WHERE id IN (
            SELECT id FROM inbox_rule_audit
            ORDER BY created_at DESC, id DESC
            LIMIT -1 OFFSET 5000
        )
        '''
    )
    conn.commit()
    conn.close()
    return inserted

def list_inbox_rule_audit(limit: int = 200, rule_id: Optional[str] = None) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit or 200), 1000))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if rule_id:
        c.execute(
            '''
            SELECT id, rule_id, scope, target_kind, action, item_ref, item_kind, result, meta_json, created_at
            FROM inbox_rule_audit
            WHERE rule_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            ''',
            (str(rule_id), lim),
        )
    else:
        c.execute(
            '''
            SELECT id, rule_id, scope, target_kind, action, item_ref, item_kind, result, meta_json, created_at
            FROM inbox_rule_audit
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            ''',
            (lim,),
        )
    rows = c.fetchall()
    conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        try:
            rec["meta"] = json.loads(rec.pop("meta_json") or "{}")
        except Exception:
            rec["meta"] = {}
        out.append(rec)
    return out

def add_paper_labels(paper_id: str, labels: List[str], source: str = "rule") -> int:
    if not paper_id or not labels:
        return 0
    clean = [str(l).strip() for l in labels if str(l).strip()]
    if not clean:
        return 0
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    rows = [(paper_id, label, source, now) for label in clean]
    c.executemany(
        '''
        INSERT OR IGNORE INTO paper_labels (paper_id, label, source, created_at)
        VALUES (?, ?, ?, ?)
        ''',
        rows,
    )
    conn.commit()
    added = c.rowcount
    conn.close()
    return added

def add_paper_labels_bulk(rows: List[tuple[str, str, str]]) -> int:
    if not rows:
        return 0
    now = datetime.now().isoformat()
    payload = []
    for paper_id, label, source in rows:
        pid = str(paper_id or "").strip()
        lbl = str(label or "").strip()
        src = str(source or "rule").strip() or "rule"
        if not pid or not lbl:
            continue
        payload.append((pid, lbl, src, now))
    if not payload:
        return 0
    conn = _connect()
    c = conn.cursor()
    c.executemany(
        '''
        INSERT OR IGNORE INTO paper_labels (paper_id, label, source, created_at)
        VALUES (?, ?, ?, ?)
        ''',
        payload,
    )
    conn.commit()
    inserted = int(c.rowcount or 0)
    conn.close()
    return inserted

def get_paper_labels_map(paper_ids: List[str]) -> Dict[str, List[str]]:
    if not paper_ids:
        return {}
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    out: Dict[str, List[str]] = {}
    for chunk in _chunked(paper_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f'''
            SELECT paper_id, label
            FROM paper_labels
            WHERE paper_id IN ({placeholders})
            ''',
            chunk,
        )
        for row in c.fetchall():
            pid = str(row["paper_id"])
            out.setdefault(pid, []).append(row["label"])
    conn.close()
    return out

def set_pin(paper_id: str, note: Optional[str], expires_at: Optional[str] = None) -> Dict[str, Any]:
    if not paper_id:
        return {}
    now = datetime.now().isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO pinned_papers (paper_id, note, created_at, updated_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            note = excluded.note,
            updated_at = excluded.updated_at,
            expires_at = excluded.expires_at
        ''',
        (paper_id, note, now, now, expires_at),
    )
    conn.commit()
    conn.close()
    return {"paper_id": paper_id, "note": note or "", "updated_at": now, "expires_at": expires_at}

def remove_pin(paper_id: str) -> bool:
    if not paper_id:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM pinned_papers WHERE paper_id = ?", (paper_id,))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok

def get_pinned_map(paper_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not paper_ids:
        return {}
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    out: Dict[str, Dict[str, Any]] = {}
    expired_ids: List[str] = []
    now = datetime.now().isoformat()
    for chunk in _chunked(paper_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f'''
            SELECT paper_id, note, created_at, updated_at, expires_at
            FROM pinned_papers
            WHERE paper_id IN ({placeholders})
            ''',
            chunk,
        )
        for row in c.fetchall():
            rec = dict(row)
            expires_at = rec.get("expires_at") or ""
            if expires_at and expires_at < now:
                expired_ids.append(str(rec.get("paper_id")))
                continue
            out[str(rec.get("paper_id"))] = rec
    if expired_ids:
        placeholders = ",".join(["?"] * len(expired_ids))
        try:
            c.execute(f"DELETE FROM pinned_papers WHERE paper_id IN ({placeholders})", expired_ids)
            conn.commit()
        except Exception:
            pass
    conn.close()
    return out

def add_follow_up(paper_id: str, remind_at: str, note: Optional[str] = None) -> Dict[str, Any]:
    if not paper_id or not remind_at:
        return {}
    import uuid
    follow_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO paper_followups (id, paper_id, remind_at, note, created_at, done_at)
        VALUES (?, ?, ?, ?, ?, NULL)
        ''',
        (follow_id, paper_id, remind_at, (note or "").strip(), now),
    )
    conn.commit()
    conn.close()
    return {
        "id": follow_id,
        "paper_id": paper_id,
        "remind_at": remind_at,
        "note": (note or "").strip(),
        "created_at": now,
        "done_at": None,
    }

def list_follow_ups(due_only: bool = True, limit: int = 50) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit), 200))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    now = datetime.now().isoformat()
    if due_only:
        c.execute(
            '''
            SELECT f.id, f.paper_id, f.remind_at, f.note, f.created_at, f.done_at,
                   p.title, p.published
            FROM paper_followups f
            LEFT JOIN papers p ON p.id = f.paper_id
            WHERE f.done_at IS NULL AND f.remind_at <= ?
            ORDER BY f.remind_at ASC
            LIMIT ?
            ''',
            (now, lim),
        )
    else:
        c.execute(
            '''
            SELECT f.id, f.paper_id, f.remind_at, f.note, f.created_at, f.done_at,
                   p.title, p.published
            FROM paper_followups f
            LEFT JOIN papers p ON p.id = f.paper_id
            WHERE f.done_at IS NULL
            ORDER BY f.remind_at ASC
            LIMIT ?
            ''',
            (lim,),
        )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def count_follow_ups_due(now_iso: Optional[str] = None) -> int:
    now = str(now_iso or datetime.now().isoformat())
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        SELECT COUNT(*)
        FROM paper_followups
        WHERE done_at IS NULL AND remind_at <= ?
        ''',
        (now,),
    )
    row = c.fetchone()
    conn.close()
    return int(row[0] or 0) if row else 0

def mark_follow_up_done(follow_id: str) -> bool:
    if not follow_id:
        return False
    now = datetime.now().isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "UPDATE paper_followups SET done_at = ? WHERE id = ? AND done_at IS NULL",
        (now, follow_id),
    )
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok

def snooze_follow_up(follow_id: str, days: int = 3) -> Optional[Dict[str, Any]]:
    if not follow_id:
        return None
    try:
        span = max(1, min(int(days or 3), 90))
    except Exception:
        span = 3
    remind_at = (datetime.now() + timedelta(days=span)).isoformat()
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "UPDATE paper_followups SET remind_at = ? WHERE id = ? AND done_at IS NULL",
        (remind_at, follow_id),
    )
    updated = c.rowcount > 0
    if not updated:
        conn.commit()
        conn.close()
        return None
    c.execute(
        '''
        SELECT f.id, f.paper_id, f.remind_at, f.note, f.created_at, f.done_at,
               p.title, p.published
        FROM paper_followups f
        LEFT JOIN papers p ON p.id = f.paper_id
        WHERE f.id = ?
        LIMIT 1
        ''',
        (follow_id,),
    )
    row = c.fetchone()
    conn.commit()
    conn.close()
    return dict(row) if row else None

def add_paper_link(
    paper_id: str,
    related_id: str,
    relation: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    if not paper_id or not related_id or paper_id == related_id:
        return {}
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, paper_id, related_id, relation, note, created_at
        FROM paper_links
        WHERE (paper_id = ? AND related_id = ?)
           OR (paper_id = ? AND related_id = ?)
        LIMIT 1
        ''',
        (paper_id, related_id, related_id, paper_id),
    )
    row = c.fetchone()
    if row:
        conn.close()
        return dict(row)

    import uuid
    link_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    c.execute(
        '''
        INSERT INTO paper_links (id, paper_id, related_id, relation, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (link_id, paper_id, related_id, (relation or "").strip(), (note or "").strip(), now),
    )
    conn.commit()
    conn.close()
    return {
        "id": link_id,
        "paper_id": paper_id,
        "related_id": related_id,
        "relation": (relation or "").strip(),
        "note": (note or "").strip(),
        "created_at": now,
    }

def list_paper_links(paper_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    if not paper_id:
        return []
    lim = max(1, min(int(limit), 200))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, paper_id, related_id, relation, note, created_at
        FROM paper_links
        WHERE paper_id = ? OR related_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        ''',
        (paper_id, paper_id, lim),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    if not rows:
        return []
    other_ids = []
    for row in rows:
        other = row.get("related_id") if row.get("paper_id") == paper_id else row.get("paper_id")
        if other:
            other_ids.append(other)
    titles = {}
    if other_ids:
        for p in get_papers_by_ids(other_ids):
            if p and p.get("id"):
                titles[p.get("id")] = p.get("title") or p.get("id")
    for row in rows:
        other = row.get("related_id") if row.get("paper_id") == paper_id else row.get("paper_id")
        row["other_id"] = other
        row["other_title"] = titles.get(other, other or "")
    return rows

def delete_paper_link(link_id: str) -> bool:
    if not link_id:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM paper_links WHERE id = ?", (link_id,))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok

def get_interaction_status_map(paper_ids: List[str]) -> Dict[str, str]:
    if not paper_ids:
        return {}
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    out: Dict[str, str] = {}
    for chunk in _chunked(paper_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f'''
            SELECT paper_id, status
            FROM interactions
            WHERE paper_id IN ({placeholders})
            ''',
            chunk,
        )
        for row in c.fetchall():
            out[str(row["paper_id"])] = str(row["status"])
    conn.close()
    return out

def add_export_history(
    kind: str,
    filename: str,
    path: Optional[str] = None,
    size_bytes: Optional[int] = None,
    cache_key: Optional[str] = None,
    token: Optional[str] = None,
    expires_at: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not kind or not filename:
        return {}
    import uuid
    now = datetime.now().isoformat()
    export_id = str(uuid.uuid4())
    meta_json = json.dumps(meta) if meta is not None else None
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO export_history (
            id, kind, cache_key, token, path, filename, size_bytes, created_at, updated_at, expires_at, meta
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            export_id,
            kind,
            cache_key,
            token,
            path,
            filename,
            int(size_bytes or 0),
            now,
            now,
            expires_at,
            meta_json,
        ),
    )
    conn.commit()
    conn.close()
    return {
        "id": export_id,
        "kind": kind,
        "cache_key": cache_key,
        "token": token,
        "path": path,
        "filename": filename,
        "size_bytes": int(size_bytes or 0),
        "created_at": now,
        "updated_at": now,
        "expires_at": expires_at,
        "meta": meta,
    }

def update_export_history(
    export_id: str,
    *,
    token: Optional[str] = None,
    path: Optional[str] = None,
    filename: Optional[str] = None,
    size_bytes: Optional[int] = None,
    expires_at: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> bool:
    if not export_id:
        return False
    fields = []
    values: List[Any] = []
    if token is not None:
        fields.append("token = ?")
        values.append(token)
    if path is not None:
        fields.append("path = ?")
        values.append(path)
    if filename is not None:
        fields.append("filename = ?")
        values.append(filename)
    if size_bytes is not None:
        fields.append("size_bytes = ?")
        values.append(int(size_bytes or 0))
    if expires_at is not None:
        fields.append("expires_at = ?")
        values.append(expires_at)
    if meta is not None:
        fields.append("meta = ?")
        values.append(json.dumps(meta))
    if not fields:
        return False
    fields.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(export_id)
    conn = _connect()
    c = conn.cursor()
    c.execute(
        f"UPDATE export_history SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok

def get_export_history(export_id: str) -> Optional[Dict[str, Any]]:
    if not export_id:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, kind, cache_key, token, path, filename, size_bytes, created_at, updated_at, expires_at, meta
        FROM export_history
        WHERE id = ?
        ''',
        (export_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    rec = dict(row)
    meta_raw = rec.get("meta")
    if meta_raw:
        try:
            rec["meta"] = json.loads(meta_raw)
        except Exception:
            pass
    return rec

def list_export_history(limit: int = 50, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit), 500))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if kind:
        c.execute(
            '''
            SELECT id, kind, cache_key, token, path, filename, size_bytes, created_at, updated_at, expires_at, meta
            FROM export_history
            WHERE kind = ?
            ORDER BY created_at DESC
            LIMIT ?
            ''',
            (kind, lim),
        )
    else:
        c.execute(
            '''
            SELECT id, kind, cache_key, token, path, filename, size_bytes, created_at, updated_at, expires_at, meta
            FROM export_history
            ORDER BY created_at DESC
            LIMIT ?
            ''',
            (lim,),
        )
    rows = c.fetchall()
    conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        meta_raw = rec.get("meta")
        if meta_raw:
            try:
                rec["meta"] = json.loads(meta_raw)
            except Exception:
                pass
        out.append(rec)
    return out

def get_paper_by_id(paper_id: str) -> Dict[str, Any]:
    """Retrieves a single paper by its ID."""
    papers = get_papers_by_ids([paper_id])
    return papers[0] if papers else None

def get_reading_status(paper_id: str) -> Optional[Dict[str, Any]]:
    if not paper_id:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT paper_id, status, progress, started_at, finished_at, updated_at
        FROM reading_status
        WHERE paper_id = ?
        ''',
        (paper_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_reading_status_map(paper_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not paper_ids:
        return {}
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    out: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunked(paper_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f'''
            SELECT paper_id, status, progress, started_at, finished_at, updated_at
            FROM reading_status
            WHERE paper_id IN ({placeholders})
            ''',
            chunk,
        )
        for row in c.fetchall():
            rec = dict(row)
            out[str(rec.get("paper_id"))] = rec
    conn.close()
    return out

def get_reading_time(paper_id: str) -> Optional[Dict[str, Any]]:
    if not paper_id:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT paper_id, page_count, minutes, updated_at
        FROM paper_reading_time
        WHERE paper_id = ?
        ''',
        (paper_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_reading_time_map(paper_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not paper_ids:
        return {}
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    out: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunked(paper_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f'''
            SELECT paper_id, page_count, minutes, updated_at
            FROM paper_reading_time
            WHERE paper_id IN ({placeholders})
            ''',
            chunk,
        )
        for row in c.fetchall():
            rec = dict(row)
            out[str(rec.get("paper_id"))] = rec
    conn.close()
    return out

def set_reading_time(paper_id: str, page_count: int, minutes: int) -> Dict[str, Any]:
    if not paper_id:
        return {}
    try:
        page_count_val = max(0, int(page_count))
    except Exception:
        page_count_val = 0
    try:
        minutes_val = max(0, int(minutes))
    except Exception:
        minutes_val = 0
    now = datetime.now().isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO paper_reading_time (paper_id, page_count, minutes, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            page_count = excluded.page_count,
            minutes = excluded.minutes,
            updated_at = excluded.updated_at
        ''',
        (paper_id, page_count_val, minutes_val, now),
    )
    conn.commit()
    conn.close()
    return {
        "paper_id": paper_id,
        "page_count": page_count_val,
        "minutes": minutes_val,
        "updated_at": now,
    }

def set_reading_status(paper_id: str, status: str, progress: Optional[int] = None) -> Dict[str, Any]:
    if not paper_id:
        return {}
    status = (status or "queue").lower()
    if status not in {"queue", "reading", "done"}:
        status = "queue"
    try:
        progress_val = int(progress) if progress is not None else None
    except Exception:
        progress_val = None
    if progress_val is None:
        progress_val = 0
    progress_val = max(0, min(progress_val, 100))

    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT started_at, finished_at FROM reading_status WHERE paper_id = ?",
        (paper_id,),
    )
    existing = c.fetchone()
    started_at = existing["started_at"] if existing else None
    finished_at = existing["finished_at"] if existing else None
    now = datetime.now().isoformat()

    if status == "queue":
        started_at = None
        finished_at = None
        progress_val = 0
    elif status == "reading":
        if not started_at:
            started_at = now
        finished_at = None
    elif status == "done":
        if not started_at:
            started_at = now
        finished_at = now
        progress_val = 100

    c.execute(
        '''
        INSERT INTO reading_status (paper_id, status, progress, started_at, finished_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            status = excluded.status,
            progress = excluded.progress,
            started_at = excluded.started_at,
            finished_at = excluded.finished_at,
            updated_at = excluded.updated_at
        ''',
        (paper_id, status, progress_val, started_at, finished_at, now),
    )
    conn.commit()
    conn.close()
    return {
        "paper_id": paper_id,
        "status": status,
        "progress": progress_val,
        "started_at": started_at,
        "finished_at": finished_at,
        "updated_at": now,
    }


def save_reading_plan_snapshot(
    plan_date: str,
    payload: Dict[str, Any],
    options: Optional[Dict[str, Any]] = None,
    source: str = "manual",
) -> Dict[str, Any]:
    if not plan_date or not isinstance(payload, dict):
        return {}
    now = datetime.now().isoformat()
    safe_source = str(source or "manual")[:40]
    try:
        options_json = json.dumps(options or {})
    except Exception:
        options_json = json.dumps({})
    try:
        payload_json = json.dumps(payload)
    except Exception:
        payload_json = json.dumps({})

    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO reading_plan_snapshots (plan_date, source, options_json, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (str(plan_date), safe_source, options_json, payload_json, now),
    )
    snapshot_id = c.lastrowid
    # Keep table bounded.
    c.execute(
        '''
        DELETE FROM reading_plan_snapshots
        WHERE id IN (
            SELECT id
            FROM reading_plan_snapshots
            ORDER BY created_at DESC, id DESC
            LIMIT -1 OFFSET 800
        )
        '''
    )
    conn.commit()
    conn.close()
    return {
        "id": int(snapshot_id or 0),
        "plan_date": str(plan_date),
        "source": safe_source,
        "created_at": now,
    }


def get_reading_plan_snapshot(plan_date: str) -> Optional[Dict[str, Any]]:
    if not plan_date:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, plan_date, source, options_json, payload_json, created_at
        FROM reading_plan_snapshots
        WHERE plan_date = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        ''',
        (str(plan_date),),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    rec = dict(row)
    try:
        rec["options"] = json.loads(rec.pop("options_json") or "{}")
    except Exception:
        rec["options"] = {}
    try:
        rec["payload"] = json.loads(rec.pop("payload_json") or "{}")
    except Exception:
        rec["payload"] = {}
    return rec


def list_reading_plan_snapshots(
    limit: int = 30,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit or 30), 200))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    where = []
    params: List[Any] = []
    if date_from:
        where.append("plan_date >= ?")
        params.append(str(date_from))
    if date_to:
        where.append("plan_date <= ?")
        params.append(str(date_to))
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    c.execute(
        f'''
        SELECT id, plan_date, source, options_json, payload_json, created_at
        FROM reading_plan_snapshots
        {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        ''',
        [*params, lim],
    )
    rows = c.fetchall()
    conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        try:
            options = json.loads(rec.pop("options_json") or "{}")
        except Exception:
            options = {}
        try:
            payload = json.loads(rec.pop("payload_json") or "{}")
        except Exception:
            payload = {}
        out.append(
            {
                "id": int(rec.get("id") or 0),
                "plan_date": rec.get("plan_date"),
                "source": rec.get("source"),
                "created_at": rec.get("created_at"),
                "options": options,
                "count": int(payload.get("count") or 0),
                "planned_minutes": int(payload.get("planned_minutes") or 0),
                "total_minutes_budget": int(payload.get("total_minutes_budget") or 0),
            }
        )
    return out


def defer_reading_plan_paper(paper_id: str, defer_until: str, reason: Optional[str] = None) -> Dict[str, Any]:
    if not paper_id:
        return {}
    now = datetime.now().isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO reading_plan_deferred (paper_id, defer_until, reason, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            defer_until = excluded.defer_until,
            reason = excluded.reason,
            updated_at = excluded.updated_at
        ''',
        (str(paper_id), str(defer_until), (reason or None), now),
    )
    conn.commit()
    conn.close()
    return {
        "paper_id": str(paper_id),
        "defer_until": str(defer_until),
        "reason": (reason or None),
        "updated_at": now,
    }


def clear_deferred_reading_plan_paper(paper_id: str) -> bool:
    if not paper_id:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM reading_plan_deferred WHERE paper_id = ?", (str(paper_id),))
    conn.commit()
    ok = bool(c.rowcount and c.rowcount > 0)
    conn.close()
    return ok


def get_deferred_reading_map(
    paper_ids: List[str],
    on_date: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    if not paper_ids:
        return {}
    day = str(on_date or datetime.now().date().isoformat())
    unique_ids = [str(pid) for pid in dict.fromkeys(paper_ids) if pid]
    if not unique_ids:
        return {}

    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    out: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunked(unique_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f'''
            SELECT paper_id, defer_until, reason, updated_at
            FROM reading_plan_deferred
            WHERE paper_id IN ({placeholders})
              AND defer_until >= ?
            ''',
            [*chunk, day],
        )
        for row in c.fetchall():
            rec = dict(row)
            out[str(rec.get("paper_id"))] = rec
    conn.close()
    return out


def record_reading_plan_activity(
    plan_date: str,
    paper_id: str,
    action: str,
    minutes: int = 0,
    meta: Optional[Dict[str, Any]] = None,
) -> int:
    if not plan_date or not paper_id or not action:
        return 0
    now = datetime.now().isoformat()
    safe_action = str(action).strip().lower()[:40]
    safe_minutes = max(0, int(minutes or 0))
    try:
        meta_json = json.dumps(meta or {})
    except Exception:
        meta_json = json.dumps({})
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO reading_plan_activity (plan_date, paper_id, action, minutes, meta_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (str(plan_date), str(paper_id), safe_action, safe_minutes, meta_json, now),
    )
    rid = int(c.lastrowid or 0)
    c.execute(
        '''
        DELETE FROM reading_plan_activity
        WHERE id IN (
            SELECT id
            FROM reading_plan_activity
            ORDER BY created_at DESC, id DESC
            LIMIT -1 OFFSET 5000
        )
        '''
    )
    conn.commit()
    conn.close()
    return rid


def list_reading_plan_activity(
    limit: int = 500,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit or 500), 3000))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    where = []
    params: List[Any] = []
    if date_from:
        where.append("plan_date >= ?")
        params.append(str(date_from))
    if date_to:
        where.append("plan_date <= ?")
        params.append(str(date_to))
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    c.execute(
        f'''
        SELECT id, plan_date, paper_id, action, minutes, meta_json, created_at
        FROM reading_plan_activity
        {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        ''',
        [*params, lim],
    )
    rows = c.fetchall()
    conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        try:
            rec["meta"] = json.loads(rec.pop("meta_json") or "{}")
        except Exception:
            rec["meta"] = {}
        rec["minutes"] = int(rec.get("minutes") or 0)
        out.append(rec)
    return out


def set_version_update_state(
    arxiv_base_id: str,
    status: str,
    snooze_until: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    if not arxiv_base_id or not status:
        return {}
    now = datetime.now().isoformat()
    state = str(status).strip().lower()
    if state not in {"reviewed", "snoozed", "dismissed"}:
        return {}
    snooze_val = None
    if state == "snoozed" and snooze_until:
        snooze_val = str(snooze_until)
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO version_update_states (arxiv_base_id, status, snooze_until, note, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(arxiv_base_id) DO UPDATE SET
            status = excluded.status,
            snooze_until = excluded.snooze_until,
            note = excluded.note,
            updated_at = excluded.updated_at
        ''',
        (str(arxiv_base_id), state, snooze_val, note or None, now),
    )
    conn.commit()
    conn.close()
    return {
        "arxiv_base_id": str(arxiv_base_id),
        "status": state,
        "snooze_until": snooze_val,
        "note": note or None,
        "updated_at": now,
    }


def clear_version_update_state(arxiv_base_id: str) -> bool:
    if not arxiv_base_id:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM version_update_states WHERE arxiv_base_id = ?", (str(arxiv_base_id),))
    conn.commit()
    ok = bool(c.rowcount and c.rowcount > 0)
    conn.close()
    return ok


def get_version_update_state_map(
    base_ids: List[str],
    on_date: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    if not base_ids:
        return {}
    day = str(on_date or datetime.now().date().isoformat())
    unique_ids = [str(x) for x in dict.fromkeys(base_ids) if x]
    if not unique_ids:
        return {}
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    out: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunked(unique_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f'''
            SELECT arxiv_base_id, status, snooze_until, note, updated_at
            FROM version_update_states
            WHERE arxiv_base_id IN ({placeholders})
            ''',
            chunk,
        )
        for row in c.fetchall():
            rec = dict(row)
            status = str(rec.get("status") or "").lower()
            snooze_until = str(rec.get("snooze_until") or "")
            active = True
            if status in {"reviewed", "dismissed"}:
                active = False
            elif status == "snoozed" and snooze_until and snooze_until >= day:
                active = False
            rec["active"] = active
            out[str(rec.get("arxiv_base_id") or "")] = rec
    conn.close()
    return out


def get_paper_notes(paper_id: str) -> Optional[Dict[str, Any]]:
    if not paper_id:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT paper_id, notes, created_at, updated_at
        FROM paper_notes
        WHERE paper_id = ?
        ''',
        (paper_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def list_paper_notes_history(paper_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    if not paper_id:
        return []
    lim = max(1, min(int(limit), 100))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, paper_id, notes, created_at
        FROM paper_notes_history
        WHERE paper_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        ''',
        (paper_id, lim),
    )
    rows = c.fetchall()
    conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        notes = rec.get("notes") or ""
        rec["preview"] = (notes[:180] + "…") if len(notes) > 180 else notes
        rec["length"] = len(notes)
        rec.pop("notes", None)
        out.append(rec)
    return out

def get_paper_notes_history_entry(history_id: str) -> Optional[Dict[str, Any]]:
    if not history_id:
        return None
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, paper_id, notes, created_at
        FROM paper_notes_history
        WHERE id = ?
        ''',
        (history_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_notes_meta_map(paper_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not paper_ids:
        return {}
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    out: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunked(paper_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f'''
            SELECT paper_id, updated_at, notes
            FROM paper_notes
            WHERE paper_id IN ({placeholders})
            ''',
            chunk,
        )
        for row in c.fetchall():
            rec = dict(row)
            out[str(rec.get("paper_id"))] = {
                "updated_at": rec.get("updated_at"),
                "has_notes": bool(rec.get("notes")),
            }
    conn.close()
    return out

def set_paper_notes(paper_id: str, notes: Optional[str]) -> Dict[str, Any]:
    if not paper_id:
        return {}
    clean = (notes or "").strip()
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        "SELECT notes, created_at FROM paper_notes WHERE paper_id = ?",
        (paper_id,),
    )
    row = c.fetchone()
    existing_notes = row[0] if row else None
    created_at = row[1] if row else now

    if row and (existing_notes or "") != clean:
        import uuid
        if (existing_notes or "").strip():
            c.execute(
                '''
                INSERT INTO paper_notes_history (id, paper_id, notes, created_at)
                VALUES (?, ?, ?, ?)
                ''',
                (str(uuid.uuid4()), paper_id, existing_notes or "", now),
            )
            # Keep only the latest N versions
            c.execute(
                '''
                DELETE FROM paper_notes_history
                WHERE paper_id = ? AND id NOT IN (
                    SELECT id FROM paper_notes_history
                    WHERE paper_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                )
                ''',
                (paper_id, paper_id, int(NOTES_HISTORY_LIMIT)),
            )

    if not clean:
        c.execute("DELETE FROM paper_notes WHERE paper_id = ?", (paper_id,))
        conn.commit()
        conn.close()
        return {"paper_id": paper_id, "notes": "", "updated_at": now, "deleted": True}
    c.execute(
        '''
        INSERT INTO paper_notes (paper_id, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            notes = excluded.notes,
            updated_at = excluded.updated_at
        ''',
        (paper_id, clean, created_at, now),
    )
    conn.commit()
    conn.close()
    return {"paper_id": paper_id, "notes": clean, "updated_at": now, "deleted": False}

def import_notes_bulk(entries: List[Dict[str, Any]]) -> Dict[str, int]:
    if not entries:
        return {"imported": 0, "skipped": 0}
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    imported = 0
    skipped = 0
    import uuid
    for entry in entries:
        pid = entry.get("paper_id") or entry.get("id")
        notes = (entry.get("notes") or "").strip()
        if not pid or not notes:
            skipped += 1
            continue
        c.execute(
            "SELECT notes, created_at FROM paper_notes WHERE paper_id = ?",
            (pid,),
        )
        row = c.fetchone()
        existing_notes = row[0] if row else None
        created_at = row[1] if row else now
        if row and (existing_notes or "") != notes:
            if (existing_notes or "").strip():
                c.execute(
                    '''
                    INSERT INTO paper_notes_history (id, paper_id, notes, created_at)
                    VALUES (?, ?, ?, ?)
                    ''',
                    (str(uuid.uuid4()), pid, existing_notes or "", now),
                )
                c.execute(
                    '''
                    DELETE FROM paper_notes_history
                    WHERE paper_id = ? AND id NOT IN (
                        SELECT id FROM paper_notes_history
                        WHERE paper_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                    )
                    ''',
                    (pid, pid, int(NOTES_HISTORY_LIMIT)),
                )
        c.execute(
            '''
            INSERT INTO paper_notes (paper_id, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
                notes = excluded.notes,
                updated_at = excluded.updated_at
            ''',
            (pid, notes, created_at, now),
        )
        imported += 1
    conn.commit()
    conn.close()
    return {"imported": imported, "skipped": skipped}

def get_paper_notes_map(paper_ids: List[str]) -> Dict[str, str]:
    if not paper_ids:
        return {}
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    out: Dict[str, str] = {}
    for chunk in _chunked(paper_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f'''
            SELECT paper_id, notes
            FROM paper_notes
            WHERE paper_id IN ({placeholders})
            ''',
            chunk,
        )
        for row in c.fetchall():
            pid = str(row["paper_id"])
            out[pid] = row["notes"] or ""
    conn.close()
    return out

def export_notes() -> List[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT n.paper_id, n.notes, n.updated_at, n.created_at,
               p.title, p.published
        FROM paper_notes n
        LEFT JOIN papers p ON p.id = n.paper_id
        ORDER BY n.updated_at DESC
        '''
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def list_paper_comments(paper_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    if not paper_id:
        return []
    lim = max(1, min(int(limit), 200))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, paper_id, author, body, mentions, created_at, updated_at
        FROM paper_comments
        WHERE paper_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        ''',
        (paper_id, lim),
    )
    rows = c.fetchall()
    conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        mentions_raw = rec.get("mentions")
        if mentions_raw:
            try:
                rec["mentions"] = json.loads(mentions_raw)
            except Exception:
                rec["mentions"] = []
        else:
            rec["mentions"] = []
        out.append(rec)
    return out

def add_paper_comment(
    paper_id: str,
    author: str,
    body: str,
    mentions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if not paper_id or not body:
        return {}
    import uuid
    comment_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    author_clean = (author or "").strip() or "Anonymous"
    body_clean = (body or "").strip()
    mentions_list = mentions or []
    mentions_json = json.dumps(mentions_list)
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO paper_comments (id, paper_id, author, body, mentions, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (comment_id, paper_id, author_clean, body_clean, mentions_json, now, now),
    )
    if mentions_list:
        mention_rows = []
        for m in mentions_list:
            clean = (m or "").strip().lstrip("@").lower()
            if not clean:
                continue
            mention_rows.append(
                (
                    str(uuid.uuid4()),
                    clean,
                    paper_id,
                    comment_id,
                    author_clean,
                    body_clean,
                    now,
                )
            )
        if mention_rows:
            c.executemany(
                '''
                INSERT INTO comment_mentions (id, mention, paper_id, comment_id, author, body, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                mention_rows,
            )
    conn.commit()
    conn.close()
    return {
        "id": comment_id,
        "paper_id": paper_id,
        "author": author_clean,
        "body": body_clean,
        "mentions": mentions or [],
        "created_at": now,
        "updated_at": now,
    }

def delete_paper_comment(comment_id: str) -> bool:
    if not comment_id:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM paper_comments WHERE id = ?", (comment_id,))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok

def list_mentions_for_handle(handle: str, limit: int = 50) -> List[Dict[str, Any]]:
    clean = (handle or "").strip().lstrip("@").lower()
    if not clean:
        return []
    lim = max(1, min(int(limit), 200))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT m.id, m.mention, m.paper_id, m.comment_id, m.author, m.body, m.created_at,
               p.title, p.published
        FROM comment_mentions m
        LEFT JOIN papers p ON p.id = m.paper_id
        WHERE m.mention = ?
        ORDER BY m.created_at DESC
        LIMIT ?
        ''',
        (clean, lim),
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def set_weekly_pick(paper_id: str, active: bool) -> Dict[str, Any]:
    if not paper_id:
        return {"paper_id": paper_id, "active": False}
    if active:
        add_paper_labels(paper_id, ["Weekly Pick"], source="weekly")
        return {"paper_id": paper_id, "active": True}
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        DELETE FROM paper_labels
        WHERE paper_id = ? AND label = ? AND source = ?
        ''',
        (paper_id, "Weekly Pick", "weekly"),
    )
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return {"paper_id": paper_id, "active": False, "removed": ok}

def list_weekly_picks(days: int = 7, limit: int = 50) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit), 200))
    try:
        days_int = max(1, int(days))
    except Exception:
        days_int = 7
    cutoff = (datetime.now() - timedelta(days=days_int)).isoformat()
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT p.*, l.created_at AS picked_at
        FROM papers p
        JOIN paper_labels l ON p.id = l.paper_id
        WHERE l.label = ? AND l.source = ? AND l.created_at >= ?
        ORDER BY l.created_at DESC
        LIMIT ?
        ''',
        ("Weekly Pick", "weekly", cutoff, lim),
    )
    rows = c.fetchall()
    conn.close()
    out = []
    for row in rows:
        rec = dict(row)
        rec = _deserialize_paper_dict(rec)
        out.append(rec)
    return out

def get_papers_by_ids(paper_ids: List[str], allow_fuzzy: bool = False):
    if not paper_ids:
        return []
    requested = [str(pid) for pid in paper_ids if pid]
    if not requested:
        return []
    query_ids = list(dict.fromkeys(
        requested
        + [f"http://arxiv.org/abs/{pid}" for pid in requested if not str(pid).startswith("http")]
    ))

    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Exact match in chunks to avoid sqlite variable limits on large lists.
    found_map: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunked(query_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(f"SELECT * FROM papers WHERE id IN ({placeholders})", chunk)
        for row in c.fetchall():
            rec = dict(row)
            rid = str(rec.get("id") or "")
            if rid and rid not in found_map:
                found_map[rid] = rec

    missing_ids = [pid for pid in requested if pid not in found_map]

    # Constrained fuzzy fallback: only for single short id lookups.
    if (
        allow_fuzzy
        and len(requested) == 1
        and len(missing_ids) == 1
    ):
        mid = str(missing_ids[0] or "").strip()
        if mid and len(mid) <= 64:
            c.execute("SELECT * FROM papers WHERE id LIKE ? LIMIT 5", (f"%{mid}%",))
            for row in c.fetchall():
                rec = dict(row)
                rid = str(rec.get("id") or "")
                if rid and mid in rid and rid not in found_map:
                    found_map[rid] = rec
                    break

    conn.close()

    ordered: List[Dict[str, Any]] = []
    used: set[str] = set()
    for pid in requested:
        rec = found_map.get(pid)
        if rec is None and not str(pid).startswith("http"):
            rec = found_map.get(f"http://arxiv.org/abs/{pid}")
        if rec is not None:
            rid = str(rec.get("id") or "")
            if rid and rid not in used:
                ordered.append(_deserialize_paper_dict(rec))
                used.add(rid)
                continue
        # Fuzzy match case.
        for rid, candidate in found_map.items():
            if rid in used:
                continue
            if pid and pid in rid:
                ordered.append(_deserialize_paper_dict(candidate))
                used.add(rid)
                break
    return ordered

def add_bookmark(paper_id: str):
    conn = _connect()
    c = conn.cursor()
    c.execute('''
        INSERT OR IGNORE INTO bookmarks (paper_id, created_at) VALUES (?, ?)
    ''', (paper_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def remove_bookmark(paper_id: str):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM bookmarks WHERE paper_id = ?", (paper_id,))
    conn.commit()
    conn.close()

def index_paper_text(paper_id: str, content: str):
    conn = _connect()
    c = conn.cursor()
    # Delete existing index for this paper to avoid duplicates/staleness
    c.execute("DELETE FROM paper_fts WHERE paper_id = ?", (paper_id,))
    c.execute("INSERT INTO paper_fts (paper_id, content) VALUES (?, ?)", (paper_id, content))
    conn.commit()
    conn.close()

def index_papers_text(items: List[tuple[str, str]]) -> int:
    if not items:
        return 0
    rows = [(pid, content) for pid, content in items if pid and content]
    if not rows:
        return 0
    conn = _connect()
    c = conn.cursor()
    try:
        c.executemany("DELETE FROM paper_fts WHERE paper_id = ?", [(pid,) for pid, _ in rows])
        c.executemany("INSERT INTO paper_fts (paper_id, content) VALUES (?, ?)", rows)
        conn.commit()
    except sqlite3.OperationalError:
        conn.close()
        return 0
    conn.close()
    return len(rows)

def backfill_fts(limit: int = 2000) -> int:
    if limit <= 0:
        return 0
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute(
            '''
            SELECT p.id, p.title, p.summary, p.authors, p.categories
            FROM papers p
            WHERE NOT EXISTS (
                SELECT 1 FROM paper_fts f WHERE f.paper_id = p.id
            )
            ORDER BY p.published DESC
            LIMIT ?
            ''',
            (int(limit),),
        )
        rows = c.fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return 0
    conn.close()
    if not rows:
        return 0
    items: List[tuple[str, str]] = []
    for row in rows:
        rec = dict(row)
        pid = rec.get("id")
        if not pid:
            continue
        title = rec.get("title") or ""
        summary = rec.get("summary") or ""
        authors = rec.get("authors") or ""
        categories = rec.get("categories") or ""
        content = f"{title} {summary} {authors} {categories}".strip()
        items.append((pid, content))
    return index_papers_text(items)

def rebuild_fts(batch_size: int = 1000) -> int:
    batch = max(100, int(batch_size))
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("DELETE FROM paper_fts")
        conn.commit()
    except sqlite3.OperationalError:
        conn.close()
        return 0

    total = 0
    offset = 0
    while True:
        c.execute(
            '''
            SELECT id, title, summary, authors, categories
            FROM papers
            ORDER BY id
            LIMIT ? OFFSET ?
            ''',
            (batch, offset),
        )
        rows = c.fetchall()
        if not rows:
            break
        items: List[tuple[str, str]] = []
        for row in rows:
            rec = dict(row)
            pid = rec.get("id")
            if not pid:
                continue
            title = rec.get("title") or ""
            summary = rec.get("summary") or ""
            authors = rec.get("authors") or ""
            categories = rec.get("categories") or ""
            items.append((pid, f"{title} {summary} {authors} {categories}".strip()))
        if items:
            c.executemany("INSERT INTO paper_fts (paper_id, content) VALUES (?, ?)", items)
            conn.commit()
            total += len(items)
        offset += batch

    conn.close()
    return total

def search_full_text_paged(query: str, limit: int = 50, offset: int = 0) -> tuple[List[Dict[str, Any]], int]:
    conn = _connect()
    c = conn.cursor()
    total = 0
    try:
        c.execute("SELECT COUNT(*) FROM paper_fts WHERE paper_fts MATCH ?", (query,))
        row = c.fetchone()
        total = int(row[0]) if row else 0
    except Exception:
        try:
            c.execute("SELECT COUNT(*) FROM paper_fts WHERE content MATCH ?", (query,))
            row = c.fetchone()
            total = int(row[0]) if row else 0
        except Exception:
            total = 0

    try:
        c.execute('''
            SELECT paper_id, snippet(paper_fts, 1, '<b>', '</b>', '...', 20) as snippet 
            FROM paper_fts 
            WHERE paper_fts MATCH ? 
            ORDER BY bm25(paper_fts)
            LIMIT ? OFFSET ?
        ''', (query, int(limit), int(offset)))
    except Exception:
        # FTS4 fallback
        c.execute('''
            SELECT paper_id, snippet(paper_fts) as snippet 
            FROM paper_fts 
            WHERE content MATCH ? 
            LIMIT ? OFFSET ?
        ''', (query, int(limit), int(offset)))

    rows = c.fetchall()
    conn.close()
    return ([{"id": r[0], "snippet": r[1]} for r in rows], total)

def search_full_text(query: str, limit: int = 50):
    items, _total = search_full_text_paged(query, limit=limit, offset=0)
    return items

def search_papers(query: str, limit: int = 50):
    """Compatibility wrapper for callers expecting a limit arg."""
    return search_full_text(query, limit=limit)

def save_embeddings(items: List[tuple[str, np.ndarray]]) -> int:
    """Bulk-save numpy embeddings to the DB."""
    if not items:
        return 0

    rows = []
    now = datetime.now().isoformat()
    for paper_id, embedding in items:
        if not paper_id or embedding is None or getattr(embedding, "size", 0) == 0:
            continue
        vec = embedding.astype(np.float32, copy=False)
        rows.append((paper_id, vec.tobytes(), now))

    if not rows:
        return 0

    conn = _connect()
    c = conn.cursor()

    c.executemany('''
        INSERT OR REPLACE INTO paper_embeddings (paper_id, embedding, updated_at)
        VALUES (?, ?, ?)
    ''', rows)

    conn.commit()
    conn.close()
    _invalidate_embedding_cache()
    return len(rows)

def save_embedding(paper_id: str, embedding: np.ndarray):
    """Saves a numpy embedding to the DB."""
    save_embeddings([(paper_id, embedding)])

def search_semantic(query_embedding: np.ndarray, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Performs cosine similarity search against all stored embeddings.
    Loads all embeddings into memory (fast for <100k papers).
    """
    ids, matrix, _ = _load_embedding_matrix()
    if matrix.size == 0 or not ids:
        return []
    
    # Cosine Similarity
    # query_embedding should be normalized. Matrix rows should be normalized.
    # We assume they are normalized on generation.
    # sim = dot(A, B) / (norm(A) * norm(B))
    # If normalized, just dot(A, B).
    
    # Ensure dimensions match
    if matrix.shape[1] != query_embedding.shape[0]:
        print(f"Dimension mismatch: DB={matrix.shape[1]}, Query={query_embedding.shape[0]}")
        return []
        
    scores = np.dot(matrix, query_embedding)
    top_k = min(limit, scores.shape[0])
    if top_k <= 0:
        return []

    # Use argpartition for faster top-k on large arrays.
    if top_k == scores.shape[0]:
        top_indices = np.argsort(scores)[::-1]
    else:
        partial = np.argpartition(scores, -top_k)[-top_k:]
        top_indices = partial[np.argsort(scores[partial])[::-1]]
    
    results = []
    for idx in top_indices:
        results.append({
            "id": ids[idx],
            "score": float(scores[idx])
        })
        
    return results

def compute_novelty_scores(paper_ids: List[str], reference_status: str = "liked") -> Dict[str, float]:
    """
    Computes novelty in [0,1] for target papers against a reference set.
    novelty ~= 1 - max_cosine_similarity(reference_set).
    """
    if not paper_ids:
        return {}

    ids, matrix, id_to_idx = _load_embedding_matrix()
    if matrix.size == 0:
        return {}

    target_indices = []
    target_ids = []
    for pid in paper_ids:
        idx = id_to_idx.get(pid)
        if idx is not None:
            target_indices.append(idx)
            target_ids.append(pid)
    if not target_indices:
        return {}

    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT paper_id FROM interactions WHERE status = ?", (reference_status,))
    ref_ids = [r[0] for r in c.fetchall()]
    conn.close()

    ref_indices = [id_to_idx[pid] for pid in ref_ids if pid in id_to_idx]
    if not ref_indices:
        # Fallback to all embeddings except the target itself.
        ref_indices = [i for i in range(len(ids)) if i not in set(target_indices)]
    if not ref_indices:
        return {}

    target_matrix = matrix[target_indices]
    ref_matrix = matrix[ref_indices]
    sim = np.dot(target_matrix, ref_matrix.T)
    max_sim = sim.max(axis=1)

    novelty = {}
    for pid, s in zip(target_ids, max_sim):
        value = max(0.0, min(1.0, 1.0 - float(s)))
        novelty[pid] = round(value, 3)
    return novelty

def update_match_scores(scores: Dict[str, int]) -> int:
    if not scores:
        return 0
    conn = _connect()
    c = conn.cursor()
    rows = [(int(v or 0), k) for k, v in scores.items() if k]
    if not rows:
        conn.close()
        return 0
    c.executemany("UPDATE papers SET match_score = ? WHERE id = ?", rows)
    conn.commit()
    conn.close()
    return len(rows)

def update_ranker_scores(scores: Dict[str, float]) -> int:
    if not scores:
        return 0
    conn = _connect()
    c = conn.cursor()
    rows = [(float(v or 0.0), k) for k, v in scores.items() if k]
    if not rows:
        conn.close()
        return 0
    c.executemany("UPDATE papers SET ranker_score = ? WHERE id = ?", rows)
    conn.commit()
    conn.close()
    return len(rows)

def recompute_match_scores(keywords: Optional[List[str]] = None) -> int:
    kw = [k.lower() for k in (keywords or config.KEYWORDS) if k]
    if not kw:
        return 0
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, title, summary FROM papers")
    rows = c.fetchall()
    conn.close()
    if not rows:
        return 0
    scores = {}
    for row in rows:
        rec = dict(row)
        pid = rec.get("id")
        if not pid:
            continue
        scores[pid] = _compute_match_score(rec.get("title", ""), rec.get("summary", ""), kw)
    return update_match_scores(scores)

def update_novelty_scores(scores: Dict[str, float]) -> int:
    if not scores:
        return 0
    conn = _connect()
    c = conn.cursor()
    rows = [(float(v), k) for k, v in scores.items() if k and v is not None]
    if not rows:
        conn.close()
        return 0
    c.executemany("UPDATE papers SET novelty_score = ? WHERE id = ?", rows)
    conn.commit()
    conn.close()
    return len(rows)

def get_bookmarked_ids() -> List[str]:
    conn = _connect()
    c = conn.cursor()
    c.execute('SELECT paper_id FROM bookmarks')
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_graph_data():
    """
    Builds a co-authorship graph from the library.
    Returns: { nodes: [{id, label, value}], edges: [{from, to, value}] }
    """
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    # Fetch authors ONLY from Liked (Favorited) papers
    c.execute('''
        SELECT p.authors 
        FROM papers p
        JOIN interactions i ON p.id = i.paper_id
        WHERE i.status = 'liked'
    ''')
    rows = c.fetchall()
    conn.close()
    
    from collections import Counter
    import itertools
    
    author_counts = Counter()
    co_occurrences = Counter()
    
    for row in rows:
        raw = row['authors']
        try:
            authors = json.loads(raw) if raw else []
        except:
            authors = [raw] if raw else []
            
        if not authors: continue
        
        # Count individual frequency (node size)
        author_counts.update(authors)
        
        # Count connections (edge weight)
        # SKIP edge generation for papers with > 50 authors to prevent "hairball" explosion
        if len(authors) > 1 and len(authors) <= 50:
            # Sort to ensure undirected edge consistency
            for u, v in itertools.combinations(sorted(authors), 2):
                co_occurrences[(u, v)] += 1
                
    # Format for vis-network
    # Limit to Top 500 authors (relaxed since we are only looking at favorites)
    top_authors = set(dict(author_counts.most_common(500)).keys())
    
    nodes = []
    for author, count in author_counts.items():
        if author in top_authors:
            nodes.append({
                "id": author,
                "label": author,
                "value": count, # Size
                "group": "author"
            })
        
    edges = []
    for (source, target), weight in co_occurrences.items():
        if source in top_authors and target in top_authors:
            edges.append({
                "from": source,
                "to": target,
                "value": weight # Thickness
            })
        
    return {"nodes": nodes, "edges": edges}

def get_concept_graph() -> Dict:
    """
    Builds a network graph of concepts based on co-occurrence.
    Nodes: Concepts (size = frequency)
    Edges: Co-occurrence (thickness = count)
    """
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT concepts FROM papers WHERE concepts IS NOT NULL")
    rows = c.fetchall()
    conn.close()
    
    node_counts = {}
    edge_counts = {}
    
    for r in rows:
        try:
            tags = json.loads(r[0])
            # Only consider valid lists
            if not isinstance(tags, list): continue
            
            # Normalize tags (lowercase?) -> No, keep display case for now, maybe set.
            # Count nodes
            for t in tags:
                node_counts[t] = node_counts.get(t, 0) + 1
                
            # Count edges (pairs)
            for i in range(len(tags)):
                for j in range(i + 1, len(tags)):
                    edge = tuple(sorted((tags[i], tags[j])))
                    edge_counts[edge] = edge_counts.get(edge, 0) + 1
                    
        except:
            continue
            
    # Format for Vis.js
    nodes = []
    edges = []
    
    # Filter noise? Min occurrence 2?
    
    for tag, count in node_counts.items():
        if count >= 1: # Include all for now
            nodes.append({
                "id": tag,
                "label": tag,
                "value": count, # Size
                "group": "concept"
            })
            
    for (source, target), weight in edge_counts.items():
        if weight >= 1:
            edges.append({
                "from": source,
                "to": target,
                "value": weight # Thickness
            })
        
    return {"nodes": nodes, "edges": edges}

def get_all_embeddings() -> List[Dict[str, Any]]:
    """Retrieves all paper embeddings and their titles."""
    conn = _connect()
    c = conn.cursor()
    
    # We join with papers table to get title too
    c.execute('''
        SELECT e.paper_id, e.embedding, p.title, p.categories 
        FROM paper_embeddings e
        JOIN papers p ON e.paper_id = p.id
    ''')
    
    results = []
    for row in c.fetchall():
        try:
            emb = np.frombuffer(row[1], dtype=np.float32)
            results.append({
                "id": row[0],
                "vector": emb,
                "title": row[2],
                "category": row[3]
            })
        except Exception as e:
            print(f"Error loading embedding for {row[0]}: {e}")
            
    conn.close()
    return results

def update_paper_concepts(paper_id: str, concepts: List[str]):
    """Updates the concepts list for a specific paper."""
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE papers SET concepts = ? WHERE id = ?", (json.dumps(concepts), paper_id))
    conn.commit()
    conn.close()

def update_paper_structure(paper_id: str, structure: Dict[str, Any]):
    """Caches structured paper summary for a paper."""
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE papers SET structure = ? WHERE id = ?", (json.dumps(structure), paper_id))
    conn.commit()
    conn.close()


def update_paper_structures(items: List[tuple[str, Dict[str, Any]]]) -> int:
    """Bulk-caches structured summaries for multiple papers."""
    if not items:
        return 0
    rows = []
    for paper_id, structure in items:
        if not paper_id or structure is None:
            continue
        try:
            payload = json.dumps(structure)
        except Exception:
            continue
        rows.append((payload, str(paper_id)))
    if not rows:
        return 0
    conn = _connect()
    c = conn.cursor()
    c.executemany("UPDATE papers SET structure = ? WHERE id = ?", rows)
    conn.commit()
    count = c.rowcount if c.rowcount is not None else len(rows)
    conn.close()
    return int(max(0, count))

def get_alert_settings() -> Dict[str, Any]:
    defaults = {
        "citation_threshold": 25,
        "max_results": 100,
    }
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT key, value FROM alert_settings")
    rows = c.fetchall()
    conn.close()
    settings = defaults.copy()
    for k, v in rows:
        try:
            settings[k] = json.loads(v)
        except Exception:
            settings[k] = v
    return settings

def set_alert_settings(settings: Dict[str, Any]):
    if not settings:
        return
    conn = _connect()
    c = conn.cursor()
    rows = []
    for k, v in settings.items():
        rows.append((k, json.dumps(v)))
    c.executemany(
        "INSERT OR REPLACE INTO alert_settings (key, value) VALUES (?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

def create_alerts(alert_rows: List[Dict[str, Any]]) -> int:
    """
    Inserts alert rows, deduped by (paper_id, alert_type).
    Returns number of newly inserted alerts.
    """
    if not alert_rows:
        return 0
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    inserted = 0
    for row in alert_rows:
        c.execute('''
            INSERT OR IGNORE INTO alerts (paper_id, alert_type, message, created_at, seen)
            VALUES (?, ?, ?, ?, 0)
        ''', (row["paper_id"], row["alert_type"], row["message"], row.get("created_at", now)))
        inserted += c.rowcount
    conn.commit()
    conn.close()
    return inserted

def get_alerts(limit: int = 100, unseen_only: bool = False) -> List[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if unseen_only:
        c.execute('''
            SELECT a.id, a.paper_id, a.alert_type, a.message, a.created_at, a.seen,
                   p.title, p.authors, p.published, p.citation_count
            FROM alerts a
            LEFT JOIN papers p ON p.id = a.paper_id
            WHERE a.seen = 0
            ORDER BY a.created_at DESC
            LIMIT ?
        ''', (limit,))
    else:
        c.execute('''
            SELECT a.id, a.paper_id, a.alert_type, a.message, a.created_at, a.seen,
                   p.title, p.authors, p.published, p.citation_count
            FROM alerts a
            LEFT JOIN papers p ON p.id = a.paper_id
            ORDER BY a.created_at DESC
            LIMIT ?
        ''', (limit,))
    rows = c.fetchall()
    conn.close()
    alerts = []
    for row in rows:
        item = dict(row)
        if item.get("authors") and isinstance(item["authors"], str):
            try:
                item["authors"] = json.loads(item["authors"])
            except Exception:
                item["authors"] = [item["authors"]]
        alerts.append(item)
    return alerts

def mark_alerts_seen(alert_ids: List[int] = None):
    conn = _connect()
    c = conn.cursor()
    if alert_ids:
        placeholders = ",".join(["?"] * len(alert_ids))
        c.execute(f"UPDATE alerts SET seen = 1 WHERE id IN ({placeholders})", alert_ids)
    else:
        c.execute("UPDATE alerts SET seen = 1 WHERE seen = 0")
    conn.commit()
    conn.close()

def count_unseen_alerts() -> int:
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM alerts WHERE seen = 0")
    row = c.fetchone()
    conn.close()
    return int(row[0]) if row else 0

def get_changes_since(since_iso: str, limit: int = 6) -> Dict[str, Any]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    limit = max(1, min(int(limit), 50))

    c.execute("SELECT COUNT(*) FROM papers WHERE fetched_at >= ?", (since_iso,))
    new_count = int(c.fetchone()[0] or 0)
    c.execute(
        '''
        SELECT id, title, published, fetched_at
        FROM papers
        WHERE fetched_at >= ?
        ORDER BY fetched_at DESC
        LIMIT ?
        ''',
        (since_iso, limit),
    )
    new_papers = [dict(row) for row in c.fetchall()]

    c.execute(
        "SELECT COUNT(*) FROM alerts WHERE alert_type = 'version' AND created_at >= ?",
        (since_iso,),
    )
    version_count = int(c.fetchone()[0] or 0)
    c.execute(
        '''
        SELECT a.paper_id, a.message, a.created_at, p.title
        FROM alerts a
        LEFT JOIN papers p ON p.id = a.paper_id
        WHERE a.alert_type = 'version' AND a.created_at >= ?
        ORDER BY a.created_at DESC
        LIMIT ?
        ''',
        (since_iso, limit),
    )
    version_updates = [dict(row) for row in c.fetchall()]

    c.execute(
        "SELECT COUNT(*) FROM papers WHERE citation_updated_at IS NOT NULL AND citation_updated_at >= ?",
        (since_iso,),
    )
    citation_count = int(c.fetchone()[0] or 0)
    c.execute(
        '''
        SELECT id, title, citation_count, citation_updated_at
        FROM papers
        WHERE citation_updated_at IS NOT NULL AND citation_updated_at >= ?
        ORDER BY citation_updated_at DESC
        LIMIT ?
        ''',
        (since_iso, limit),
    )
    citation_updates = [dict(row) for row in c.fetchall()]

    conn.close()
    return {
        "counts": {
            "new_papers": new_count,
            "version_updates": version_count,
            "citation_updates": citation_count,
        },
        "new_papers": new_papers,
        "version_updates": version_updates,
        "citation_updates": citation_updates,
    }

def create_saved_search_agent(name: str, query: str, cadence: str = "daily", max_results: int = 8) -> int:
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        '''
        INSERT INTO saved_search_agents (name, query, cadence, max_results, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (name, query, cadence, max(1, int(max_results)), now, now),
    )
    agent_id = int(c.lastrowid)
    conn.commit()
    conn.close()
    return agent_id

def list_saved_search_agents() -> List[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT a.id, a.name, a.query, a.cadence, a.max_results, a.created_at, a.updated_at, a.last_run_at,
               r.summary AS last_summary, r.matches_count AS last_matches_count
        FROM saved_search_agents a
        LEFT JOIN saved_search_runs r
          ON r.id = (
              SELECT rr.id FROM saved_search_runs rr
              WHERE rr.agent_id = a.id
              ORDER BY rr.created_at DESC
              LIMIT 1
          )
        ORDER BY a.updated_at DESC
        '''
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def get_saved_search_agent(agent_id: int) -> Optional[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, name, query, cadence, max_results, created_at, updated_at, last_run_at
        FROM saved_search_agents
        WHERE id = ?
        ''',
        (agent_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_saved_search_agent(agent_id: int):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM saved_search_runs WHERE agent_id = ?", (agent_id,))
    c.execute("DELETE FROM saved_search_agents WHERE id = ?", (agent_id,))
    conn.commit()
    conn.close()

def record_saved_search_run(agent_id: int, summary: str, matches_count: int):
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        '''
        INSERT INTO saved_search_runs (agent_id, summary, matches_count, created_at)
        VALUES (?, ?, ?, ?)
        ''',
        (agent_id, summary, int(matches_count), now),
    )
    c.execute(
        "UPDATE saved_search_agents SET last_run_at = ?, updated_at = ? WHERE id = ?",
        (now, now, agent_id),
    )
    conn.commit()
    conn.close()

def get_saved_search_seen_ids(agent_id: int, paper_ids: List[str]) -> set[str]:
    if not paper_ids:
        return set()
    conn = _connect()
    c = conn.cursor()
    seen = set()
    for chunk in _chunked(paper_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        params = [agent_id] + chunk
        c.execute(
            f"SELECT paper_id FROM saved_search_seen WHERE agent_id = ? AND paper_id IN ({placeholders})",
            params,
        )
        seen.update(row[0] for row in c.fetchall())
    conn.close()
    return seen

def mark_saved_search_seen(agent_id: int, paper_ids: List[str]) -> int:
    if not paper_ids:
        return 0
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    rows = [(agent_id, pid, now) for pid in paper_ids]
    c.executemany(
        '''
        INSERT OR IGNORE INTO saved_search_seen (agent_id, paper_id, first_seen_at)
        VALUES (?, ?, ?)
        ''',
        rows,
    )
    inserted = c.rowcount if c.rowcount is not None else 0
    conn.commit()
    conn.close()
    return int(inserted)

def create_digest_run(
    cadence: str,
    title: str,
    summary: str,
    items: List[Dict[str, Any]],
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    source_name: Optional[str] = None,
) -> int:
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    rows = items or []
    c.execute(
        '''
        INSERT INTO digest_runs (cadence, title, summary, paper_count, created_at, source_type, source_id, source_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (cadence, title, summary, len(rows), now, source_type, source_id, source_name),
    )
    digest_id = int(c.lastrowid)

    if rows:
        payload = []
        for idx, item in enumerate(rows, 1):
            contributors = item.get("contributors")
            contributors_json = ""
            if contributors is not None:
                try:
                    contributors_json = json.dumps(contributors)
                except Exception:
                    contributors_json = ""
            payload.append(
                (
                    digest_id,
                    idx,
                    str(item.get("paper_id") or ""),
                    str(item.get("title") or ""),
                    str(item.get("reason") or ""),
                    float(item.get("score") or 0.0),
                    contributors_json,
                )
            )
        c.executemany(
            '''
            INSERT INTO digest_items (digest_id, item_rank, paper_id, title, reason, score, contributors)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            payload,
        )

    conn.commit()
    conn.close()
    return digest_id

def get_digest_run(digest_id: int) -> Optional[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT d.id, d.cadence, d.title, d.summary, d.paper_count, d.created_at,
               d.source_type, d.source_id, d.source_name,
               r.read_at
        FROM digest_runs d
        LEFT JOIN digest_reads r ON r.digest_id = d.id
        WHERE id = ?
        ''',
        (digest_id,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return None

    run = dict(row)
    c.execute(
        '''
        SELECT item_rank, paper_id, title, reason, score, contributors
        FROM digest_items
        WHERE digest_id = ?
        ORDER BY item_rank ASC
        ''',
        (digest_id,),
    )
    items = [dict(r) for r in c.fetchall()]
    for item in items:
        raw = item.get("contributors")
        if raw:
            try:
                item["contributors"] = json.loads(raw)
            except Exception:
                item["contributors"] = None
        else:
            item["contributors"] = None
    run["items"] = items
    run["unread"] = run.get("read_at") in (None, "")
    conn.close()
    return run

def list_digest_runs(limit: int = 20, cadence: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    limit = max(1, min(int(limit), 100))
    if cadence:
        c.execute(
            '''
            SELECT d.id, d.cadence, d.title, d.summary, d.paper_count, d.created_at,
                   d.source_type, d.source_id, d.source_name,
                   r.read_at
            FROM digest_runs d
            LEFT JOIN digest_reads r ON r.digest_id = d.id
            WHERE cadence = ?
            ORDER BY created_at DESC
            LIMIT ?
            ''',
            (cadence, limit),
        )
    else:
        c.execute(
            '''
            SELECT d.id, d.cadence, d.title, d.summary, d.paper_count, d.created_at,
                   d.source_type, d.source_id, d.source_name,
                   r.read_at
            FROM digest_runs d
            LEFT JOIN digest_reads r ON r.digest_id = d.id
            ORDER BY created_at DESC
            LIMIT ?
            ''',
            (limit,),
        )
    runs = [dict(r) for r in c.fetchall()]

    digest_ids = [int(r["id"]) for r in runs]
    items_by_digest: Dict[int, List[Dict[str, Any]]] = {}
    if digest_ids:
        for chunk in _chunked(digest_ids, 300):
            placeholders = ",".join(["?"] * len(chunk))
            c.execute(
                f'''
                SELECT digest_id, item_rank, paper_id, title, reason, score, contributors
                FROM digest_items
                WHERE digest_id IN ({placeholders})
                ORDER BY digest_id DESC, item_rank ASC
                ''',
                chunk,
            )
            for row in c.fetchall():
                item = dict(row)
                raw = item.get("contributors")
                if raw:
                    try:
                        item["contributors"] = json.loads(raw)
                    except Exception:
                        item["contributors"] = None
                else:
                    item["contributors"] = None
                did = int(item.pop("digest_id"))
                items_by_digest.setdefault(did, []).append(item)
    conn.close()

    for run in runs:
        did = int(run["id"])
        run["items"] = items_by_digest.get(did, [])
        run["unread"] = run.get("read_at") in (None, "")
    return runs

def get_latest_digest(cadence: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = _connect()
    c = conn.cursor()
    if cadence:
        c.execute(
            "SELECT id FROM digest_runs WHERE cadence = ? ORDER BY created_at DESC LIMIT 1",
            (cadence,),
        )
    else:
        c.execute("SELECT id FROM digest_runs ORDER BY created_at DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return get_digest_run(int(row[0]))

def get_last_digest_created_at(cadence: str) -> Optional[str]:
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "SELECT created_at FROM digest_runs WHERE cadence = ? ORDER BY created_at DESC LIMIT 1",
        (cadence,),
    )
    row = c.fetchone()
    conn.close()
    return str(row[0]) if row else None

def mark_digest_read(digest_id: int) -> bool:
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        '''
        INSERT INTO digest_reads (digest_id, read_at)
        VALUES (?, ?)
        ON CONFLICT(digest_id) DO UPDATE SET
            read_at = excluded.read_at
        ''',
        (int(digest_id), now),
    )
    conn.commit()
    ok = c.rowcount == 1
    conn.close()
    return ok

def count_unread_digests() -> int:
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        SELECT COUNT(*) FROM digest_runs d
        LEFT JOIN digest_reads r ON r.digest_id = d.id
        WHERE r.digest_id IS NULL
        '''
    )
    row = c.fetchone()
    conn.close()
    return int(row[0]) if row else 0

def create_share_token(kind: str, payload_id: str, ttl_days: Optional[int] = None) -> str:
    import uuid
    token = uuid.uuid4().hex
    conn = _connect()
    c = conn.cursor()
    now = datetime.now()
    expires_at = None
    effective_ttl = SHARE_TOKEN_DEFAULT_TTL_DAYS if ttl_days is None else int(ttl_days)
    if effective_ttl is not None and int(effective_ttl) > 0:
        expires_at = (now + timedelta(days=int(effective_ttl))).isoformat()
    c.execute(
        '''
        INSERT INTO share_tokens (token, kind, payload_id, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (token, str(kind), str(payload_id), now.isoformat(), expires_at),
    )
    conn.commit()
    conn.close()
    return token

def get_share_token(token: str, ttl_days: Optional[int] = None) -> Optional[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        '''
        SELECT token, kind, payload_id, created_at, expires_at
        FROM share_tokens
        WHERE token = ?
        ''',
        (token,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    record = dict(row)
    expires_at = record.get("expires_at")
    if not expires_at:
        effective_ttl = SHARE_TOKEN_DEFAULT_TTL_DAYS if ttl_days is None else int(ttl_days)
        created_at = record.get("created_at")
        if effective_ttl is not None and created_at:
            try:
                created_dt = datetime.fromisoformat(str(created_at))
                expires_at = (created_dt + timedelta(days=int(effective_ttl))).isoformat()
            except Exception:
                expires_at = None
    if expires_at:
        try:
            if datetime.now() >= datetime.fromisoformat(str(expires_at)):
                conn = _connect()
                c = conn.cursor()
                c.execute("DELETE FROM share_tokens WHERE token = ?", (token,))
                conn.commit()
                conn.close()
                return None
        except Exception:
            pass
    return record

def delete_share_token(token: str) -> bool:
    if not token:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM share_tokens WHERE token = ?", (token,))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok

def purge_expired_share_tokens() -> int:
    now_dt = datetime.now()
    now = now_dt.isoformat()
    cutoff = (now_dt - timedelta(days=SHARE_TOKEN_DEFAULT_TTL_DAYS)).isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        '''
        DELETE FROM share_tokens
        WHERE (expires_at IS NOT NULL AND expires_at <= ?)
           OR (expires_at IS NULL AND created_at <= ?)
        ''',
        (now, cutoff),
    )
    conn.commit()
    deleted = c.rowcount
    conn.close()
    return int(deleted or 0)

def db_healthcheck() -> Dict[str, Any]:
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute("SELECT 1")
        c.fetchone()
        conn.close()
        return {"ok": True, "db_path": DB_PATH}
    except Exception as e:
        return {"ok": False, "db_path": DB_PATH, "error": str(e)}

def get_embedding_status() -> Dict[str, Any]:
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(MAX(updated_at), '') FROM paper_embeddings")
        row = c.fetchone()
        conn.close()
        count = int(row[0]) if row else 0
        updated_at = row[1] if row else ""
        return {"count": count, "updated_at": updated_at, "ready": count > 0}
    except Exception as e:
        return {"count": 0, "updated_at": "", "ready": False, "error": str(e)}

def get_fts_status() -> Dict[str, Any]:
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM papers")
        total_row = c.fetchone()
        total = int(total_row[0]) if total_row else 0
        try:
            c.execute("SELECT COUNT(*) FROM paper_fts")
            indexed_row = c.fetchone()
            indexed = int(indexed_row[0]) if indexed_row else 0
            conn.close()
            coverage = (indexed / total) if total else 0.0
            return {
                "ok": True,
                "indexed": indexed,
                "total_papers": total,
                "coverage": round(coverage, 3),
            }
        except sqlite3.OperationalError as e:
            conn.close()
            return {"ok": False, "indexed": 0, "total_papers": total, "coverage": 0.0, "error": str(e)}
    except Exception as e:
        return {"ok": False, "indexed": 0, "total_papers": 0, "coverage": 0.0, "error": str(e)}

def get_papers_by_base_ids(base_ids: List[str]) -> List[Dict[str, Any]]:
    if not base_ids:
        return []
    unique_base_ids = [b for b in dict.fromkeys(str(x) for x in base_ids) if b]
    if not unique_base_ids:
        return []
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    results: List[Dict[str, Any]] = []
    for chunk in _chunked(unique_base_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f"SELECT * FROM papers WHERE arxiv_base_id IN ({placeholders})",
            chunk,
        )
        results.extend(dict(row) for row in c.fetchall())
    conn.close()
    return [_deserialize_paper_dict(r) for r in results]


def get_versions_by_base_ids(base_ids: List[str]) -> Dict[str, List[int]]:
    if not base_ids:
        return {}
    unique_base_ids = [b for b in dict.fromkeys(str(x) for x in base_ids) if b]
    if not unique_base_ids:
        return {}
    conn = _connect()
    c = conn.cursor()
    out: Dict[str, List[int]] = {}
    for chunk in _chunked(unique_base_ids, 400):
        placeholders = ",".join(["?"] * len(chunk))
        c.execute(
            f'''
            SELECT arxiv_base_id, COALESCE(arxiv_version, 1)
            FROM papers
            WHERE arxiv_base_id IN ({placeholders})
            ''',
            chunk,
        )
        for base_id, version in c.fetchall():
            if not base_id:
                continue
            out.setdefault(str(base_id), []).append(int(version or 1))
    conn.close()
    for base_id, versions in out.items():
        versions.sort()
        out[base_id] = versions
    return out

def get_ai_cache(key: str, max_age_seconds: Optional[int] = None) -> Optional[str]:
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT value, updated_at FROM ai_cache WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    value, updated_at = row
    if max_age_seconds is not None:
        try:
            ts = datetime.fromisoformat(updated_at)
            age = (datetime.now() - ts).total_seconds()
            if age > max_age_seconds:
                return None
        except Exception:
            return None
    return value

def set_ai_cache(key: str, value: str):
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        '''
        INSERT INTO ai_cache (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        ''',
        (key, value, now),
    )
    conn.commit()
    conn.close()

def try_acquire_scheduler_lock(name: str, owner_id: str, ttl_seconds: int = 900) -> bool:
    """
    Tries to acquire or renew a distributed lock stored in SQLite.
    Returns True if caller owns the lock after this call.
    """
    ttl_seconds = max(5, int(ttl_seconds))
    now = datetime.now()
    now_iso = now.isoformat()

    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("SELECT owner_id, heartbeat_at FROM scheduler_locks WHERE name = ?", (name,))
        row = c.fetchone()

        if not row:
            c.execute(
                "INSERT OR IGNORE INTO scheduler_locks (name, owner_id, heartbeat_at) VALUES (?, ?, ?)",
                (name, owner_id, now_iso),
            )
            conn.commit()
            if c.rowcount == 1:
                return True
            c.execute("SELECT owner_id, heartbeat_at FROM scheduler_locks WHERE name = ?", (name,))
            row = c.fetchone()

        if not row:
            return False

        current_owner, heartbeat_at = row
        if current_owner == owner_id:
            c.execute(
                "UPDATE scheduler_locks SET heartbeat_at = ? WHERE name = ? AND owner_id = ?",
                (now_iso, name, owner_id),
            )
            conn.commit()
            return c.rowcount == 1

        stale = False
        try:
            hb_dt = datetime.fromisoformat(heartbeat_at)
            stale = (now - hb_dt).total_seconds() > ttl_seconds
        except Exception:
            stale = True

        if not stale:
            return False

        c.execute(
            '''
            UPDATE scheduler_locks
            SET owner_id = ?, heartbeat_at = ?
            WHERE name = ? AND owner_id = ? AND heartbeat_at = ?
            ''',
            (owner_id, now_iso, name, current_owner, heartbeat_at),
        )
        conn.commit()
        return c.rowcount == 1
    finally:
        conn.close()

def heartbeat_scheduler_lock(name: str, owner_id: str) -> bool:
    conn = _connect()
    c = conn.cursor()
    now_iso = datetime.now().isoformat()
    c.execute(
        "UPDATE scheduler_locks SET heartbeat_at = ? WHERE name = ? AND owner_id = ?",
        (now_iso, name, owner_id),
    )
    conn.commit()
    ok = c.rowcount == 1
    conn.close()
    return ok

def release_scheduler_lock(name: str, owner_id: str) -> bool:
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM scheduler_locks WHERE name = ? AND owner_id = ?", (name, owner_id))
    conn.commit()
    ok = c.rowcount == 1
    conn.close()
    return ok

def get_scheduler_lock(name: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT name, owner_id, heartbeat_at FROM scheduler_locks WHERE name = ?", (name,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def _serialize_job_field(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, (int, float, bool)):
        return value
    return str(value)

def _deserialize_job_field(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value

def _deserialize_job_row(row: sqlite3.Row) -> Dict[str, Any]:
    payload = _deserialize_job_field(row["payload"])
    result = _deserialize_job_field(row["result"])
    return {
        "id": row["id"],
        "type": row["type"],
        "payload": payload if isinstance(payload, dict) else (payload or {}),
        "status": row["status"],
        "attempts": int(row["attempts"] or 0),
        "max_attempts": int(row["max_attempts"] or 1),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "result": result,
        "error": row["error"],
        "cancel_requested": bool(row["cancel_requested"]),
        "cancel_requested_at": row["cancel_requested_at"],
    }

def create_job_record(job: Dict[str, Any]) -> None:
    conn = _connect()
    c = conn.cursor()
    payload = _serialize_job_field(job.get("payload") or {})
    result = _serialize_job_field(job.get("result"))
    c.execute(
        '''
        INSERT OR REPLACE INTO job_queue (
            id, type, payload, status, attempts, max_attempts, created_at, updated_at,
            started_at, finished_at, result, error, cancel_requested, cancel_requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            job.get("id"),
            job.get("type"),
            payload,
            job.get("status"),
            int(job.get("attempts") or 0),
            int(job.get("max_attempts") or 1),
            job.get("created_at"),
            job.get("updated_at"),
            job.get("started_at"),
            job.get("finished_at"),
            result,
            job.get("error"),
            1 if job.get("cancel_requested") else 0,
            job.get("cancel_requested_at"),
        ),
    )
    conn.commit()
    conn.close()

def update_job_record(job_id: str, fields: Dict[str, Any]) -> bool:
    if not job_id or not fields:
        return False
    conn = _connect()
    c = conn.cursor()
    columns = []
    params: List[Any] = []
    for key, value in fields.items():
        if key == "id":
            continue
        if key in {"payload", "result"}:
            value = _serialize_job_field(value)
        elif key == "cancel_requested":
            value = 1 if value else 0
        columns.append(f"{key} = ?")
        params.append(value)
    params.append(job_id)
    sql = f"UPDATE job_queue SET {', '.join(columns)} WHERE id = ?"
    c.execute(sql, params)
    conn.commit()
    ok = c.rowcount >= 1
    conn.close()
    return ok

def get_job_record(job_id: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM job_queue WHERE id = ?", (job_id,))
    row = c.fetchone()
    conn.close()
    return _deserialize_job_row(row) if row else None

def list_job_records(limit: int = 200, status: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if status:
        c.execute(
            "SELECT * FROM job_queue WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
            (status, max(1, int(limit))),
        )
    else:
        c.execute(
            "SELECT * FROM job_queue ORDER BY updated_at DESC LIMIT ?",
            (max(1, int(limit)),),
        )
    rows = c.fetchall()
    conn.close()
    return [_deserialize_job_row(r) for r in rows]

def reset_inflight_jobs() -> int:
    """Resets running jobs to queued so they can be retried after restart."""
    conn = _connect()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        '''
        UPDATE job_queue
        SET status = 'queued', updated_at = ?, started_at = NULL
        WHERE status IN ('running', 'canceling')
        ''',
        (now,),
    )
    conn.commit()
    count = c.rowcount
    conn.close()
    return count
