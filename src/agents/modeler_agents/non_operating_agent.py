import logging
from pathlib import Path
from typing import Dict, Any, Optional

from src.services.llm_client import LLMClient
from src.core.exceptions import LLMError
from src.agents.agent_executor import run_agent_loop
from src.core.blackboard import WorkspaceContext, CompanyMetadata

logger = logging.getLogger(__name__)


def run_non_operating_agent(
    client: LLMClient,
    company_metadata: CompanyMetadata,
    workspace_state: WorkspaceContext,
    period_key: str,
    learnings: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Stateless agent that extracts and categorizes non-operating items from the blackboard.
    Returns a dictionary of results.
    Enforces a 10-turn limit and tool restrictions.
    """
    # 1. Pre-flight dependency check
    if period_key not in workspace_state.reports:
        return {
            "status": "failed",
            "error": f"Missing dependency: Period '{period_key}' not initialized on the blackboard.",
        }

    report = workspace_state.reports[period_key]

    # Extract non-operating items from blackboard
    non_operating_assets = [
        item
        for item in report.financial_data.line_items
        if item.category in ("current_assets", "noncurrent_assets")
        and not item.operating
    ]
    non_operating_liabilities = [
        item
        for item in report.financial_data.line_items
        if item.category in ("current_liabilities", "noncurrent_liabilities")
        and not item.operating
    ]

    non_op_assets_str = (
        "\n".join(f"- {item.line_name}: {item.value}" for item in non_operating_assets)
        if non_operating_assets
        else "None"
    )
    non_op_liab_str = (
        "\n".join(
            f"- {item.line_name}: {item.value}" for item in non_operating_liabilities
        )
        if non_operating_liabilities
        else "None"
    )

    # Default results in case of failure or empty response
    final_results = {
        "cash": 0.0,
        "short_term_investments": 0.0,
        "debt": 0.0,
        "preferred_equity": 0.0,
        "minority_interest": 0.0,
        "other_financial": 0.0,
        "explanation": "Default backup non-operating values used.",
    }

    # Define tools as inner functions closed over state
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

    def access_resources() -> str:
        """Access the central balance sheet dictionary for classifications."""
        dict_path = Path("src/resources/dictionary/balance_sheet.md")
        if dict_path.exists():
            return dict_path.read_text(encoding="utf-8")
        return ""

    def finalize(
        cash: float,
        short_term_investments: float,
        debt: float,
        preferred_equity: float,
        minority_interest: float,
        other_financial: float,
        explanation: str,
    ) -> str:
        """Conclude non-operating categories extraction."""
        final_results["cash"] = cash
        final_results["short_term_investments"] = short_term_investments
        final_results["debt"] = debt
        final_results["preferred_equity"] = preferred_equity
        final_results["minority_interest"] = minority_interest
        final_results["other_financial"] = other_financial
        final_results["explanation"] = explanation
        return "Non-operating extraction finalized."

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. Your task is to extract and categorize the company's non-operating balance sheet line items into the following 6 categories:\n"
        "1. cash: Cash and cash equivalents (plus restricted cash).\n"
        "2. short_term_investments: Marketable securities, short-term investments, liquid investments.\n"
        "3. debt: Short-term debt, long-term debt, lease liabilities (if non-operating), notes payable, commercial paper, convertible debt.\n"
        "4. preferred_equity: Preferred stock, mezzanine equity.\n"
        "5. minority_interest: Non-controlling interests, redeemable non-controlling interests.\n"
        "6. other_financial: Other non-operating physical/financial assets (e.g. equity method investments, assets held for sale, pension assets, due from related parties) MINUS other non-operating liabilities (e.g. dividends payable, pension liabilities, liabilities held for sale, litigation accruals, other accrued non-operating liabilities).\n\n"
        "Rules:\n"
        "1. Examine the provided sections: Non-Operating Assets, Non-Operating Liabilities, and the raw Balance Sheet markdown.\n"
        "2. Cross-reference with the Classification Table in the Balance Sheet Dictionary to map line items to categories.\n"
        "3. For each category, sum the values of all corresponding line items. (All values are typically in millions, keep them scaled exactly as they are in the balance sheet).\n"
        "4. For 'other_financial', calculate: (Sum of non-operating assets in 'other_financial_physical_assets') minus (Sum of non-operating liabilities in 'other_financial_liabilities').\n"
        "5. If a category has no items, its value should be 0.0.\n"
        "6. Call the 'finalize' tool with the extracted arguments."
    )

    user_content = (
        f"Extract the non-operating categories for ticker: {company_metadata.ticker}, period: {period_key}\n\n"
        f"### Non-Operating Assets Section:\n{non_op_assets_str}\n\n"
        f"### Non-Operating Liabilities Section:\n{non_op_liab_str}\n\n"
        f"### Raw Balance Sheet Markdown:\n{report.financial_data.raw_balance_sheet_markdown or 'Not available.'}\n"
    )
    if learnings:
        user_content += f'\n\nHere is the active company modeling learning context to guide your decisions:\n"""\n{learnings}\n"""'

    tools = [query_blackboard, access_resources, finalize]

    try:
        finalized_args, history = run_agent_loop(
            client=client,
            system_prompt=sys_prompt,
            initial_prompt=user_content,
            tools=tools,
            max_turns=10,
        )
    except LLMError as e:
        raise LLMError(
            f"Non-Operating Agent failed to finalize non-operating extraction within the maximum turn limit: {e}"
        )
    except Exception as e:
        raise LLMError(f"Non-Operating Agent failed during LLM generation: {e}")

    # Trigger Curator Agent to capture lessons in model_learning.md
    try:
        from src.agents.curator_agent import CuratorAgent

        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(client.settings)
        curator.curate_model_agent(
            company_metadata.ticker, "Non-Operating", history_text
        )
    except Exception as e:
        logger.error(f"Failed to run curator for Non-Operating agent: {e}")

    return final_results
