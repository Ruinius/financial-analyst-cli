from src.utils.tools import extract_json_from_text
import re
import json
import logging
from pathlib import Path

from src.agents.extractor_orchestrator import LineItem, AuditLinkage

logger = logging.getLogger(__name__)


def update_extract_context(extractor, line_item) -> None:
    """Placeholder for backward compatibility. Direct updates are handled via CuratorAgent."""
    pass


def run_interpretation_agent(
    extracted_line_items: list,
    file_path: Path,
    extractor,
    is_quarterly: bool = True,
) -> list:
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    is_path = extracted_dir / f"{file_path.stem}_income_statement.md"
    bs_path = extracted_dir / f"{file_path.stem}_balance_sheet.md"

    is_md = is_path.read_text(encoding="utf-8") if is_path.exists() else ""
    bs_md = bs_path.read_text(encoding="utf-8") if bs_path.exists() else ""

    # Check local dictionary classifications to pass as guidance/override
    local_dict_guidance = ""
    is_dict = extractor.get_dictionary("income_statement")
    if is_dict:
        local_dict_guidance += f"--- Income Statement Dictionary ---\n{is_dict}\n"
    bs_dict = extractor.get_dictionary("balance_sheet")
    if bs_dict:
        local_dict_guidance += f"--- Balance Sheet Dictionary ---\n{bs_dict}\n"

    # Check company context classifications
    context_content = extractor.get_extract_context()
    company_context_guidance = {}
    if context_content:
        # Pre-parse all guidance rules from context to avoid O(N) regex searches
        guidance_rules = {}
        for match in re.finditer(
            r"-\s*(.*?)\s*:\s*(operating|non-operating)", context_content, re.IGNORECASE
        ):
            guidance_rules[match.group(1).strip().lower()] = (
                match.group(2).lower() == "operating"
            )

        for item in extracted_line_items:
            line_name_lower = item.line_name.lower()
            if line_name_lower in guidance_rules:
                company_context_guidance[item.line_name] = guidance_rules[
                    line_name_lower
                ]

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

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    sys_prompt = (
        "You are Sir Pennyworth, a senior financial auditor and statement interpretation agent.\n"
        "Your task is to analyze the raw financial statements and classify/verify all extracted line items.\n"
        f"Specifically, we are focused on the {focus_period} time period. Ensure you interpret and verify the line items for this focused period.\n"
        "Specifically, you must:\n"
        "1. Identify whether each line item is a raw transaction/primitive line or a subtotal/total ('calculated' = true/false).\n"
        "   - 'calculated' = true indicates the line is a subtotal or total (e.g., Gross Profit, Operating Income, Total Assets).\n"
        "   - Sometimes subtotals/totals are explicitly called out as such (e.g., 'Total Assets', 'Subtotal'). Other times, they are not explicitly labeled and must be inferred based on the surrounding numbers, line items, mathematical relationships, indentation, or placement.\n"
        "2. Classify each item as operating (true) or non-operating (false). Respect the provided local dictionary or company context rules if they exist.\n"
        "   - Operating items (operating = true) represent activities central to the core business operations (e.g., Revenues, Cost of Sales, R&D, SG&A, operating leases).\n"
        "   - Non-operating items (operating = false) represent financing, investing, tax, or peripheral/one-off transactions not part of core operations (e.g., Interest Expense, Interest Income, investment gains/losses, tax provision, discontinued operations).\n"
        "   - This classification is used to calculate clean Operating EBITA and to isolate operating assets/liabilities for calculating Invested Capital and Return on Invested Capital (ROIC).\n"
        "3. Interpret any unnamed, generic (e.g. 'Other', 'Reconciliation adjustment') or ambiguous line items using their indentation, surrounding context, or placement.\n"
        "4. Perform cross-statement mathematical checks. Verify that subtotals match the sum of constituent line items (e.g. total assets = current assets + non-current assets; assets = liabilities + equity; net income = operating income + non-operating income - tax provision). If there are discrepancies, make adjustments or flag them.\n"
        "5. Standardize positive/negative signs for the Income Statement:\n"
        "   - Verify that any number that subtracts from the revenue is an expense, cost, or loss, and is expressed as a negative number.\n"
        "   - Verify that any number that effectively increases profit (e.g. revenue, interest income, tax benefits, gains) is expressed as a positive number.\n"
        "   - Pay special attention to ambiguous items (e.g., net interest income or other non-operating income/expense net): make sure their sign correctly reflects whether they are a net expense (negative) or net income (positive) in the context of the statements.\n\n"
        "Return a valid JSON object with the key 'line_items' containing the updated/verified line items."
    )

    prompt = f"""
Income Statement Markdown:
\"\"\"
{is_md}
\"\"\"

Balance Sheet Markdown:
\"\"\"
{bs_md}
\"\"\"

Currently Extracted Line Items:
{json.dumps(items_data, indent=2)}

Local Dictionary Guidance:
{local_dict_guidance}

Company Context Rules:
{json.dumps(company_context_guidance, indent=2)}

Please review, verify, correct, and return the final list of verified line items in this structure:
{{
  "line_items": [
    {{
      "line_name": "Line Item Name",
      "value": 12345.0,
      "category": "current_assets | current_liabilities | noncurrent_assets | noncurrent_liabilities | income_statement | other",
      "operating": true/false,
      "calculated": true/false
    }}
  ]
}}
"""
    try:
        resp = extractor.llm.generate(
            prompt, system_prompt=sys_prompt, stream_thinking=True
        )
        json_str = extract_json_from_text(resp)
        if json_str:
            data = json.loads(json_str)
            updated_items = []
            # Match back to original line items to preserve audit trails
            for up_item in data.get("line_items", []):
                matching_orig = None
                for orig in extracted_line_items:
                    if orig.line_name.lower() == up_item.get("line_name", "").lower():
                        matching_orig = orig
                        break

                if matching_orig:
                    matching_orig.operating = up_item.get(
                        "operating", matching_orig.operating
                    )
                    matching_orig.calculated = up_item.get(
                        "calculated", matching_orig.calculated
                    )
                    matching_orig.category = up_item.get(
                        "category", matching_orig.category
                    )
                    matching_orig.value = up_item.get("value", matching_orig.value)
                    updated_items.append(matching_orig)
                    update_extract_context(extractor, matching_orig)
                else:
                    new_item = LineItem(
                        line_name=up_item.get("line_name"),
                        value=up_item.get("value", 0.0),
                        operating=up_item.get("operating", True),
                        calculated=up_item.get("calculated", False),
                        category=up_item.get("category", "other"),
                        audit=AuditLinkage(
                            source_file=file_path.name,
                            chunk_id=0,
                            exact_snippet="Agent-interpreted item",
                        ),
                    )
                    updated_items.append(new_item)
                    update_extract_context(extractor, new_item)
            return updated_items
    except Exception as e:
        logger.error(f"Interpretation agent failed: {e}. Falling back to default list.")

    return extracted_line_items
