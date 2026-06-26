import json
import logging
from typing import Optional, List, Any
from src.services.llm_client import LLMClient
from src.core.blackboard import CompanyMetadata, WorkspaceContext, LineItem
from src.agents.agent_executor import run_agent_loop

logger = logging.getLogger(__name__)


def run_interpretation_agent(
    client: LLMClient,
    extracted_line_items: list,
    company_metadata: CompanyMetadata,
    workspace_state: WorkspaceContext,
    period_key: str,
    is_quarterly: bool = True,
    learnings: Optional[str] = None,
) -> list:
    """
    Stateless agent that classifies, verifies, and interprets extracted line items.
    Runs a turn-based agent loop with a 10-turn limit.
    """
    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )

    # Load markdown statements from blackboard if available
    report = workspace_state.reports.get(period_key)
    is_md = ""
    bs_md = ""
    if report:
        is_md = report.financial_data.raw_income_statement_markdown or ""
        bs_md = report.financial_data.raw_balance_sheet_markdown or ""

    # Serialize items for LLM (omitting operating and calculated fields so the agent makes judgment calls without default bias)
    items_data = []
    for item in extracted_line_items:
        items_data.append(
            {
                "line_name": item.line_name,
                "value": item.value,
                "category": item.category,
            }
        )

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial auditor and statement interpretation agent.\n"
        "Your task is to analyze the raw financial statements and classify/verify all extracted line items.\n"
        f"Specifically, we are focused on the {focus_period} time period. Ensure you interpret and verify the line items for this focused period.\n"
        "Specifically, you must:\n"
        "1. Identify whether each line item is a subtotal/total ('calculated' = true/false).\n"
        "   - 'calculated' = true indicates the line is a subtotal or total (e.g., Gross Profit, Operating Income, Total Assets).\n"
        "2. Classify each item as operating (true) or non-operating (false). Use access_resources to query the dictionary for balance_sheet or income_statement classifications.\n"
        "3. Interpret any unnamed, generic (e.g. 'Other', 'Reconciliation adjustment') or ambiguous line items using their indentation, surrounding context, or placement.\n"
        "4. Perform cross-statement mathematical checks. Verify that subtotals match the sum of constituent line items.\n"
        "5. Standardize positive/negative signs for the Income Statement:\n"
        "   - Verify that any number that subtracts from the revenue is an expense, cost, or loss, and is expressed as a negative number.\n"
        "   - Verify that any number that effectively increases profit (e.g. revenue, interest income, tax benefits, gains) is expressed as a positive number.\n"
        "6. Call 'finalize' with the updated/verified line items list as an argument named 'line_items'. Each item should match the structure:\n"
        "   {\n"
        "     'line_name': 'Line Item Name',\n"
        "     'value': 12345.0,\n"
        "     'category': 'current_assets | current_liabilities | noncurrent_assets | noncurrent_liabilities | income_statement | other',\n"
        "     'operating': true/false,\n"
        "     'calculated': true/false\n"
        "   }"
    )

    user_content = (
        f"Starting line item interpretation for ticker '{company_metadata.ticker}', period '{period_key}'.\n"
        f'Income Statement:\n"""\n{is_md}\n"""\n\n'
        f'Balance Sheet:\n"""\n{bs_md}\n"""\n\n'
        f"Currently Extracted Line Items:\n{json.dumps(items_data, indent=2)}\n\n"
        "Please query dictionaries via access_resources and verify/classify the line items."
    )
    if learnings:
        user_content += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learnings}\n"""'

    # Define tools as inner functions
    from src.tools.access_resources import access_resources

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

    def finalize(line_items: List[Any]) -> str:
        """Finalize the line item interpretation, providing the updated/verified list of line items."""
        return "Line items interpretation finalized."

    tools = [access_resources, query_blackboard, finalize]

    finalized_args, history = run_agent_loop(
        client=client,
        system_prompt=sys_prompt,
        initial_prompt=user_content,
        tools=tools,
        max_turns=10,
    )

    if not finalized_args:
        finalized_args = {}

    updated_items = []
    # Match back to original line items to preserve audit trails
    for up_item in finalized_args.get("line_items", []):
        matching_orig = None
        for orig in extracted_line_items:
            if orig.line_name.lower() == up_item.get("line_name", "").lower():
                matching_orig = orig
                break

        if matching_orig:
            matching_orig.operating = up_item.get("operating", matching_orig.operating)
            matching_orig.calculated = up_item.get(
                "calculated", matching_orig.calculated
            )
            matching_orig.category = up_item.get("category", matching_orig.category)
            matching_orig.value = up_item.get("value", matching_orig.value)
            updated_items.append(matching_orig)
        else:
            cat = up_item.get("category", "income_statement")
            if cat not in [
                "current_assets",
                "noncurrent_assets",
                "current_liabilities",
                "noncurrent_liabilities",
                "equity",
                "income_statement",
            ]:
                if "asset" in cat:
                    cat = "current_assets"
                elif "liabilit" in cat:
                    cat = "current_liabilities"
                elif "equity" in cat:
                    cat = "equity"
                else:
                    cat = "income_statement"

            new_item = LineItem(
                line_name=up_item.get("line_name"),
                value=up_item.get("value", 0.0),
                operating=up_item.get("operating", True),
                calculated=up_item.get("calculated", False),
                category=cat,
            )
            updated_items.append(new_item)

    return updated_items if updated_items else extracted_line_items
