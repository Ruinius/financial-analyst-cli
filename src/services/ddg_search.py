import logging
from typing import List, Dict
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


def ddg_search(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    """
    Search DuckDuckGo with the given query and return a list of result dictionaries.
    Each result dictionary typically has 'title', 'href', and 'body' keys.
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return results
    except Exception as e:
        logger.error(f"DuckDuckGo search failed for query '{query}': {str(e)}")
        return []
