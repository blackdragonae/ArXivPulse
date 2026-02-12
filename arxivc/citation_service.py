import requests
from typing import List, Dict, Any

SEMANTIC_SCHOLAR_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"

def _to_semantic_scholar_id(arxiv_id: str) -> str:
    if not arxiv_id:
        return ""
    clean_id = arxiv_id.strip()
    if "arxiv.org" in clean_id:
        clean_id = clean_id.split('/')[-1]
    import re
    clean_id = re.sub(r'v\d+$', '', clean_id)
    return f"ARXIV:{clean_id}"

def get_s2_ids(arxiv_ids: List[str]) -> Dict[str, str]:
    """Maps arXiv IDs to Semantic Scholar paper IDs."""
    if not arxiv_ids:
        return {}
    ss_ids: List[str] = []
    mapping: Dict[str, str] = {}
    for full_id in arxiv_ids:
        ss_id = _to_semantic_scholar_id(full_id)
        if not ss_id:
            continue
        mapping[ss_id] = full_id
        ss_ids.append(ss_id)
    if not ss_ids:
        return {}
    payload = {
        "ids": ss_ids,
        "fields": "paperId",
    }
    results: Dict[str, str] = {}
    try:
        resp = requests.post(SEMANTIC_SCHOLAR_BATCH_URL, json=payload, timeout=12)
        if resp.status_code != 200:
            print(f"Semantic Scholar Error: {resp.status_code} {resp.text}")
            return {}
        data = resp.json()
        for i, item in enumerate(data):
            original_id = mapping.get(ss_ids[i])
            if not original_id:
                continue
            if item and item.get("paperId"):
                results[original_id] = item["paperId"]
    except Exception as e:
        print(f"Error fetching Semantic Scholar IDs: {e}")
    return results

def get_direct_links(arxiv_ids: List[str]) -> Dict[str, Any]:
    """Returns direct citation links between the provided arXiv IDs."""
    if not arxiv_ids:
        return {"edges": [], "missing": []}
    id_map = get_s2_ids(arxiv_ids)
    s2_to_arxiv = {v: k for k, v in id_map.items() if v}
    s2_ids = [id_map.get(pid) for pid in arxiv_ids if id_map.get(pid)]
    if not s2_ids:
        return {"edges": [], "missing": arxiv_ids}

    payload = {
        "ids": s2_ids,
        "fields": "references.paperId,citations.paperId",
    }
    edges_set = set()
    try:
        resp = requests.post(SEMANTIC_SCHOLAR_BATCH_URL, json=payload, timeout=15)
        if resp.status_code != 200:
            print(f"Semantic Scholar Error: {resp.status_code} {resp.text}")
            return {"edges": [], "missing": [pid for pid in arxiv_ids if pid not in id_map]}
        data = resp.json()
        for i, item in enumerate(data):
            if not item:
                continue
            src_s2 = s2_ids[i]
            src_arxiv = s2_to_arxiv.get(src_s2)
            if not src_arxiv:
                continue
            refs = item.get("references") or []
            for ref in refs:
                tgt_s2 = ref.get("paperId")
                tgt_arxiv = s2_to_arxiv.get(tgt_s2)
                if tgt_arxiv and tgt_arxiv != src_arxiv:
                    edges_set.add((src_arxiv, tgt_arxiv))
            cits = item.get("citations") or []
            for cite in cits:
                tgt_s2 = cite.get("paperId")
                tgt_arxiv = s2_to_arxiv.get(tgt_s2)
                if tgt_arxiv and tgt_arxiv != src_arxiv:
                    edges_set.add((tgt_arxiv, src_arxiv))
    except Exception as e:
        print(f"Error fetching citation links: {e}")
    edges = [{"from": a, "to": b, "label": "cites"} for (a, b) in edges_set]
    missing = [pid for pid in arxiv_ids if pid not in id_map]
    return {"edges": edges, "missing": missing}

