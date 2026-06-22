import json
import logging
from pathlib import Path
from typing import Dict, Optional
from src.services.llm_client import LLMClient
from src.core.blackboard import CompanyMetadata, WorkspaceContext
from src.agents.agent_executor import run_agent_loop
from src.tools.keyword_search import (
    find_keyword_contexts as orchestrator_find_keyword_contexts,
)

logger = logging.getLogger(__name__)


def run_tax_agent(
    client: LLMClient,
    parsed_documents: Dict[str, str],
    company_metadata: CompanyMetadata,
    workspace_state: WorkspaceContext,
    period_key: str,
    operating_income: float,
    operating_ebita: float,
    ebita_adjustments: list,
    is_quarterly: bool = True,
    learnings: Optional[str] = None,
) -> tuple[float, float, float, list]:
    """
    Stateless agent that extracts Income Before Taxes, Reported Tax Provision, Adjusted Taxes, and tax adjustments.
    Returns (income_before_taxes, reported_tax_provision, adjusted_taxes, tax_adjustments) as floats and list.
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
        "You are Sir Pennyworth, a senior financial analyst specializing in tax provisions and adjustments.\n"
        f"Your task is to identify key income statement figures directly from the statement (specifically "
        "Income Before Taxes and Reported Tax Provision), identify non-operating bridge items and non-recurring tax "
        "benefits from footnotes, and calculate adjusted taxes, focusing specifically on the "
        f"{focus_period} time period.\n\n"
        "You have been provided with the already extracted Operating Income, and optionally Operating EBITA and EBITA adjustments from a prior stage.\n"
        "Rules:\n"
        "1. You have a maximum of 10 turns. Search for keyword contexts and chunks first to locate the figures.\n"
        "2. Use 'keyword_search' to search the available files. You can search files simultaneously or target specific files.\n"
        "3. Use 'query_blackboard' to read existing data (like metadata or other period results) to verify/reconcile tax provisions.\n"
        "4. Extract Reported Income Before Taxes and Reported Tax Provision from the income statement content.\n"
        "5. Back out the tax effect of non-operating adjustments at a statutory rate of 25% (21% federal, 4% state/local). This includes:\n"
        "   - The EBITA adjustments identified by the EBITA agent (e.g. restructuring, amortization).\n"
        "   - Non-operating items that bridge Income Before Taxes to Operating Income (e.g., interest expense, interest income, non-operating gains/losses).\n"
        "6. Identify any non-recurring tax benefits/credits in the footnotes.\n"
        "7. Calculate Adjusted Taxes = Reported Tax Provision + Tax effect of adjustments - non-recurring tax benefits.\n"
        "8. Standardize positive/negative signs for the calculations and outputs:\n"
        "   - The Reported Tax Provision is expressed as a negative number if it is a tax expense, and positive only if it is a tax benefit/credit.\n"
        "   - For the tax effect of non-operating adjustments (tax_adjustments): a positive value indicates a tax benefit/credit (reducing tax expense), and a negative value indicates a tax expense (increasing overall tax expense).\n"
        "   - Ensure that Adjusted Taxes and their components in the returned JSON have signs consistent with these rules so that math checks (e.g. Adjusted Taxes = Reported Tax Provision + Tax effect of adjustments - non-recurring tax benefits) work correctly.\n"
        "9. Reasoning rules for tax adjustments direction:\n"
        "   - When backing out adjustments to calculate Adjusted Taxes:\n"
        "     - Non-operating bridge items (like interest expense or interest income) must be tax-adjusted as well. An interest expense add-back is a positive pre-tax adjustment (since interest expense was subtracted to get Income Before Taxes). An interest income subtraction is a negative pre-tax adjustment.\n"
        "     - A positive adjustment increases taxable operating profit. Therefore, it increases tax expense (making the tax adjustment a negative value, representing additional tax expense).\n"
        "     - A negative adjustment decreases taxable operating profit. Therefore, it decreases tax expense (making the tax adjustment a positive value, representing a tax reduction/benefit).\n"
        "     - Exception: Non-deductible items like goodwill impairments have a tax impact of 0%, so they have 0.0 associated tax adjustment.\n"
        "10. Identify the currency and unit from the extracted income statement content (provided below). Ensure all pre-tax income, reported tax provision, and tax adjustments are in this same currency and unit (do not convert to USD unless the income statement itself is in USD).\n"
        "11. Call 'finalize' with the extracted/calculated pre-tax income, reported tax, adjusted taxes, and the list of adjustments."
    )

    filenames_str = ", ".join(parsed_documents.keys())
    ebita_info = ""
    if operating_ebita or ebita_adjustments:
        ebita_info = (
            f"The EBITA Agent has determined:\n"
            f"- Operating EBITA: {operating_ebita}\n"
            f"- EBITA Adjustments: {json.dumps(ebita_adjustments)}\n\n"
        )
    else:
        ebita_info = "Note: Operating EBITA and EBITA adjustments are not available for this run.\n\n"

    user_content = (
        f"Start searching for tax provisions and non-operating bridge items for ticker '{company_metadata.ticker}', period '{period_key}'.\n"
        f"Fanned-in files: [{filenames_str}].\n\n"
        f"Operating Income: {operating_income}\n"
        f"{ebita_info}"
        "Here are some useful keywords to search for if needed: interest, gain, loss, tax benefit, tax adjustment, provision, statutory."
    )
    if learnings:
        user_content += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learnings}\n"""'

    if local_dict_guidance:
        user_content += f"\n\nLocal Dictionary Guidance:\n{local_dict_guidance}\n"

    # Define tools as inner functions closed over state
    def keyword_search(
        keywords: list, filename: Optional[str] = None, window: int = 250
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

    def finalize(
        income_before_taxes: float,
        reported_tax_provision: float,
        adjusted_taxes: float,
        tax_adjustments: list,
    ) -> str:
        """Finalize the tax adjustments extraction, specifying income_before_taxes, reported_tax_provision, adjusted_taxes, and the adjustments list."""
        return "Tax extraction finalized."

    tools = [keyword_search, query_blackboard, finalize]

    finalized_args, history = run_agent_loop(
        client=client,
        system_prompt=sys_prompt,
        initial_prompt=user_content,
        tools=tools,
        max_turns=10,
    )

    inc_bt = float(finalized_args.get("income_before_taxes", 0.0))
    rep_tax = float(finalized_args.get("reported_tax_provision", 0.0))
    adj_taxes = float(finalized_args.get("adjusted_taxes", rep_tax))
    tax_adjustments = finalized_args.get("tax_adjustments", [])

    return inc_bt, rep_tax, adj_taxes, tax_adjustments
