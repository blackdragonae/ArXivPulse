import os
import threading
from datetime import datetime, date, timedelta, timezone
from typing import Any, Callable, Dict, List, TypeVar

import arxiv
import requests

from . import config


ARXIV_PAGE_SIZE = max(20, min(int(os.environ.get("ARXIVC_ARXIV_PAGE_SIZE", "200") or 200), 2000))
ARXIV_DELAY_SECONDS = max(0.0, float(os.environ.get("ARXIVC_ARXIV_DELAY_SECONDS", "3.0") or 3.0))
ARXIV_NUM_RETRIES = max(0, int(os.environ.get("ARXIVC_ARXIV_NUM_RETRIES", "1") or 1))
ARXIV_REQUEST_TIMEOUT_SECONDS = max(
    2.0, float(os.environ.get("ARXIVC_ARXIV_TIMEOUT_SECONDS", "20.0") or 20.0)
)
ARXIV_RATE_LIMIT_COOLDOWN_SECONDS = max(
    5, int(os.environ.get("ARXIVC_ARXIV_429_COOLDOWN_SECONDS", "90") or 90)
)

_ARXIV_REQUEST_LOCK = threading.Lock()
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_UNTIL: datetime | None = None

T = TypeVar("T")


class ArxivRateLimitError(RuntimeError):
    def __init__(self, message: str, retry_after_seconds: int):
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__(message)


class _TimeoutSession(requests.Session):
    """Requests session with a default timeout for every call."""

    def __init__(self, timeout_seconds: float):
        super().__init__()
        self._timeout_seconds = float(timeout_seconds)

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self._timeout_seconds)
        return super().request(method, url, **kwargs)


class _ResilientArxivClient(arxiv.Client):
    """
    Extend arxiv.Client retry logic to include request timeouts.
    This keeps retries at the page level instead of restarting the whole fetch.
    """

    def _parse_feed(
        self, url: str, first_page: bool = True, _try_index: int = 0
    ):
        try:
            return self._Client__try_parse_feed(url, first_page=first_page, try_index=_try_index)
        except (
            arxiv.HTTPError,
            arxiv.UnexpectedEmptyPageError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as err:
            if _try_index < self.num_retries:
                arxiv.logger.debug("Got error (try %d): %s", _try_index, err)
                return self._parse_feed(url, first_page=first_page, _try_index=_try_index + 1)
            arxiv.logger.debug("Giving up (try %d): %s", _try_index, err)
            raise err


_ARXIV_CLIENT = _ResilientArxivClient(
    page_size=ARXIV_PAGE_SIZE,
    delay_seconds=ARXIV_DELAY_SECONDS,
    num_retries=ARXIV_NUM_RETRIES,
)
_ARXIV_CLIENT._session = _TimeoutSession(ARXIV_REQUEST_TIMEOUT_SECONDS)


def _result_to_dict(result: arxiv.Result) -> Dict[str, Any]:
    return {
        "id": result.entry_id,
        "title": result.title,
        "summary": result.summary,
        "authors": [a.name for a in result.authors],
        "published": result.published.isoformat(),
        "pdf_url": result.pdf_url,
        "categories": result.categories,
    }


def _seconds_until_rate_limit_lifts(now: datetime | None = None) -> int:
    ref = now or datetime.now(timezone.utc)
    with _RATE_LIMIT_LOCK:
        until = _RATE_LIMIT_UNTIL
    if not until:
        return 0
    remaining = int((until - ref).total_seconds())
    return max(0, remaining)


def _set_rate_limit_cooldown(seconds: int = ARXIV_RATE_LIMIT_COOLDOWN_SECONDS) -> int:
    wait = max(1, int(seconds or ARXIV_RATE_LIMIT_COOLDOWN_SECONDS))
    until = datetime.now(timezone.utc) + timedelta(seconds=wait)
    with _RATE_LIMIT_LOCK:
        global _RATE_LIMIT_UNTIL
        _RATE_LIMIT_UNTIL = until
    return wait


def _raise_if_rate_limited() -> None:
    wait = _seconds_until_rate_limit_lifts()
    if wait > 0:
        raise ArxivRateLimitError(
            f"arXiv API is temporarily rate limited. Retry in about {wait}s.",
            retry_after_seconds=wait,
        )


def _with_arxiv_client(op: Callable[[arxiv.Client], T]) -> T:
    _raise_if_rate_limited()
    with _ARXIV_REQUEST_LOCK:
        try:
            return op(_ARXIV_CLIENT)
        except arxiv.HTTPError as err:
            status = int(getattr(err, "status", 0) or 0)
            if status == 429:
                wait = _set_rate_limit_cooldown()
                raise ArxivRateLimitError(
                    f"arXiv API returned HTTP 429 (rate limit). Retry in about {wait}s.",
                    retry_after_seconds=wait,
                ) from err
            raise RuntimeError(f"arXiv API request failed with HTTP {status}.") from err
        except requests.exceptions.Timeout as err:
            raise RuntimeError(
                "arXiv request timed out after "
                f"{int(ARXIV_REQUEST_TIMEOUT_SECONDS)}s "
                f"(retries={int(ARXIV_NUM_RETRIES)})."
            ) from err
        except requests.exceptions.RequestException as err:
            raise RuntimeError(f"arXiv request failed: {err}") from err

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

    def _run(api_client: arxiv.Client) -> List[Dict[str, Any]]:
        papers = []
        for result in api_client.results(search):
            papers.append(_result_to_dict(result))
        return papers

    return _with_arxiv_client(_run)

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

    def _run(api_client: arxiv.Client) -> tuple[List[Dict[str, Any]], str]:
        first_result = next(api_client.results(search), None)
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
            sort_order=arxiv.SortOrder.Descending,
        )

        daily_papers = []
        for result in api_client.results(full_search):
            # Check date
            if result.published.date() < target_date:
                # We reached the previous day, stop
                break
            if result.published.date() == target_date:
                daily_papers.append(_result_to_dict(result))

        # Return target_date + 1 day as the "Batch Label"
        batch_label = (target_date + timedelta(days=1)).isoformat()
        return daily_papers, batch_label

    return _with_arxiv_client(_run)

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

    def _run(api_client: arxiv.Client) -> List[Dict[str, Any]]:
        papers = []
        for result in api_client.results(search):
            papers.append(_result_to_dict(result))
        return papers

    return _with_arxiv_client(_run)

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

    def _run(api_client: arxiv.Client) -> List[Dict[str, Any]]:
        papers = []
        for result in api_client.results(search):
            papers.append(_result_to_dict(result))
        return papers

    return _with_arxiv_client(_run)
