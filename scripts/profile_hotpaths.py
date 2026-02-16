#!/usr/bin/env python3
"""
Profiles hot paths:
1) semantic vector search
2) feed queries
3) inbox queries
4) PDF image extraction
"""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import time
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arxivc import storage, pdf_service


def build_semantic_fixture(db_path: str, num_vectors: int = 3000, dim: int = 384):
    storage.DB_PATH = db_path
    storage.init_db()

    rng = np.random.default_rng(7)
    now = datetime.now().isoformat()
    rows = []
    for i in range(num_vectors):
        vec = rng.standard_normal(dim, dtype=np.float32)
        vec = vec / (np.linalg.norm(vec) + 1e-12)
        rows.append((f"http://arxiv.org/abs/3999.{i:05d}v1", vec.tobytes(), now))

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executemany(
        "INSERT OR REPLACE INTO paper_embeddings (paper_id, embedding, updated_at) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def build_feed_inbox_fixture(db_path: str, num_papers: int = 2500):
    storage.DB_PATH = db_path
    storage.init_db()

    now = datetime.now()
    papers = []
    for i in range(num_papers):
        pid = f"http://arxiv.org/abs/3998.{i:05d}v1"
        published_dt = now - timedelta(minutes=i)
        papers.append(
            {
                "id": pid,
                "title": f"Fixture paper {i}",
                "summary": "Synthetic summary for feed/inbox profiling.",
                "authors": ["Fixture Author", f"Author {i % 17}"],
                "published": published_dt.isoformat(),
                "pdf_url": f"http://arxiv.org/pdf/3998.{i:05d}v1.pdf",
                "categories": ["astro-ph", "gr-qc"] if i % 2 == 0 else ["cs.AI"],
            }
        )
    storage.save_papers(papers)

    for i, row in enumerate(papers):
        pid = row["id"]
        if i % 5 == 0:
            storage.update_interaction(pid, "liked")
        elif i % 11 == 0:
            storage.update_interaction(pid, "dismissed")
        if i % 9 == 0:
            storage.add_bookmark(pid)

    alert_rows = []
    alert_types = ["keyword", "author", "citation", "version"]
    for i in range(min(500, num_papers)):
        pid = papers[i]["id"]
        alert_rows.append(
            {
                "paper_id": pid,
                "alert_type": alert_types[i % len(alert_types)],
                "message": "Fixture alert",
            }
        )
    storage.create_alerts(alert_rows)

    for i in range(min(180, num_papers)):
        pid = papers[i]["id"]
        remind_at = (now - timedelta(hours=(i % 24) + 1)).isoformat()
        storage.add_follow_up(pid, remind_at=remind_at, note="Fixture follow-up")

    for i in range(20):
        items = []
        for j in range(6):
            idx = (i * 13 + j) % num_papers
            p = papers[idx]
            items.append(
                {
                    "paper_id": p["id"],
                    "title": p["title"],
                    "reason": "fixture",
                    "score": 0.5 + (j * 0.05),
                }
            )
        digest_id = storage.create_digest_run(
            cadence="daily",
            title=f"Fixture Digest {i}",
            summary="Fixture digest summary",
            items=items,
        )
        if i % 4 == 0:
            storage.mark_digest_read(digest_id)


def _profile_call(fn, loops: int = 25):
    t0 = time.perf_counter()
    first = fn()
    t1 = time.perf_counter()

    t2 = time.perf_counter()
    for _ in range(loops):
        fn()
    t3 = time.perf_counter()

    cold_ms = (t1 - t0) * 1000
    warm_avg_ms = ((t3 - t2) * 1000) / loops
    return first, cold_ms, warm_avg_ms


def profile_semantic_search():
    with TemporaryDirectory() as td:
        db_path = str(Path(td) / "profile.db")
        build_semantic_fixture(db_path=db_path, num_vectors=3000, dim=384)

        query = np.random.standard_normal(384).astype(np.float32)
        query = query / (np.linalg.norm(query) + 1e-12)

        t0 = time.perf_counter()
        first = storage.search_semantic(query, limit=20)
        t1 = time.perf_counter()

        n = 30
        t2 = time.perf_counter()
        for _ in range(n):
            storage.search_semantic(query, limit=20)
        t3 = time.perf_counter()

        cold_ms = (t1 - t0) * 1000
        warm_avg_ms = ((t3 - t2) * 1000) / n

        print("Semantic Search")
        print(f"  vectors: 3000")
        print(f"  cold call: {cold_ms:.2f} ms")
        print(f"  warm avg ({n} calls): {warm_avg_ms:.2f} ms")
        print(f"  results: {len(first)}")
        print()


def profile_feed_queries():
    with TemporaryDirectory() as td:
        db_path = str(Path(td) / "profile-feed.db")
        build_feed_inbox_fixture(db_path=db_path, num_papers=2500)

        new_fn = lambda: storage.get_papers_page_by_status(
            status="new",
            limit=60,
            offset=0,
            include_total=True,
            include_liked_in_new=True,
        )
        bookmarked_fn = lambda: storage.get_bookmarked_papers_page(
            limit=60,
            offset=0,
            include_total=True,
        )

        (new_items, new_total), cold_new, warm_new = _profile_call(new_fn, loops=20)
        (bookmarked_items, bookmarked_total), cold_book, warm_book = _profile_call(bookmarked_fn, loops=20)

        print("Feed Queries")
        print(f"  papers fixture: 2500")
        print(f"  new feed cold: {cold_new:.2f} ms")
        print(f"  new feed warm avg (20 calls): {warm_new:.2f} ms")
        print(f"  new feed rows: {len(new_items)} / total {new_total}")
        print(f"  bookmarked cold: {cold_book:.2f} ms")
        print(f"  bookmarked warm avg (20 calls): {warm_book:.2f} ms")
        print(f"  bookmarked rows: {len(bookmarked_items)} / total {bookmarked_total}")
        print()


def profile_inbox_queries():
    with TemporaryDirectory() as td:
        db_path = str(Path(td) / "profile-inbox.db")
        build_feed_inbox_fixture(db_path=db_path, num_papers=1800)

        count_alerts_fn = lambda: storage.count_unseen_alerts()
        list_alerts_fn = lambda: storage.get_alerts(limit=120, unseen_only=True)
        count_followups_fn = lambda: storage.count_follow_ups_due()
        list_followups_fn = lambda: storage.list_follow_ups(due_only=True, limit=120)
        count_digests_fn = lambda: storage.count_unread_digests()
        list_digests_fn = lambda: storage.list_digest_runs(limit=80, include_items=False)

        alerts_count, cold_alert_count, warm_alert_count = _profile_call(count_alerts_fn, loops=30)
        alerts_rows, cold_alert_list, warm_alert_list = _profile_call(list_alerts_fn, loops=20)
        follow_count, cold_follow_count, warm_follow_count = _profile_call(count_followups_fn, loops=30)
        follow_rows, cold_follow_list, warm_follow_list = _profile_call(list_followups_fn, loops=20)
        digest_count, cold_digest_count, warm_digest_count = _profile_call(count_digests_fn, loops=30)
        digest_rows, cold_digest_list, warm_digest_list = _profile_call(list_digests_fn, loops=20)

        print("Inbox Queries")
        print(f"  unseen alerts count cold: {cold_alert_count:.2f} ms | warm avg: {warm_alert_count:.2f} ms | value: {alerts_count}")
        print(f"  unseen alerts list cold: {cold_alert_list:.2f} ms | warm avg: {warm_alert_list:.2f} ms | rows: {len(alerts_rows)}")
        print(f"  due follow-ups count cold: {cold_follow_count:.2f} ms | warm avg: {warm_follow_count:.2f} ms | value: {follow_count}")
        print(f"  due follow-ups list cold: {cold_follow_list:.2f} ms | warm avg: {warm_follow_list:.2f} ms | rows: {len(follow_rows)}")
        print(f"  unread digests count cold: {cold_digest_count:.2f} ms | warm avg: {warm_digest_count:.2f} ms | value: {digest_count}")
        print(f"  digest runs list cold: {cold_digest_list:.2f} ms | warm avg: {warm_digest_list:.2f} ms | rows: {len(digest_rows)}")
        print()


def profile_pdf_extraction():
    pdfs = sorted(Path("downloads").glob("*.pdf"))
    if not pdfs:
        print("PDF Extraction")
        print("  skipped: no PDFs found in downloads/")
        print()
        return

    sample = str(pdfs[0])
    t0 = time.perf_counter()
    first = pdf_service.extract_images_from_pdf(sample, max_images=10)
    t1 = time.perf_counter()

    t2 = time.perf_counter()
    second = pdf_service.extract_images_from_pdf(sample, max_images=10)
    t3 = time.perf_counter()

    print("PDF Image Extraction")
    print(f"  file: {sample}")
    print(f"  first call: {(t1 - t0) * 1000:.2f} ms")
    print(f"  cached call: {(t3 - t2) * 1000:.2f} ms")
    print(f"  images: {len(first)} (cached: {len(second)})")
    print()


def main():
    profile_semantic_search()
    profile_feed_queries()
    profile_inbox_queries()
    profile_pdf_extraction()


if __name__ == "__main__":
    main()
