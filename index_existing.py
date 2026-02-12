
import sqlite3
import json
import sys
import os

sys.path.append(os.getcwd())
from arxivc import storage, embeddings
from tqdm import tqdm

def main():
    print("Initializing DB...")
    storage.init_db()
    
    print("Loading Model...")
    embeddings.get_model()
    
    # Connect
    conn = sqlite3.connect(storage.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT id, title, summary FROM papers")
    rows = c.fetchall()
    
    print(f"Found {len(rows)} papers. Indexing...")
    
    count = 0
    for row in tqdm(rows):
        pid = row['id']
        text = f"{row['title']} {row['summary']}"
        
        # Check if already indexed?
        # Maybe Force Update to be safe
        vec = embeddings.generate_embedding(text)
        if vec.size > 0:
            storage.save_embedding(pid, vec)
            count += 1
            
    print(f"Successfully indexed {count} papers.")
    conn.close()

if __name__ == "__main__":
    main()
