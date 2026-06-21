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


def run_diluted_shares_agent(
    client: LLMClient,
    parsed_documents: Dict[str, str],
    company_metadata: CompanyMetadata,
    workspace_state: WorkspaceContext,
    period_key: str,
    is_quarterly: bool = True,
    learnings: Optional[str] = None,
) -> tuple[float, float]:
    """
    Stateless agent that extracts basic and diluted shares outstanding for a target period.
    Returns (basic_shares, diluted_shares) as floats (in millions).
    Enforces a 10-turn limit and tool restrictions.
    """
    from src.agents.extractor_orchestrator import clean_val

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the Diluted Shares Agent. Your goal is to find the exact basic and diluted shares outstanding.\n"
        f"Specifically, we are focused on the {focus_period} time period. Ensure you find the shares outstanding corresponding to this focused period.\n"
        "Rules:\n"
        "1. You have a maximum of 10 turns. Search for keyword contexts first (hint: potential first keywords to search for include 'diluted', 'share', 'basic').\n"
        "2. Use 'keyword_search' to search the available files. You can search files simultaneously or target specific files.\n"
        "3. Use 'query_blackboard' to read existing data (like metadata or the extracted income statement) to check if the shares have already been extracted or to verify constraints.\n"
        "4. When you find the values, call 'finalize' with the basic and diluted shares. You must express the values as float strings in millions of shares, formatted with two decimal places (e.g., '280.00' for 280 million shares, or '283.13' for 283,125,000 shares). Do not write 'million' or include commas in the values."
    )

    filenames_str = ", ".join(parsed_documents.keys())
    user_content = (
        f"Starting search for basic and diluted shares outstanding for ticker '{company_metadata.ticker}', period '{period_key}'.\n"
        f"Fanned-in files: [{filenames_str}].\n\n"
        "Please find the basic and diluted shares outstanding."
    )
    if learnings:
        user_content += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learnings}\n"""'

    # Define tools as inner functions closed over state
    def keyword_search(
        keywords: list, filename: Optional[str] = None, window: int = 200
    ) -> str:
        """
        Search for occurrences of keywords within a window of characters.
        If filename is specified, search only that document. Otherwise, searches all fanned-in documents.
        """
        if filename:
            doc_content = parsed_documents.get(filename, "")
            if not doc_content:
                return f"Error: Document '{filename}' not found or empty."
            return str(
                orchestrator_find_keyword_contexts(doc_content, keywords, window)
            )
        else:
            results = {}
            for name, doc_content in parsed_documents.items():
                contexts = orchestrator_find_keyword_contexts(
                    doc_content, keywords, window
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

    def finalize(basic_shares: str, diluted_shares: str) -> str:
        """Finalize the shares extraction, specifying basic_shares and diluted_shares in millions."""
        return "Shares extraction finalized."

    tools = [keyword_search, query_blackboard, finalize]

    finalized_args, history = run_agent_loop(
        client=client,
        system_prompt=sys_prompt,
        initial_prompt=user_content,
        tools=tools,
        max_turns=10,
    )

    basic_shares = clean_val(str(finalized_args.get("basic_shares", "0")))
    diluted_shares = clean_val(str(finalized_args.get("diluted_shares", "0")))

    return basic_shares, diluted_shares
