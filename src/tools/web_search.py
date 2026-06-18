import logging
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


def search_investopedia(term: str) -> str:
    """Search Investopedia for the given accounting term and return the first result summary."""
    query = f"site:investopedia.com {term} definition"
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if results:
                # Combine snippets
                snippets = []
                for res in results:
                    snippets.append(f"{res.get('title')}: {res.get('body')}")
                return "\n".join(snippets)
    except Exception as e:
        logger.error(f"DuckDuckGo search failed for query '{query}': {str(e)}")
    return ""
