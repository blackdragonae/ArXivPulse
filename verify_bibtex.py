import requests
import json

BASE_URL = "http://localhost:8000"

def test_bibtex():
    # 1. Fetch some papers to get IDs
    print("Fetching papers...")
    res = requests.get(f"{BASE_URL}/api/papers?status=new&limit=5")
    if res.status_code != 200:
        print(f"Failed to fetch papers: {res.text}")
        return
        
    papers = res.json()
    if not papers:
        print("No papers found to test.")
        return
        
    ids = [p['id'] for p in papers[:2]]
    print(f"Testing export for IDs: {ids}")
    
    # 2. POST to /api/export/bibtex
    payload = {"paper_ids": ids}
    try:
        res = requests.post(f"{BASE_URL}/api/export/bibtex", json=payload)
        
        if res.status_code == 200:
            print("SUCCESS! API returned 200.")
            print("Content Preview:")
            print(res.text[:200])
        else:
            print(f"FAILURE! Status: {res.status_code}")
            print(f"Response: {res.text}")
            
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_bibtex()
