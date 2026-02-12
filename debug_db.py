
from arxivc import storage
import json

def test_db_logic():
    print("Initializing DB...")
    storage.init_db()
    
    query = "Test"
    print(f"Searching papers with query: '{query}'")
    
    search_results = storage.search_papers(query, limit=5)
    print(f"Search found {len(search_results)} snippets")
    for r in search_results:
        print(f" - {r}")
        
    ids = [r['id'] for r in search_results]
    print(f"IDs: {ids}")
    
    if not ids:
        print("No IDs found. Creating a fake paper for testing if needed, or exiting.")
        return

    print("Hydrating papers by IDs...")
    try:
        papers = storage.get_papers_by_ids(ids)
        print(f"Hydrated {len(papers)} papers")
        if papers:
            print("First paper sample keys:", papers[0].keys())
    except Exception as e:
        print("CRASH in get_papers_by_ids:", e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_db_logic()
