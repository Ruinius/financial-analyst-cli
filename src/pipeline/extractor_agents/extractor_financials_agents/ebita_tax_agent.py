import re
import json
import logging
from pathlib import Path
from src.utils.tools import find_keyword_contexts

logger = logging.getLogger(__name__)


def run_ebita_and_tax_agent(
    content: str,
    extracted_line_items: list,
    extractor,
    income_statement_content: str = "",
) -> tuple[float, float, float, float, float, list, list]:
    # Check local dictionary classifications to pass as guidance/override
    is_dict_path = Path("src/resources/dictionary/income_statement.md")
    local_dict_guidance = ""
    if is_dict_path.exists():
        local_dict_guidance += f"--- Income Statement Dictionary ---\n{is_dict_path.read_text(encoding='utf-8')}\n"

    keywords = [
        "restructuring",
        "amortization",
        "impairment",
        "write-off",
        "non-recurring",
        "one-time",
        "tax benefit",
        "tax adjustment",
    ]
    snippets = find_keyword_contexts(content, keywords, window=250)
    snippets_text = "\n---\n".join(
        [f"Chunk {s['chunk_id']}: {s['snippet']}" for s in snippets]
    )[:6000]

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst specializing in EBITA adjustments and tax provisions.\n"
        "Your task is to identify and extract key income statement figures directly from the statement (such as Operating Income, "
        "Income Before Taxes, and Reported Tax Provision), identify non-operating/non-recurring adjustments and non-recurring tax "
        "benefits from footnotes, and calculate adjusted taxes and EBITA.\n"
        "Rules:\n"
        "1. Extract Reported Operating Income, Reported Income Before Taxes, and Reported Tax Provision from the income statement content.\n"
        "2. Identify any non-recurring adjustments (e.g. restructuring, asset impairments, amortization of intangibles).\n"
        "3. Back out the tax effect of non-operating adjustments at a statutory rate of 25% (21% federal, 4% state/local).\n"
        "4. Identify any non-recurring tax benefits/credits in the footnotes.\n"
        "5. Calculate clean Operating EBITA = Operating Income + Non-Operating/Non-recurring adjustments.\n"
        "6. Calculate Adjusted Taxes = Reported Tax Provision + Tax effect of adjustments - non-recurring tax benefits.\n"
        "7. Standardize positive/negative signs for the calculations and outputs:\n"
        "   - Verify that any number that subtracts from the revenue is an expense, cost, or loss, and is expressed as a negative number. This includes the Reported Tax Provision (expressed as negative if it is a tax expense, and positive only if it is a tax benefit/credit).\n"
        "   - Verify that any number that effectively increases profit (e.g. revenue, interest income, tax benefits, gains) is expressed as a positive number.\n"
        "   - Pay special attention to ambiguous items: make sure their sign correctly reflects whether they are a net expense (negative) or net income/benefit (positive) in the context of the statements.\n"
        "   - For the tax effect of non-operating adjustments (tax_adjustments): a positive value indicates a tax benefit/credit or addition (reducing tax expense/provision), and a negative value indicates a tax expense (increasing tax provision).\n"
        "   - Ensure that EBITA, Adjusted Taxes, and their components in the returned JSON have signs consistent with these rules so that math checks (e.g. Adjusted Taxes = Reported Tax Provision + Tax effect of adjustments - non-recurring tax benefits) work correctly.\n"
        "8. Reasoning rules for tax adjustments direction:\n"
        "   - When backing out non-operating adjustments (such as amortization and restructuring) to calculate Operating EBITA:\n"
        "     - If an adjustment is positive (increases EBITA), its associated tax adjustment (tax effect at 25% statutory rate) must increase the Adjusted Taxes (making the tax provision more negative, since expenses are expressed as negative).\n"
        "     - If an adjustment is negative (decreases EBITA), its associated tax adjustment must decrease the Adjusted Taxes (making it more positive, since expenses are expressed as negative).\n"
        "     - Exception: Write-offs, asset write-downs, or goodwill/asset impairments typically have a tax impact of 0%, so they increase EBITA but have 0.0 associated tax adjustment.\n\n"
        "Please return a JSON object with:\n"
        "{\n"
        '  "operating_income": 2332.0,\n'
        '  "income_before_taxes": 2406.0,\n'
        '  "reported_tax_provision": -519.0,\n'
        '  "operating_ebita": 2336.0,\n'
        '  "adjusted_taxes": -518.0,\n'
        '  "ebita_adjustments": [\n'
        '    {"name": "Restructuring", "value": 4.0}\n'
        "  ],\n"
        '  "tax_adjustments": [\n'
        '    {"name": "Tax effect of restructuring at 25%", "value": 1.0}\n'
        "  ]\n"
        "}"
    )

    prompt = ""
    if income_statement_content:
        prompt += f'Extracted Income Statement:\n"""\n{income_statement_content}\n"""\n'

    if local_dict_guidance:
        prompt += f"\nLocal Dictionary Guidance:\n{local_dict_guidance}\n"

    prompt += f"""
Footnote Snippets:
\"\"\"
{snippets_text}
\"\"\"

Please identify the key income statement figures, any adjustments, and return a JSON object with:
{{
  "operating_income": 2332.0,
  "income_before_taxes": 2406.0,
  "reported_tax_provision": -519.0,
  "operating_ebita": 2336.0,
  "adjusted_taxes": -518.0,
  "ebita_adjustments": [
    {{"name": "Adjustment Name", "value": 12.3}}
  ],
  "tax_adjustments": [
    {{"name": "Adjustment Name", "value": 4.5}}
  ]
}}
"""
    try:
        resp = extractor.llm.generate(
            prompt, system_prompt=sys_prompt, stream_thinking=True
        )
        json_match = re.search(r"\{.*\}", resp, re.DOTALL)
        if not json_match:
            raise ValueError("LLM response did not contain a valid JSON object.")
        data = json.loads(json_match.group(0))
        op_inc = float(data.get("operating_income", 0.0))
        inc_bt = float(data.get("income_before_taxes", 0.0))
        rep_tax = float(data.get("reported_tax_provision", 0.0))
        ebita = float(data.get("operating_ebita", op_inc))
        adj_taxes = float(data.get("adjusted_taxes", rep_tax))
        ebita_adjustments = data.get("ebita_adjustments", [])
        tax_adjustments = data.get("tax_adjustments", [])
        return (
            op_inc,
            inc_bt,
            rep_tax,
            ebita,
            adj_taxes,
            ebita_adjustments,
            tax_adjustments,
        )
    except Exception as e:
        logger.error(f"Operating EBITA / Tax Agent failed: {e}")
        raise e
