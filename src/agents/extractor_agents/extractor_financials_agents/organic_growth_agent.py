import json
import logging
from typing import Dict, Optional
from src.services.llm_client import LLMClient
from src.core.blackboard import CompanyMetadata, WorkspaceContext
from src.agents.agent_executor import run_agent_loop
from src.tools.keyword_search import (
    find_keyword_contexts as orchestrator_find_keyword_contexts,
)

logger = logging.getLogger(__name__)


def run_organic_growth_agent(
    client: LLMClient,
    parsed_documents: Dict[str, str],
    company_metadata: CompanyMetadata,
    workspace_state: WorkspaceContext,
    period_key: str,
    is_quarterly: bool = True,
    learnings: Optional[str] = None,
) -> tuple[float, float, float]:
    """
    Stateless agent that extracts simple growth, organic growth, and total revenue for a target period.
    Returns (simple_growth, organic_growth, revenue) as floats.
    Enforces a 10-turn limit and tool restrictions.
    """
    from src.utils.financial_math import clean_val

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the Organic Growth Agent. Your goal is to determine simple revenue growth, organic revenue growth, and total revenue.\n"
        f"Specifically, we are focused on the {focus_period} time period. Find the values corresponding to this focused period.\n"
        "Rules:\n"
        "1. You have a maximum of 10 turns. Search the document for organic growth, constant currency adjustments, acquisitions, and revenue growth using keyword_search (hint: potential first keywords to search include 'organic', 'currency', 'acquisition', 'merger', 'contribr').\n"
        "2. Use 'keyword_search' to search the available files. You can search files simultaneously or target specific files.\n"
        "3. Use 'query_blackboard' to read existing data (like metadata, income statement elements, or other period results) to verify total revenue or other trends.\n"
        "4. If organic growth or constant currency growth is explicitly reported, extract it. Check if there are M&A contributions that should be backed out.\n"
        "5. If organic growth is NOT explicitly reported, compute it: e.g. Organic Growth = Constant Currency Growth (if reported, otherwise simple growth) - (Acquisition revenue / Total revenue).\n"
        "6. Determine the correct total revenue value from the income statement content.\n"
        "7. Call 'finalize' with your final extracted/calculated growth rates and total revenue. You must express the growth values as percentage float strings (e.g., '18.25%' for 18.25% growth, '8.00%' for 8% growth, or '0.50%' for 0.5% growth). Format the percentage with two decimal places. For revenue, provide the total revenue number as a string (e.g., '9829' or '9829.0')."
    )

    filenames_str = ", ".join(parsed_documents.keys())
    user_content = (
        f"Starting search for organic growth and revenue for ticker '{company_metadata.ticker}', period '{period_key}'.\n"
        f"Fanned-in files: [{filenames_str}].\n\n"
        "Please find the total revenue, simple revenue growth, and organic revenue growth."
    )
    if learnings:
        user_content += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learnings}\n"""'

    # Define tools as inner functions closed over state
    def keyword_search(
        keywords: str, filename: Optional[str] = None, window: int = 200
    ) -> str:
        """
        Search for occurrences of keywords (comma-separated list) within a window of characters.
        If filename is specified, search only that document. Otherwise, searches all fanned-in documents.
        """
        keywords_list = [k.strip() for k in keywords.split(",") if k.strip()]
        if filename:
            doc_content = parsed_documents.get(filename, "")
            if not doc_content:
                return f"Error: Document '{filename}' not found or empty."
            return str(
                orchestrator_find_keyword_contexts(doc_content, keywords_list, window)
            )
        else:
            results = {}
            for name, doc_content in parsed_documents.items():
                contexts = orchestrator_find_keyword_contexts(
                    doc_content, keywords_list, window
                )
                if contexts:
                    results[name] = contexts
            return json.dumps(results)

    def query_blackboard(section: str, period: Optional[str] = None) -> str:
        """
        Query the active blackboard state in a read-only manner.
        Arguments:
          section: The section of the blackboard to query. Options: 'metadata', 'company_data', 'financial_data', 'other_data', 'reports'.
          period: Optional specific period (e.g., '2024_Q3') if querying 'financial_data' or 'other_data'. If not specified, defaults to the current active period.
        """
        from src.tools.query_blackboard import query_blackboard_helper

        return query_blackboard_helper(
            workspace_state=workspace_state,
            company_metadata=company_metadata,
            period_key=period_key,
            section=section,
            period=period,
        )

    def finalize(simple_growth: str, organic_growth: str, revenue: str) -> str:
        """Finalize the growth extraction, specifying simple_growth, organic_growth percentages and revenue."""
        return "Growth extraction finalized."

    tools = [keyword_search, query_blackboard, finalize]

    finalized_args, history = run_agent_loop(
        client=client,
        system_prompt=sys_prompt,
        initial_prompt=user_content,
        tools=tools,
        max_turns=10,
    )

    def clean_growth_val(val: str) -> float:
        val_str = str(val).strip()
        parsed = clean_val(val_str)
        if "%" not in val_str and abs(parsed) > 1.0:
            parsed /= 100.0
        return round(parsed, 4)

    simple_growth = clean_growth_val(str(finalized_args.get("simple_growth", "0")))
    organic_growth = clean_growth_val(str(finalized_args.get("organic_growth", "0")))
    revenue = clean_val(str(finalized_args.get("revenue", "0")))

    if organic_growth == 0.0 and simple_growth != 0.0:
        organic_growth = simple_growth
    return simple_growth, organic_growth, revenue
