import json
import logging
from pathlib import Path
from typing import Dict, Optional, List, Any
from src.services.llm_client import LLMClient
from src.core.blackboard import CompanyMetadata, WorkspaceContext
from src.agents.agent_executor import run_agent_loop
from src.tools.keyword_search import (
    find_keyword_contexts as orchestrator_find_keyword_contexts,
)

logger = logging.getLogger(__name__)


def run_ebita_agent(
    client: LLMClient,
    parsed_documents: Dict[str, str],
    company_metadata: CompanyMetadata,
    workspace_state: WorkspaceContext,
    period_key: str,
    is_quarterly: bool = True,
    learnings: Optional[str] = None,
) -> tuple[float, float, list]:
    """
    Stateless agent that extracts Operating Income, Operating EBITA, and EBITA adjustments.
    Returns (operating_income, operating_ebita, ebita_adjustments) as floats and list.
    Enforces a 10-turn limit and tool restrictions.
    """
    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )

    # Load static dictionary if available
    dict_path = Path("src/resources/dictionary/income_statement.md")
    local_dict_guidance = ""
    if dict_path.exists():
        try:
            is_dict = dict_path.read_text(encoding="utf-8")
            local_dict_guidance = f"--- Income Statement Dictionary ---\n{is_dict}\n"
        except Exception:
            pass

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst specializing in EBITA adjustments.\n"
        f"Your task is to identify and extract Operating Income directly from the income statement, "
        "identify non-operating/non-recurring operating adjustments (e.g. restructuring charges, asset impairments, "
        "amortization of acquired intangibles in opex) from the income statement and footnotes, and calculate clean Operating EBITA, "
        f"focusing specifically on the {focus_period} time period.\n\n"
        "Rules:\n"
        "1. You have a maximum of 10 turns. Search for keyword contexts and chunks first to locate the figures.\n"
        "2. Use 'keyword_search' to search the available files. You can search files simultaneously or target specific files.\n"
        "3. Use 'query_blackboard' to read existing data (like metadata or the interpreted/extracted income statement) to check if the Operating Income has already been extracted or verify classifications.\n"
        "4. Extract Operating Income from the income statement content. Note that if the income statement does not explicitly list it, you must attempt to calculate it starting with a proxy line item that would be close (such as pre-tax income / income before taxes).\n"
        "5. Identify any non-recurring operating adjustments (e.g. restructuring, asset impairments, amortization of acquired intangibles).\n"
        "6. Calculate clean Operating EBITA = Operating Income + EBITA adjustments.\n"
        "7. Standardize positive/negative signs for the calculations and outputs:\n"
        "   - EBITA adjustments are positive if they add back an opex expense (increasing EBITA), and negative if they subtract an operating gain (decreasing EBITA).\n"
        "   - Verify that any number that effectively increases profit is expressed as a positive number.\n"
        "   - Pay special attention to ambiguous items: make sure their sign correctly reflects whether they are a net expense (negative) or net income/benefit (positive).\n"
        "   - Ensure that EBITA and its components in the returned JSON have signs consistent with these rules.\n"
        "8. For adjustments or values not found on the face of the income statement (e.g., found in footnotes or chunk disclosures), you must be extremely careful to use the value corresponding to the three-month period (quarter) rather than the year-to-date (six-month or nine-month) period when the focus period is a quarter. If only a year-to-date value is provided, calculate the quarterly value by subtracting the prior periods' values if available.\n"
        "9. If any individual adjustment value represents a large percentage of EBITA (or Operating Income), you must double-check the text/footnotes to ensure it is the correct value for the focus period and not an incorrect, aggregate, or multi-period value.\n"
        "10. Call 'finalize' with Operating Income, Operating EBITA, and the adjustments list in the specified structure."
    )

    filenames_str = ", ".join(parsed_documents.keys())
    user_content = (
        f"Start searching for Operating Income and EBITA adjustments for ticker '{company_metadata.ticker}', period '{period_key}'.\n"
        f"Fanned-in files: [{filenames_str}].\n\n"
        "(hint: try searching for keywords like 'restructur', 'amort', 'impair', 'goodwill', 'conting', 'acquire', 'intangible')."
    )
    if learnings:
        user_content += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learnings}\n"""'

    if local_dict_guidance:
        user_content += f"\n\nLocal Dictionary Guidance:\n{local_dict_guidance}\n"

    # Define tools as inner functions closed over state
    def keyword_search(
        keywords: str, filename: Optional[str] = None, window: int = 250
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

    def finalize(
        operating_income: float, operating_ebita: float, ebita_adjustments: List[Any]
    ) -> str:
        """Finalize the EBITA extraction, specifying operating_income, operating_ebita, and the adjustments list."""
        return "EBITA extraction finalized."

    tools = [keyword_search, query_blackboard, finalize]

    finalized_args, history = run_agent_loop(
        client=client,
        system_prompt=sys_prompt,
        initial_prompt=user_content,
        tools=tools,
        max_turns=10,
    )

    op_inc = float(finalized_args.get("operating_income", 0.0))
    ebita = float(finalized_args.get("operating_ebita", op_inc))
    ebita_adjustments = finalized_args.get("ebita_adjustments", [])

    return op_inc, ebita, ebita_adjustments
