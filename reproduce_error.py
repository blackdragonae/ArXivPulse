import urllib.request
import json
import uuid

API_BASE = "http://localhost:8000/api"

def debug_folder():
    # 1. Create a folder
    print("Creating debug folder...")
    folder_data = json.dumps({"name": "Debug", "query": "Test"}).encode('utf-8')
    req = urllib.request.Request(f"{API_BASE}/folders", data=folder_data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode('utf-8')
            data = json.loads(res_body)
            fid = data['id']
            print(f"Folder created: {fid}")
            
            # 2. Try to fetch papers
            print("Fetching papers...")
            try:
                with urllib.request.urlopen(f"{API_BASE}/folders/{fid}/papers") as res2:
                    print("Status: 200")
                    print("Response:", res2.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                print(f"Fetch Error: {e.code}")
                print(e.read().decode('utf-8'))
                
    except urllib.error.HTTPError as e:
        print(f"Create Error: {e.code}")
        print(e.read().decode('utf-8'))

if __name__ == "__main__":
    debug_folder()
