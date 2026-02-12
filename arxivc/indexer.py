import os
import re
import traceback
from pypdf import PdfReader
from . import storage

DOWNLOAD_DIR = "downloads"

def extract_text_from_pdf(filepath: str) -> str:
    try:
        reader = PdfReader(filepath)
        text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
        return text
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return ""

def get_paper_id_from_filename(filename: str):
    # Try ID regex first
    match = re.search(r'(\d{4}\.\d{4,5})', filename)
    if match:
        return match.group(1)
    
    # If using Author_Year_Title strategy where ID is lost...
    # We might need to look up by Title?
    # This is tricky because we only have title in filename.
    # But wait, we store the file path -> paper ID in DB? No.
    # We store metadata in `papers` table.
    # If the file is `Author_Year_Title`, we stripped the ID.
    # BUT, we can use the same lookup logic we used in `organize_library` to find the ID!
    # Or, we can iterate all papers in DB, compute their expected filename, and match? Expensive.
    # Better: reverse lookup by title.
    
    # Simplification: Assume invalid ID if regex fails for now, 
    # BUT our `organize_library` just RENAME papers to NOT have ID.
    # So regex will fail.
    # We MUST support title lookup.
    
    if filename.startswith("Unknown_") or "_" in filename:
        # Try to extract title
        parts = filename.replace('.pdf','').split('_')
        if len(parts) >= 3:
            candidate_title = "_".join(parts[2:]) # Roughly the title
            # Search DB
            # We need a `get_paper_by_fuzzy_title`?
            # Or just brute force search title since we have few papers.
            return find_id_by_title(candidate_title)
            
    return None

def find_id_by_title(candidate_title_sanitized):
    # This assumes we can reproduce the sanitization
    # Or strict match.
    # Let's iterate all papers (cache them).
    
    conn = storage.sqlite3.connect(storage.DB_PATH)
    conn.row_factory = storage.sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, title FROM papers")
    rows = c.fetchall()
    conn.close()
    
    # Naive search
    from .downloader import sanitize_filename
    
    for r in rows:
        t = sanitize_filename(r['title'])
        if len(t) > 100: t = t[:100].strip()
        
        if t == candidate_title_sanitized:
            return r['id']
            
    return None

def build_index():
    if not os.path.exists(DOWNLOAD_DIR):
        print("No downloads found.")
        return

    print("Indexing library...")
    files = os.listdir(DOWNLOAD_DIR)
    
    # Optimization: Get set of already indexed IDs?
    # Actually, FTS doesn't expose easy ID list? 
    # We can `SELECT paper_id FROM paper_fts`.
    conn = storage.sqlite3.connect(storage.DB_PATH)
    c = conn.cursor()
    try:
        c.execute("SELECT paper_id FROM paper_fts")
        indexed_ids = set(r[0] for r in c.fetchall())
    except:
        indexed_ids = set()
    conn.close()
    
    count = 0
    for f in files:
        if not f.endswith('.pdf'):
            continue
            
        pid = get_paper_id_from_filename(f)
        if not pid:
            print(f"Skipping {f} (Cannot determine Paper ID)")
            continue
            
        if pid in indexed_ids:
            continue
            
        print(f"Indexing {f}...")
        path = os.path.join(DOWNLOAD_DIR, f)
        text = extract_text_from_pdf(path)
        if text:
            # Clean text a bit?
            text = re.sub(r'\s+', ' ', text).strip()
            storage.index_paper_text(pid, text)
            count += 1
            
    print(f"Indexed {count} new papers.")
