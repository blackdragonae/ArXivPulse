import os
import requests
import re
import json
from . import storage

DOWNLOAD_DIR = "downloads"

def sanitize_filename(name: str) -> str:
    """Removes illegal characters from filename."""
    return re.sub(r'[\\/*?:"<>|]', "", name)

def download_pdf(paper_id: str):
    """
    Downloads the PDF for a given paper ID.
    Looks up metadata from DB to get URL and Title.
    """
    # 1. Get paper details
    conn = storage.sqlite3.connect(storage.DB_PATH)
    conn.row_factory = storage.sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT title, pdf_url, authors, published FROM papers WHERE id = ?", (paper_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        print(f"Error: Paper {paper_id} not found in DB.")
        return

    title = row['title']
    pdf_url = row['pdf_url']

    # 2. Get Metadata for naming
    try:
        authors = json.loads(row['authors'])
        first_author = authors[0].split(' ')[-1] if authors else "Unknown"
        # Remove non-ascii
        first_author = re.sub(r'[^\w\-]', '', first_author)
    except:
        first_author = "Unknown"
        
    year = row['published'][:4]
    
    # Title - Take first 5 words to keep it short if needed, or full string.
    # User asked for Surname_Year_Title. Let's use full title but sanitized.
    safe_title = sanitize_filename(title)
    # limit length
    if len(safe_title) > 100:
        safe_title = safe_title[:100].strip()
        
    # Include ID in filename to make retrieval easier
    # ID might contain slashes (e.g. astro-ph/1234), sanitize it.
    safe_id = sanitize_filename(paper_id)
    filename = f"{safe_id}_{first_author}_{year}_{safe_title}.pdf"
    
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    
    # 3. Download
    if os.path.exists(filepath):
        print(f"File already exists: {filepath}")
        return

    print(f"Downloading {pdf_url} to {filepath}...")
    try:
        response = requests.get(pdf_url)
        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                f.write(response.content)
            print(f"Saved: {filepath}")
        else:
            print(f"Failed to download {pdf_url}: Status {response.status_code}")
    except Exception as e:
        print(f"Exception downloading {pdf_url}: {e}")

def organize_library():
    """
    Renames existing files in the downloads folder to the new format.
    Assumes existing files start with 'ID - ...' or are just 'ID.pdf'
    """
    if not os.path.exists(DOWNLOAD_DIR):
        print("No downloads directory found.")
        return

    print("Organizing library...")
    files = os.listdir(DOWNLOAD_DIR)
    print(f"Scanning {len(files)} files...")
    
    conn = storage.sqlite3.connect(storage.DB_PATH)
    conn.row_factory = storage.sqlite3.Row
    c = conn.cursor()
    
    count = 0
    for filename in files:
        if not filename.endswith('.pdf'):
            continue
            
        row = None
        current_safe_title = ""
        
        # Strategy 1: Find ID in filename
        match_id = re.search(r'(\d{4}\.\d{4,5})', filename)
        if match_id:
            paper_id = match_id.group(1)
            c.execute("SELECT * FROM papers WHERE id LIKE ?", (f"%{paper_id}%",))
            row = c.fetchone()
        
        # Strategy 2: If starts with Unknown, try to match Title
        # Format: Unknown_YYYY_Title.pdf
        if not row and filename.startswith("Unknown_"):
            parts = filename.replace('.pdf', '').split('_')
            if len(parts) >= 3:
                # parts[0] = Author (Unknown), parts[1] = Year, parts[2:] = Title
                candidate_title = "_".join(parts[2:])
                # The title in DB might have special chars, but filename is sanitized.
                # We can try to match sanitized title or just approximate.
                # Let's try simple LIKE. Title spaces might be underscores? 
                # sanitize_function replaced chars with empty string.
                # It did NOT start replacing spaces with underscores in my previous code!
                # Wait, "safe_title = sanitize_filename(title)". 
                # sanitize_function: re.sub(r'[\\/*?:"<>|]', "", name)
                # It keeps spaces!
                # So the filename should differ only by disallowed chars.
                # Let's try to match 
                
                # We need to find a paper where sanitize(title) == candidate_title (ignoring case)
                # This handles the cleanup.
                
                # Fetch all papers (expensive but 71 files is fine)
                # Optimize: Get only title and authors
                c.execute("SELECT title, authors, published FROM papers")
                all_papers = c.fetchall()
                
                for p in all_papers:
                    t = sanitize_filename(p['title'])
                    if len(t) > 100: t = t[:100].strip()
                    
                    if t == candidate_title:
                        row = p
                        break
        
        if not row:
            print(f"Skipping {filename} (Metadata not found)")
            continue
            
        # Construct new name
        try:
            authors = json.loads(row['authors'])
            first_author = authors[0].split(' ')[-1] if authors else "Unknown"
            first_author = re.sub(r'[^\w\-]', '', first_author)
        except:
            first_author = "Unknown"
            
        year = row['published'][:4]
        safe_title = sanitize_filename(row['title'])
        if len(safe_title) > 100:
            safe_title = safe_title[:100].strip()
            
        new_name = f"{first_author}_{year}_{safe_title}.pdf"
        
        if new_name.startswith("Unknown_") and not filename.startswith("Unknown_"):
             # Don't rename TO Unknown if we have something else, unless we really must.
             pass
             
        old_path = os.path.join(DOWNLOAD_DIR, filename)
        new_path = os.path.join(DOWNLOAD_DIR, new_name)
        
        if old_path != new_path:
            try:
                os.rename(old_path, new_path)
                print(f"Renamed: {filename} -> {new_name}")
                count += 1
            except OSError as e:
                print(f"Error renaming {filename}: {e}")
    
    conn.close()
    print(f"Library organized. Renamed {count} files.")