def get_citations(arxiv_ids: List[str]) -> Dict[str, int]:
    """
    Fetches citation counts for a list of ArXiv IDs using Semantic Scholar.
    Returns a dict mapping {arxiv_id: citation_count}.
    """
    if not arxiv_ids:
        return {}
        
    # Format IDs for Semantic Scholar (ARXIV:Prefix)
    # ArXiv IDs in our DB are typically URLs or full IDs e.g. "http://arxiv.org/abs/2106.15928v1" or "2106.15928v1"
    # We need to extract just the ID part, e.g. "2106.15928". Version suffix should be stripped for SS usually, or kept. 
    # Let's try to match what SS expects. Usually "ARXIV:2106.15928".
    
    mapping = {}
    ss_ids = []
    
    for full_id in arxiv_ids:
        # Extract ID from URL if needed
        clean_id = full_id.split('/')[-1].replace('v1', '').replace('v2', '').replace('v3', '') # Primitive stripping
        # Better: keep version if SS supports it, but usually standard ID is safer.
        # Let's clean it up roughly.
        if "arxiv.org" in full_id:
             clean_id = full_id.split('/')[-1]
             
        # Strip 'vX' suffix regex?
        import re
        clean_id = re.sub(r'v\d+$', '', clean_id)
        
        ss_id = f"ARXIV:{clean_id}"
        mapping[ss_id] = full_id
        ss_ids.append(ss_id)
        
    payload = {
        "ids": ss_ids,
        "fields": "citationCount"
    }
    
    results = {}
    try:
        resp = requests.post(SEMANTIC_SCHOLAR_BATCH_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Response is a list of objects or nulls
            for item in data:
                if item and 'paperId' in item:
                    # Semantic Scholar returns the requested ID in text if we scan carefully or we map by index?
                    # The batch endpoint returns list in same order? 
                    # Documentation says: "The order of the returned papers corresponds to the order of the input IDs."
                    pass
            
            # Since order is preserved:
            for i, item in enumerate(data):
                original_id = mapping.get(ss_ids[i])
                if item and 'citationCount' in item:
                    results[original_id] = item['citationCount']
                else:
                    results[original_id] = 0 # Not found or no citations
        else:
            print(f"Semantic Scholar Error: {resp.status_code} {resp.text}")
            
    except Exception as e:
        print(f"Error fetching citations: {e}")
        
    return results

def get_paper_graph(arxiv_id: str) -> Dict[str, Any]:
    """
    Fetches the ego-graph (citations and references) for a given paper.
    Returns a dict with 'nodes' and 'edges' suitable for visualization.
    """
    import re
    import time
    
    # Check if input is a Semantic Scholar ID (40 char hex)
    # or an ArXiv ID.
    clean_id = arxiv_id.strip()
    is_ss_id = re.match(r'^[a-f0-9]{40}$', clean_id)
    
    if is_ss_id:
        ss_id = clean_id
    else:
        # Assume ArXiv ID
        clean_id = clean_id.split('/')[-1]
        clean_id = re.sub(r'v\d+$', '', clean_id)
        ss_id = f"ARXIV:{clean_id}"

    # Fetch fields: title, year, authors
    # We fetch references and citations (limit 20 each to avoid explosion)
    url = f"https://api.semanticscholar.org/graph/v1/paper/{ss_id}"
    params = {
        "fields": "title,year,authors,references.title,references.paperId,references.year,citations.title,citations.paperId,citations.year",
        "limit": 20
    }

    # Retry parameters
    max_retries = 3
    wait_time = 1  # seconds

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 429:
                print(f"Graph Fetch Rate Limited (429). Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
                wait_time *= 2  # Exponential backoff
                continue
                
            if resp.status_code == 404:
                 print(f"Paper not found in Semantic Scholar: {ss_id}")
                 return {"nodes": [], "edges": [], "error": "Paper not found in citation database."}

            if resp.status_code != 200:
                print(f"Graph Fetch Error: {resp.status_code} - {resp.text}")
                return {"nodes": [], "edges": [], "error": f"Semantic Scholar API Error: {resp.status_code}"}
                
            data = resp.json()
            
            # Build Graph
            # Central Node
            nodes = []
            edges = []
            
            center_id = data.get('paperId') or arxiv_id
            nodes.append({
                "id": center_id,
                "label": data.get('title', 'Target Paper'),
                "group": "center",
                "year": data.get('year')
            })
            
            # References (Outgoing)
            if 'references' in data and data['references']:
                for ref in data['references']:
                    if not ref.get('paperId'): continue
                    nodes.append({
                        "id": ref['paperId'],
                        "label": ref.get('title', 'Unknown'),
                        "group": "reference",
                        "year": ref.get('year')
                    })
                    edges.append({
                        "from": center_id,
                        "to": ref['paperId'],
                        "arrows": "to",
                        "label": "cites"
                    })
    
            # Citations (Incoming)
            if 'citations' in data and data['citations']:
                for cite in data['citations']:
                    if not cite.get('paperId'): continue
                    nodes.append({
                        "id": cite['paperId'],
                        "label": cite.get('title', 'Unknown'),
                        "group": "citation",
                        "year": cite.get('year')
                    })
                    edges.append({
                        "from": cite['paperId'],
                        "to": center_id,
                        "arrows": "to",
                        "label": "cites"
                    })
                    
            return {"nodes": nodes, "edges": edges}
    
        except Exception as e:
            print(f"Graph Exception on attempt {attempt+1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
                continue
                
    print("Graph Fetch Failed after retries.")
    return {"nodes": [], "edges": [], "error": "External API is busy (Rate Limit). Please try again in 10s."}
