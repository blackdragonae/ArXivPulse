import arxiv
from typing import List, Dict, Any
from . import config
from datetime import datetime, date, timezone, timedelta

def fetch_papers(max_results: int = config.MAX_RESULTS) -> List[Dict[str, Any]]:
    """
    Fetches recent papers from the configured categories.
    """
    # Construct query: cat:astro-ph OR cat:gr-qc ...
    query = " OR ".join([f"cat:{cat}" for cat in config.CATEGORIES])
    
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )

    papers = []
    
    # We use list(search.results()) to fetch all. 
    # Be careful with very large max_results as this generator makes network calls.
    for result in search.results():
        papers.append({
            'id': result.entry_id,
            'title': result.title,
            'summary': result.summary,
            'authors': [a.name for a in result.authors],
            'published': result.published.isoformat(),
            'pdf_url': result.pdf_url,
            'categories': result.categories
        })
        
    return papers

def fetch_latest_daily_batch() -> tuple[List[Dict[str, Any]], str]:
    """
    Fetches ALL papers from the most recent active day on ArXiv.
    Returns: (papers, date_string)
    """
    # 1. Fetch a small batch to determine the latest date
    query = " OR ".join([f"cat:{cat}" for cat in config.CATEGORIES])
    search = arxiv.Search(
        query=query,
        max_results=10, # Get just a few to find the date
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )
    
    first_result = next(search.results(), None)
    if not first_result:
        return [], str(date.today())
        
    # ArXiv timestamps are UTC
    target_date = first_result.published.date()
    
    # 2. Results generator for a larger batch
    # We use max_results=None to fetch until we hit the date boundary
    full_search = arxiv.Search(
        query=query,
        max_results=None, 
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )
    
    daily_papers = []
    
    for result in full_search.results():
        # Check date
        if result.published.date() < target_date:
            # We reached the previous day, stop
            break
            
        if result.published.date() == target_date:
            daily_papers.append({
                'id': result.entry_id,
                'title': result.title,
                'summary': result.summary,
                'authors': [a.name for a in result.authors],
                'published': result.published.isoformat(),
                'pdf_url': result.pdf_url,
                'categories': result.categories
            })
            
    # Return target_date + 1 day as the "Batch Label"
    batch_label = (target_date + timedelta(days=1)).isoformat()
    return daily_papers, batch_label

def fetch_papers_by_date(date_str: str) -> List[Dict[str, Any]]:
    """
    Fetches papers submitted on a specific date (YYYY-MM-DD).
    NOTE: We shift the query by -1 day to get the 'Announcement' date equivalent.
    """
    # Parse date
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    # Query previous day
    query_d = d - timedelta(days=1)
    
    start = query_d.strftime("%Y%m%d0000")
    end = query_d.strftime("%Y%m%d2359")
    
    # Query: (cat:A OR cat:B) AND submittedDate:[start TO end]
    cat_query = " OR ".join([f"cat:{cat}" for cat in config.CATEGORIES])
    query = f"({cat_query}) AND submittedDate:[{start} TO {end}]"
    
    # max_results=None ensures we get ALL pages for this date query
    search = arxiv.Search(
        query=query,
        max_results=None,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )
    
    papers = []
    for result in search.results():
        papers.append({
            'id': result.entry_id,
            'title': result.title,
            'summary': result.summary,
            'authors': [a.name for a in result.authors],
            'published': result.published.isoformat(),
            'pdf_url': result.pdf_url,
            'categories': result.categories
        })
        
    return papers

def search_archive(query: str, max_results: int = 50) -> List[Dict[str, Any]]:
    """
    Searches the global ArXiv database (titles, authors, abstracts).
    """
    # Simple query for ArXiv API
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
        sort_order=arxiv.SortOrder.Descending
    )
    
    papers = []
    for result in search.results():
        papers.append({
            'id': result.entry_id,
            'title': result.title,
            'summary': result.summary,
            'authors': [a.name for a in result.authors],
            'published': result.published.isoformat(),
            'pdf_url': result.pdf_url,
            'categories': result.categories
        })
        
    return papers
