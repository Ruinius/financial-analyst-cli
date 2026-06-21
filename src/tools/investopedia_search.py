import logging
from src.services.ddg_search import ddg_search

logger = logging.getLogger(__name__)


def search_investopedia(term: str) -> str:
    """Search Investopedia for the given accounting term and return the first result summary."""
    query = f"site:investopedia.com {term} definition"
    results = ddg_search(query, max_results=3)
    if results:
        # Combine snippets
        snippets = []
        for res in results:
            snippets.append(f"{res.get('title')}: {res.get('body')}")
        return "\n".join(snippets)
    return ""
