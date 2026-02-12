#!/usr/bin/env python3
"""
End-to-end API smoke checks for key workflows:
- fetch
- search
- bookmark toggle
- synthesize
- pdf serving
- reading plan (today/history/actions)
- version updates
- weekly review

This uses a tiny in-process ASGI requester (no external test client dependency).
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import quote, urlencode
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arxivc import storage, server


SAMPLE_PAPERS = [
    {
        "id": "http://arxiv.org/abs/2999.00001v1",
        "title": "Quantum Cosmology with Fast Inference",
        "summary": "We study quantum cosmology and introduce a fast inference method.",
        "authors": ["Ada Lovelace", "Alan Turing"],
        "published": "2026-02-03T00:00:00+00:00",
        "pdf_url": "https://arxiv.org/pdf/2999.00001v1.pdf",
        "categories": ["quant-ph", "cs.AI"],
    },
    {
        "id": "http://arxiv.org/abs/2999.00002v1",
        "title": "Dark Energy Constraints with Sparse Models",
        "summary": "A sparse modeling approach for dark energy constraints.",
        "authors": ["Grace Hopper"],
        "published": "2026-02-03T00:00:00+00:00",
        "pdf_url": "https://arxiv.org/pdf/2999.00002v1.pdf",
        "categories": ["astro-ph.CO"],
    },
]

SAMPLE_NEW_VERSION = {
    "id": "http://arxiv.org/abs/2999.00001v2",
    "title": "Quantum Cosmology with Fast Inference (Revised)",
    "summary": "Revised method and expanded experiments for faster inference.",
    "authors": ["Ada Lovelace", "Alan Turing"],
    "published": "2026-02-05T00:00:00+00:00",
    "pdf_url": "https://arxiv.org/pdf/2999.00001v2.pdf",
    "categories": ["quant-ph", "cs.AI"],
}


def check(condition: bool, label: str):
    if not condition:
        raise AssertionError(label)
    print(f"[OK] {label}")


async def asgi_request(method: str, path: str, params=None, json_body=None):
    query_string = urlencode(params or {}, doseq=True).encode("utf-8")
    body = json.dumps(json_body).encode("utf-8") if json_body is not None else b""

    headers = [(b"host", b"localtest")]
    if body:
        headers.append((b"content-type", b"application/json"))
        headers.append((b"content-length", str(len(body)).encode("utf-8")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": headers,
    }

    sent_body = False
    messages = []

    async def receive():
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    await server.app(scope, receive, send)

    status_code = 500
    resp_headers = {}
    body_chunks = []
    for message in messages:
        if message["type"] == "http.response.start":
            status_code = message["status"]
            resp_headers = {
                k.decode("utf-8").lower(): v.decode("utf-8")
                for k, v in message.get("headers", [])
            }
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b""))

    raw = b"".join(body_chunks)
    data = None
    if raw:
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = raw

    return status_code, resp_headers, data


def main():
    original_db = storage.DB_PATH
    fake_pdf = None

    try:
        with TemporaryDirectory() as td:
            storage.DB_PATH = str(Path(td) / "smoke.db")
            storage.init_db()

            with (
                patch("arxivc.server.client.fetch_latest_daily_batch", return_value=(SAMPLE_PAPERS, "2026-02-04")),
                patch("arxivc.server.client.fetch_papers_by_date", return_value=SAMPLE_PAPERS),
                patch("arxivc.server.background_index", lambda papers: None),
                patch("arxivc.server.enrich_citations", lambda paper_ids: None),
                patch("arxivc.server.ai_service.generate_literature_review", return_value="# Smoke Review\n\nLooks good."),
                patch("arxivc.server.downloader.download_pdf", lambda paper_id: None),
                patch("arxivc.server.background_retrain", lambda: None),
            ):
                status, _, payload = asyncio.run(
                    asgi_request("POST", "/api/fetch", json_body={"max_results": 20})
                )
                check(status == 200, "POST /api/fetch returns 200")
                check(payload.get("fetched") == 2, "fetch reports 2 papers")

                for p in SAMPLE_PAPERS:
                    storage.index_paper_text(p["id"], f"{p['title']} {p['summary']}")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/search", params={"q": "quantum"})
                )
                check(status == 200, "GET /api/search returns 200")
                check(isinstance(payload, list) and len(payload) >= 1, "search returns at least 1 match")

                short_id = SAMPLE_PAPERS[0]["id"].split("/")[-1]
                encoded_short = quote(short_id, safe="")

                status, _, _ = asyncio.run(
                    asgi_request(
                        "POST",
                        f"/api/papers/{encoded_short}/bookmark",
                        json_body={"active": True},
                    )
                )
                check(status == 200, "bookmark enable returns 200")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/papers", params={"status": "bookmarked"})
                )
                check(status == 200, "GET bookmarked returns 200")
                ids = {p["id"] for p in payload}
                check(SAMPLE_PAPERS[0]["id"] in ids, "bookmarked paper appears in bookmarked list")

                status, _, _ = asyncio.run(
                    asgi_request(
                        "POST",
                        f"/api/papers/{encoded_short}/bookmark",
                        json_body={"active": False},
                    )
                )
                check(status == 200, "bookmark disable returns 200")

                # Add a newer arXiv version to verify version-update behavior (v1 -> v2).
                storage.save_papers([SAMPLE_NEW_VERSION])
                storage.update_paper_structure(
                    SAMPLE_PAPERS[0]["id"],
                    {
                        "problem": "Original baseline framing.",
                        "method": "Initial approach.",
                        "dataset": "Small benchmark",
                        "results": "Initial metrics",
                        "limitations": "Limited eval",
                    },
                )
                storage.update_paper_structure(
                    SAMPLE_NEW_VERSION["id"],
                    {
                        "problem": "Original baseline framing.",
                        "method": "Improved approach with ablations.",
                        "dataset": "Small benchmark + extended benchmark",
                        "results": "Improved metrics",
                        "limitations": "Still limited domain transfer",
                    },
                )

                status, _, _ = asyncio.run(
                    asgi_request(
                        "POST",
                        f"/api/papers/{encoded_short}/rate",
                        json_body={"status": "liked"},
                    )
                )
                check(status == 200, "like action returns 200")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/synthesize",
                        json_body={"paper_ids": [SAMPLE_PAPERS[0]["id"], SAMPLE_PAPERS[1]["id"]]},
                    )
                )
                check(status == 200, "POST /api/synthesize returns 200")
                check("review" in payload, "synthesize payload contains review")

                downloads = Path("downloads")
                downloads.mkdir(exist_ok=True)
                fake_pdf = downloads / f"{short_id}.pdf"
                fake_pdf.write_bytes(b"%PDF-1.4\n% smoke\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")

                status, headers, _ = asyncio.run(
                    asgi_request("GET", f"/api/papers/{encoded_short}/pdf")
                )
                check(status == 200, "GET /api/papers/{id}/pdf returns 200")
                check("application/pdf" in headers.get("content-type", ""), "pdf endpoint returns application/pdf")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/reading-plan/today")
                )
                check(status == 200, "GET /api/reading-plan/today returns 200")
                check(isinstance(payload, dict) and "items" in payload, "reading plan today payload has items field")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/reading-plan/generate",
                        json_body={"total_minutes": 45, "max_items": 5, "refresh": True},
                    )
                )
                check(status == 200, "POST /api/reading-plan/generate returns 200")
                check(str(payload.get("date") or ""), "generated reading plan includes date")
                plan_date = payload.get("date")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/reading-plan/history", params={"limit": 5})
                )
                check(status == 200, "GET /api/reading-plan/history returns 200")
                check(int(payload.get("count") or 0) >= 1, "reading plan history has at least one snapshot")

                status, _, payload = asyncio.run(
                    asgi_request("GET", f"/api/reading-plan/{plan_date}")
                )
                check(status == 200, "GET /api/reading-plan/{date} returns 200")
                check(str(payload.get("date") or "") == str(plan_date), "dated reading plan returns requested date")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/reading-plan/action",
                        json_body={"paper_id": SAMPLE_PAPERS[0]["id"], "action": "done"},
                    )
                )
                check(status == 200, "POST /api/reading-plan/action done returns 200")
                check(payload.get("action") == "done", "reading plan action done applied")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/reading-plan/action",
                        json_body={
                            "paper_id": SAMPLE_PAPERS[1]["id"],
                            "action": "defer",
                            "defer_days": 2,
                            "reason": "smoke defer",
                        },
                    )
                )
                check(status == 200, "POST /api/reading-plan/action defer returns 200")
                check(payload.get("action") == "defer", "reading plan action defer applied")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/reading-plan/progress", params={"days": 14})
                )
                check(status == 200, "GET /api/reading-plan/progress returns 200")
                check(isinstance(payload, dict) and "streak_days" in payload, "reading plan progress payload has streak")

                # Ensure watchlist scope has a tracked base-paper (bookmark) before checking updates.
                status, _, _ = asyncio.run(
                    asgi_request(
                        "POST",
                        f"/api/papers/{encoded_short}/bookmark",
                        json_body={"active": True},
                    )
                )
                check(status == 200, "bookmark re-enable returns 200")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/version-updates", params={"scope": "watchlist", "limit": 10})
                )
                check(status == 200, "GET /api/version-updates returns 200")
                check(int(payload.get("count") or 0) >= 1, "version updates returns at least one update")
                first = (payload.get("items") or [{}])[0]
                check(int(first.get("to_version") or 0) > int(first.get("from_version") or 0), "version update advances version")
                base_id = first.get("arxiv_base_id")
                initial_active = int(payload.get("active_count") or payload.get("count") or 0)

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/version-updates/count", params={"scope": "watchlist"})
                )
                check(status == 200, "GET /api/version-updates/count returns 200")
                check(int(payload.get("active") or 0) >= 1, "version updates count reports active updates")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/version-updates/action",
                        json_body={"action": "snooze", "arxiv_base_id": base_id, "snooze_days": 2},
                    )
                )
                check(status == 200, "POST /api/version-updates/action snooze returns 200")
                check(payload.get("success") is True, "version update snooze action applied")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/version-updates", params={"scope": "watchlist", "limit": 10})
                )
                check(status == 200, "GET /api/version-updates after snooze returns 200")
                active_after_snooze = int(payload.get("active_count") or payload.get("count") or 0)
                check(active_after_snooze <= max(0, initial_active - 1), "snoozed update is hidden from active inbox")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/version-updates/action",
                        json_body={"action": "clear", "arxiv_base_id": base_id},
                    )
                )
                check(status == 200, "POST /api/version-updates/action clear returns 200")
                check(payload.get("success") is True, "version update clear action applied")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/reading-plan/action",
                        json_body={"paper_id": SAMPLE_PAPERS[0]["id"], "action": "undo_done"},
                    )
                )
                check(status == 200, "POST /api/reading-plan/action undo_done returns 200")
                check(payload.get("action") == "undo_done", "reading plan undo_done applied")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/reading-plan/action",
                        json_body={"paper_id": SAMPLE_PAPERS[1]["id"], "action": "undefer"},
                    )
                )
                check(status == 200, "POST /api/reading-plan/action undefer returns 200")
                check(payload.get("action") == "undefer", "reading plan undefer applied")

                # Seed unified-inbox entities across all kinds.
                due_follow = storage.add_follow_up(
                    SAMPLE_PAPERS[0]["id"],
                    (datetime.now() - timedelta(days=1)).isoformat(),
                    "smoke follow-up",
                )
                digest_id = storage.create_digest_run(
                    "daily",
                    "Smoke Digest",
                    "Digest summary",
                    [
                        {
                            "paper_id": SAMPLE_PAPERS[0]["id"],
                            "title": SAMPLE_PAPERS[0]["title"],
                            "reason": "Smoke ranking item",
                            "score": 0.91,
                        }
                    ],
                )
                storage.create_alerts(
                    [
                        {
                            "paper_id": SAMPLE_PAPERS[0]["id"],
                            "alert_type": "smoke",
                            "message": "smoke alert",
                        }
                    ]
                )

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/inbox/count", params={"version_scope": "watchlist", "version_days": 30})
                )
                check(status == 200, "GET /api/inbox/count returns 200")
                check("counts" in payload and "total" in payload, "inbox count payload includes counts and total")
                check(int(payload.get("total") or 0) >= 1, "inbox count total is non-zero")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/inbox/count", params={"version_scope": "watchlist", "version_days": 30, "kinds": "alert,digest"})
                )
                check(status == 200, "GET /api/inbox/count with kinds filter returns 200")
                check(isinstance(payload.get("counts"), dict), "filtered inbox count includes counts object")
                check(payload.get("counts", {}).get("version_updates", 0) == 0, "filtered inbox count suppresses non-requested version updates")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/inbox/unified", params={"limit": 30, "version_scope": "watchlist", "version_days": 30})
                )
                check(status == 200, "GET /api/inbox/unified returns 200")
                check(isinstance(payload.get("items"), list), "unified inbox returns items list")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "GET",
                        "/api/inbox/unified",
                        params={"limit": 30, "version_scope": "watchlist", "version_days": 30, "kinds": "alert,digest"},
                    )
                )
                check(status == 200, "GET /api/inbox/unified with kinds filter returns 200")
                filtered_items = payload.get("items") or []
                check(all(item.get("kind") in {"alert", "digest"} for item in filtered_items), "filtered unified inbox only includes requested kinds")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "GET",
                        "/api/inbox/unified",
                        params={"limit": 30, "version_scope": "watchlist", "version_days": 30, "sort": "priority"},
                    )
                )
                check(status == 200, "GET /api/inbox/unified?sort=priority returns 200")
                priority_items = payload.get("items") or []
                if priority_items:
                    check("priority_score" in priority_items[0], "priority-sorted inbox includes priority_score")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "GET",
                        "/api/inbox/focus",
                        params={"limit": 8, "version_scope": "watchlist", "version_days": 30},
                    )
                )
                check(status == 200, "GET /api/inbox/focus returns 200")
                check(payload.get("mode") == "focus", "focus inbox payload mode is focus")
                check(int(payload.get("count") or 0) <= 8, "focus inbox honors limit")

                unseen_alerts = storage.get_alerts(limit=10, unseen_only=True)
                alert_id = int((unseen_alerts[0] if unseen_alerts else {}).get("id") or 0)
                check(alert_id > 0, "have unseen alert for inbox action test")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/inbox/action",
                        json_body={"kind": "alert", "action": "seen", "alert_id": alert_id},
                    )
                )
                check(status == 200, "POST /api/inbox/action alert seen returns 200")
                check(payload.get("success") is True, "inbox alert seen action applied")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/inbox/action",
                        json_body={"kind": "version_update", "action": "reviewed", "arxiv_base_id": base_id},
                    )
                )
                check(status == 200, "POST /api/inbox/action version reviewed returns 200")
                check(payload.get("success") is True, "inbox version action applied")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/inbox/action",
                        json_body={"kind": "follow_up", "action": "snooze", "follow_id": due_follow.get("id"), "snooze_days": 2},
                    )
                )
                check(status == 200, "POST /api/inbox/action follow-up snooze returns 200")
                check(payload.get("success") is True, "inbox follow-up snooze action applied")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/inbox/action",
                        json_body={"kind": "digest", "action": "read", "digest_id": digest_id},
                    )
                )
                check(status == 200, "POST /api/inbox/action digest read returns 200")
                check(payload.get("success") is True, "inbox digest action applied")

                due_follow_bulk = storage.add_follow_up(
                    SAMPLE_PAPERS[1]["id"],
                    (datetime.now() - timedelta(days=1)).isoformat(),
                    "smoke bulk follow-up",
                )
                bulk_digest_id = storage.create_digest_run(
                    "daily",
                    "Smoke Bulk Digest",
                    "Bulk digest summary",
                    [
                        {
                            "paper_id": SAMPLE_PAPERS[1]["id"],
                            "title": SAMPLE_PAPERS[1]["title"],
                            "reason": "Bulk smoke item",
                            "score": 0.77,
                        }
                    ],
                )
                storage.create_alerts(
                    [
                        {
                            "paper_id": SAMPLE_PAPERS[1]["id"],
                            "alert_type": "smoke_bulk",
                            "message": "smoke bulk alert",
                        }
                    ]
                )
                bulk_alerts = [a for a in storage.get_alerts(limit=20, unseen_only=True) if a.get("alert_type") == "smoke_bulk"]
                bulk_alert_id = int((bulk_alerts[0] if bulk_alerts else {}).get("id") or 0)
                check(bulk_alert_id > 0, "have dedicated alert for bulk action test")
                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/inbox/bulk-action",
                        json_body={
                            "items": [
                                {"kind": "alert", "action": "seen", "alert_id": bulk_alert_id},
                                {"kind": "follow_up", "action": "done", "follow_id": due_follow_bulk.get("id")},
                                {"kind": "digest", "action": "read", "digest_id": bulk_digest_id},
                                {"kind": "version_update", "action": "reviewed", "arxiv_base_id": base_id},
                            ]
                        },
                    )
                )
                check(status == 200, "POST /api/inbox/bulk-action returns 200")
                check(int(payload.get("failure_count") or 0) == 0, "bulk inbox action has zero failures")
                check(int(payload.get("success_count") or 0) >= 4, "bulk inbox action applies all requested items")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/inbox-rules",
                        json_body={
                            "name": "Smoke dark label",
                            "scope": "papers",
                            "action": "label",
                            "label": "smoke-dark",
                            "keywords": ["dark"],
                            "authors": [],
                            "venues": [],
                            "enabled": True,
                            "target_kind": None,
                            "snooze_days": 3,
                        },
                    )
                )
                check(status == 200, "POST /api/inbox-rules returns 200")
                rule_id = str(payload.get("id") or "")
                check(bool(rule_id), "created inbox rule has id")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/inbox-rules/preview",
                        json_body={"scope": "papers", "dry_run": True, "limit": 100},
                    )
                )
                check(status == 200, "POST /api/inbox-rules/preview returns 200")
                check("results" in payload and isinstance(payload.get("results"), list), "inbox rules preview returns results list")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/inbox-rules/apply",
                        json_body={"scope": "papers", "dry_run": False, "limit": 100},
                    )
                )
                check(status == 200, "POST /api/inbox-rules/apply returns 200")
                check("matched" in payload and "applied" in payload, "inbox rules apply returns counters")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/inbox-rules/audit", params={"limit": 50})
                )
                check(status == 200, "GET /api/inbox-rules/audit returns 200")
                check(int(payload.get("count") or 0) >= 1, "inbox rule audit has entries")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/inbox-rules/diagnostics", params={"limit": 80})
                )
                check(status == 200, "GET /api/inbox-rules/diagnostics returns 200")
                check(isinstance(payload.get("summary"), dict), "inbox rules diagnostics returns summary")

                day_run_body = {
                    "date": "2026-02-06",
                    "force": True,
                    "weekend_policy": "run",
                    "run_fetch": True,
                    "run_rules": True,
                    "run_reading_plan": True,
                    "run_inbox_refresh": True,
                    "run_inbox_rules_scope": "all",
                    "refresh_reading_plan": True,
                }
                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/day/run",
                        json_body=day_run_body,
                    )
                )
                check(status == 200, "POST /api/day/run returns 200")
                check("fetch" in payload and "inbox" in payload and "reading_plan" in payload, "day run payload includes fetch/inbox/reading_plan")
                run_id = int(payload.get("run_id") or 0)
                check(run_id > 0, "day run returns persisted run_id")
                check(payload.get("idempotent_replay") is False, "first day run response is not replayed")
                run_key = str(payload.get("idempotency_key") or "")
                check(bool(run_key), "day run returns idempotency key")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/day/run",
                        json_body=day_run_body,
                    )
                )
                check(status == 200, "POST /api/day/run duplicate returns 200")
                check(payload.get("idempotent_replay") is True, "duplicate day run returns replay response")
                check(str(payload.get("idempotency_key") or "") == run_key, "duplicate day run keeps same idempotency key")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/day/runs", params={"limit": 10})
                )
                check(status == 200, "GET /api/day/runs returns 200")
                check(isinstance(payload.get("items"), list) and len(payload.get("items") or []) >= 1, "day run history returns at least one item")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        "/api/day/presets",
                        json_body={
                            "name": "Smoke preset",
                            "description": "Preset for smoke tests",
                            "options": day_run_body,
                        },
                    )
                )
                check(status == 200, "POST /api/day/presets returns 200")
                preset_id = int(payload.get("id") or 0)
                check(preset_id > 0, "created day-run preset has id")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/day/presets", params={"limit": 20})
                )
                check(status == 200, "GET /api/day/presets returns 200")
                check(any(int(item.get("id") or 0) == preset_id for item in (payload.get("items") or [])), "day-run presets list includes created preset")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "PUT",
                        f"/api/day/presets/{preset_id}",
                        json_body={
                            "name": "Smoke preset updated",
                            "description": "Updated smoke preset",
                            "options": {**day_run_body, "run_rules": False},
                        },
                    )
                )
                check(status == 200, "PUT /api/day/presets/{id} returns 200")
                check(str(payload.get("name") or "").startswith("Smoke preset"), "updated day-run preset returns updated name")

                status, _, payload = asyncio.run(
                    asgi_request(
                        "POST",
                        f"/api/day/presets/{preset_id}/run",
                    )
                )
                check(status == 200, "POST /api/day/presets/{id}/run returns 200")
                check(int(payload.get("preset_id") or 0) == preset_id, "preset run response includes preset_id")

                status, _, payload = asyncio.run(
                    asgi_request("POST", f"/api/day/run/{run_id}/retry")
                )
                check(status == 200, "POST /api/day/run/{run_id}/retry returns 200")
                check(int(payload.get("retry_of") or 0) == run_id, "day run retry response includes retry_of id")

                status, _, payload = asyncio.run(
                    asgi_request("DELETE", f"/api/day/presets/{preset_id}")
                )
                check(status == 200, "DELETE /api/day/presets/{id} returns 200")
                check(payload.get("success") is True, "day-run preset delete reports success")

                status, _, payload = asyncio.run(
                    asgi_request("GET", "/api/weekly-review", params={"days": 7})
                )
                check(status == 200, "GET /api/weekly-review returns 200")
                check("reading" in payload and "version_updates" in payload, "weekly review payload contains reading and version updates")

                status, _, payload = asyncio.run(
                    asgi_request("POST", "/api/weekly-review/share", params={"days": 7})
                )
                check(status == 200, "POST /api/weekly-review/share returns 200")
                share_token = str(payload.get("token") or "")
                check(bool(share_token), "weekly review share returns token")

                status, _, payload = asyncio.run(
                    asgi_request("GET", f"/api/share/{quote(share_token, safe='')}")
                )
                check(status == 200, "GET /api/share/{weekly_review_token} returns 200")
                check(payload.get("kind") == "weekly_review", "shared payload kind is weekly_review")

        print("\nSmoke checks passed.")
    finally:
        if fake_pdf and fake_pdf.exists():
            fake_pdf.unlink()
        storage.DB_PATH = original_db


if __name__ == "__main__":
    main()
