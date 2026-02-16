from pathlib import Path

import pytest

from arxivc import storage


@pytest.fixture()
def isolated_db(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "storage_filters.db"
    monkeypatch.setattr(storage, "DB_PATH", str(db_path))
    monkeypatch.setattr(storage, "_DB_INITIALIZED_PATH", None)
    monkeypatch.setattr(storage, "_DB_INITIALIZED_SIGNATURE", None)
    storage.init_db()
    return db_path


def _paper(pid: str, published: str, title: str, summary: str = ""):
    return {
        "id": pid,
        "title": title,
        "summary": summary,
        "authors": ["Test Author"],
        "published": published,
        "pdf_url": f"https://arxiv.org/pdf/{pid.split('/')[-1]}.pdf",
        "categories": ["quant-ph"],
    }


def test_get_papers_page_by_status_can_include_liked_in_new(isolated_db):
    p_new = _paper(
        "http://arxiv.org/abs/2602.10001v1",
        "2026-02-12T01:00:00+00:00",
        "New-only paper",
    )
    p_liked = _paper(
        "http://arxiv.org/abs/2602.10002v1",
        "2026-02-12T02:00:00+00:00",
        "Liked-and-new feed paper",
    )
    storage.save_papers([p_new, p_liked])
    storage.update_interaction(p_liked["id"], "liked")

    rows_default, total_default = storage.get_papers_page_by_status(
        status="new",
        include_liked_in_new=False,
        include_total=True,
    )
    rows_with_liked, total_with_liked = storage.get_papers_page_by_status(
        status="new",
        include_liked_in_new=True,
        include_total=True,
    )

    ids_default = {row["id"] for row in rows_default}
    ids_with_liked = {row["id"] for row in rows_with_liked}

    assert p_new["id"] in ids_default
    assert p_liked["id"] not in ids_default
    assert p_new["id"] in ids_with_liked
    assert p_liked["id"] in ids_with_liked
    assert total_default == 1
    assert total_with_liked == 2


def test_get_papers_page_by_status_applies_date_and_text_filters(isolated_db):
    p1 = _paper(
        "http://arxiv.org/abs/2602.20001v1",
        "2026-02-11T00:00:00+00:00",
        "Quantum lensing methods",
        "A compact abstract",
    )
    p2 = _paper(
        "http://arxiv.org/abs/2602.20002v1",
        "2026-02-12T00:00:00+00:00",
        "Cosmology constraints",
        "Dark energy summary",
    )
    storage.save_papers([p1, p2])

    date_rows, date_total = storage.get_papers_page_by_status(
        status="new",
        published_date="2026-02-12",
        include_total=True,
    )
    query_rows, query_total = storage.get_papers_page_by_status(
        status="new",
        query_text="quantum",
        include_total=True,
    )

    assert {row["id"] for row in date_rows} == {p2["id"]}
    assert date_total == 1
    assert {row["id"] for row in query_rows} == {p1["id"]}
    assert query_total == 1


def test_get_papers_page_by_status_dedupe_latest_keeps_highest_version(isolated_db):
    v1 = _paper(
        "http://arxiv.org/abs/2602.30001v1",
        "2026-02-10T00:00:00+00:00",
        "Versioned paper v1",
    )
    v2 = _paper(
        "http://arxiv.org/abs/2602.30001v2",
        "2026-02-12T00:00:00+00:00",
        "Versioned paper v2",
    )
    other = _paper(
        "http://arxiv.org/abs/2602.30002v1",
        "2026-02-11T00:00:00+00:00",
        "Independent paper",
    )
    storage.save_papers([v1, v2, other])

    rows, total = storage.get_papers_page_by_status(
        status="new",
        dedupe_latest=True,
        include_total=True,
        limit=10,
        offset=0,
    )

    ids = {row["id"] for row in rows}
    assert v2["id"] in ids
    assert other["id"] in ids
    assert v1["id"] not in ids
    assert total == 2
