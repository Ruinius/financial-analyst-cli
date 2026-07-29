import logging
import threading
import time
import warnings
from typing import List, Dict

with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=RuntimeWarning)
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

_SEARCH_LOCK = threading.Lock()
_LAST_SEARCH_TIME = 0.0
_MIN_SEARCH_INTERVAL = 1.5  # Minimum 1.5s delay between web searches across threads


def ddg_search(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    """
    Search DuckDuckGo with the given query and return a list of result dictionaries.
    Uses a thread-safe rate-limiter queue and retry mechanism to avoid rate limits.
    """
    global _LAST_SEARCH_TIME

    with _SEARCH_LOCK:
        now = time.time()
        elapsed = now - _LAST_SEARCH_TIME
        if elapsed < _MIN_SEARCH_INTERVAL:
            time.sleep(_MIN_SEARCH_INTERVAL - elapsed)
        _LAST_SEARCH_TIME = time.time()

        for attempt in range(3):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    with DDGS() as ddgs:
                        results = list(ddgs.text(query, max_results=max_results))
                        if results:
                            return results
            except Exception as e:
                logger.warning(
                    f"DuckDuckGo search attempt {attempt + 1}/3 failed for query '{query}': {e}"
                )
            time.sleep(1.0 * (attempt + 1))

        return []
