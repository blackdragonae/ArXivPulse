#!/usr/bin/env python3
"""
Profiles hot paths:
1) semantic vector search
2) PDF image extraction
"""

from datetime import datetime
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
    profile_pdf_extraction()


if __name__ == "__main__":
    main()
