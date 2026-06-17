import re
import json
import logging
from pathlib import Path
from typing import Dict, Any

from src.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


def run_non_operating_agent(
    ticker: str,
    workspace: Path,
    llm: LLMClient,
) -> Dict[str, Any]:
    """
    Run the single-turn agent to extract non-operating categories from
    the latest extracted financials markdown and balance sheet.
    """
    extracted_dir = workspace / "4_extracted_data"

    # Discovery logic
    extracted_files = []
    if extracted_dir.exists():
        for p in extracted_dir.glob("*_extracted.md"):
            match = re.match(r"^(\d{8})_", p.name)
            if match:
                date_str = match.group(1)
                extracted_files.append((date_str, p))

    extracted_files.sort(key=lambda x: x[0], reverse=True)

    latest_extracted_file = None
    extracted_content = ""
    balance_sheet_content = ""

    for date_str, file_path in extracted_files:
        content = file_path.read_text(encoding="utf-8")
        if (
            "#### Non-Operating Assets" in content
            or "#### Non-Operating Liabilities" in content
        ):
            latest_extracted_file = file_path
            # Find the corresponding balance sheet file
            stem_without_extracted = file_path.name.replace("_extracted.md", "")
            bs_file = extracted_dir / f"{stem_without_extracted}_balance_sheet.md"
            if bs_file.exists():
                balance_sheet_content = bs_file.read_text(encoding="utf-8")
            extracted_content = content
            break

    # If no file found, fallback to defaults
    if not latest_extracted_file:
        logger.warning(
            f"No extracted financial files found containing non-operating sections for {ticker}."
        )
        return {
            "cash": 0.0,
            "short_term_investments": 0.0,
            "debt": 0.0,
            "preferred_equity": 0.0,
            "minority_interest": 0.0,
            "other_financial": 0.0,
            "explanation": "Default backup non-operating values (0.0) used because no matching extracted files were found.",
        }

    # Extract non-operating sections from the extracted file
    non_op_assets_section = ""
    non_op_liab_section = ""

    assets_match = re.search(
        r"(#### Non-Operating Assets.*?(?=####|\n---\n|##|$))",
        extracted_content,
        re.DOTALL,
    )
    if assets_match:
        non_op_assets_section = assets_match.group(1).strip()

    liab_match = re.search(
        r"(#### Non-Operating Liabilities.*?(?=####|\n---\n|##|$))",
        extracted_content,
        re.DOTALL,
    )
    if liab_match:
        non_op_liab_section = liab_match.group(1).strip()

    # Load the dictionary
    dict_path = Path("src/resources/dictionary/balance_sheet.md")
    dictionary_content = ""
    if dict_path.exists():
        dictionary_content = dict_path.read_text(encoding="utf-8")

    # Define system prompt
    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. Your task is to extract and categorize the company's non-operating balance sheet line items into the following 6 categories:\n"
        "1. cash: Cash and cash equivalents (plus restricted cash).\n"
        "2. short_term_investments: Marketable securities, short-term investments, liquid investments.\n"
        "3. debt: Short-term debt, long-term debt, lease liabilities (if non-operating), notes payable, commercial paper, convertible debt.\n"
        "4. preferred_equity: Preferred stock, mezzanine equity.\n"
        "5. minority_interest: Non-controlling interests, redeemable non-controlling interests.\n"
        "6. other_financial: Other non-operating physical/financial assets (e.g. equity method investments, assets held for sale, pension assets, due from related parties) MINUS other non-operating liabilities (e.g. dividends payable, pension liabilities, liabilities held for sale, litigation accruals, other accrued non-operating liabilities).\n\n"
        "Rules:\n"
        "1. Examine the provided sections: Non-Operating Assets, Non-Operating Liabilities, and the full Balance Sheet markdown.\n"
        "2. Cross-reference with the Classification Table in the Balance Sheet Dictionary to map line items to categories.\n"
        "3. For each category, sum the values of all corresponding line items. (All values are typically in millions, keep them scaled exactly as they are in the balance sheet).\n"
        "4. For 'other_financial', calculate: (Sum of non-operating assets in 'other_financial_physical_assets') minus (Sum of non-operating liabilities in 'other_financial_liabilities').\n"
        "5. If a category has no items, its value should be 0.0.\n"
        "6. You must return a valid JSON object matching the JSON schema below and nothing else."
    )

    prompt = f"""
Here is the context for the active company ticker: {ticker}

### Non-Operating Assets Section from Extracted Markdown:
{non_op_assets_section}

### Non-Operating Liabilities Section from Extracted Markdown:
{non_op_liab_section}

### Full Balance Sheet (Latest):
{balance_sheet_content}

### Balance Sheet Dictionary (for classifications):
{dictionary_content}

Extract the non-operating categories and return the JSON object matching this structure:
{{
  "cash": 0.0,
  "short_term_investments": 0.0,
  "debt": 0.0,
  "preferred_equity": 0.0,
  "minority_interest": 0.0,
  "other_financial": 0.0,
  "explanation": "Detailed explanation of which line items were mapped to which category, their values, and the math used."
}}
"""

    final_results = {
        "cash": 0.0,
        "short_term_investments": 0.0,
        "debt": 0.0,
        "preferred_equity": 0.0,
        "minority_interest": 0.0,
        "other_financial": 0.0,
        "explanation": "Default backup non-operating values used.",
    }

    try:
        resp = llm.generate(prompt, system_prompt=sys_prompt).strip()
        json_match = re.search(r"\{.*\}", resp, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            final_results["cash"] = float(data.get("cash", 0.0))
            final_results["short_term_investments"] = float(
                data.get("short_term_investments", 0.0)
            )
            final_results["debt"] = float(data.get("debt", 0.0))
            final_results["preferred_equity"] = float(data.get("preferred_equity", 0.0))
            final_results["minority_interest"] = float(
                data.get("minority_interest", 0.0)
            )
            final_results["other_financial"] = float(data.get("other_financial", 0.0))
            final_results["explanation"] = str(data.get("explanation", ""))
        else:
            logger.error("LLM did not return a valid JSON in non-operating agent.")
    except Exception as e:
        logger.error(f"Non-Operating Agent failed: {e}")

    # Trigger Curator Agent to capture lessons in model_learning.md
    try:
        from src.pipeline.curator_agent import CuratorAgent

        history_text = f"User: Extract non-operating items.\nAssistant: {json.dumps(final_results, indent=2)}"
        curator = CuratorAgent(llm.settings)
        curator.curate_model_agent(ticker, "Non-Operating", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for Non-Operating agent: {e}")

    return final_results
