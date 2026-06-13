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
    is_quarterly: bool = True,
) -> tuple[float, float, float, float, float, list, list]:
    op_inc = 0.0
    inc_bt = 0.0
    rep_tax = 0.0
    ebita = 0.0
    adj_taxes = 0.0
    ebita_adjustments = []
    tax_adjustments = []

    # Check local dictionary classifications to pass as guidance/override
    is_dict_path = Path("src/resources/dictionary/income_statement.md")
    local_dict_guidance = ""
    if is_dict_path.exists():
        local_dict_guidance += f"--- Income Statement Dictionary ---\n{is_dict_path.read_text(encoding='utf-8')}\n"

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst specializing in EBITA adjustments and tax provisions.\n"
        f"Your task is to identify and extract key income statement figures directly from the statement (such as Operating Income, "
        "Income Before Taxes, and Reported Tax Provision), identify non-operating/non-recurring adjustments and non-recurring tax "
        f"benefits from footnotes, and calculate adjusted taxes and EBITA, focusing specifically on the {focus_period} time period.\n\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int}\n"
        "- 'get_chunk_by_id': arguments: {'chunk_id': int}\n"
        "- 'finalize': arguments: {\n"
        "    'operating_income': float,\n"
        "    'income_before_taxes': float,\n"
        "    'reported_tax_provision': float,\n"
        "    'operating_ebita': float,\n"
        "    'adjusted_taxes': float,\n"
        "    'ebita_adjustments': list,\n"
        "    'tax_adjustments': list\n"
        "  }\n\n"
        "Rules:\n"
        "1. You have a maximum of 4 turns. Search for keyword contexts and chunks first to locate the figures.\n"
        "2. Extract Reported Operating Income, Reported Income Before Taxes, and Reported Tax Provision from the income statement content.\n"
        "3. Identify any non-recurring adjustments (e.g. restructuring, asset impairments, amortization of intangibles).\n"
        "4. Back out the tax effect of non-operating adjustments at a statutory rate of 25% (21% federal, 4% state/local). This includes:\n"
        "   - Items that take Operating Income to Operating EBITA (e.g., restructuring, amortization).\n"
        "   - Non-operating items that bridge Income Before Taxes to Operating Income (e.g., interest expense, interest income, non-operating gains/losses).\n"
        "5. Identify any non-recurring tax benefits/credits in the footnotes.\n"
        "6. Calculate clean Operating EBITA = Operating Income + Non-Operating/Non-recurring adjustments.\n"
        "7. Calculate Adjusted Taxes = Reported Tax Provision + Tax effect of adjustments - non-recurring tax benefits.\n"
        "8. Standardize positive/negative signs for the calculations and outputs:\n"
        "   - Verify that any number that subtracts from the revenue is an expense, cost, or loss, and is expressed as a negative number. This includes the Reported Tax Provision (expressed as negative if it is a tax expense, and positive only if it is a tax benefit/credit).\n"
        "   - Verify that any number that effectively increases profit (e.g. revenue, interest income, tax benefits, gains) is expressed as a positive number.\n"
        "   - Pay special attention to ambiguous items: make sure their sign correctly reflects whether they are a net expense (negative) or net income/benefit (positive) in the context of the statements.\n"
        "   - For the tax effect of non-operating adjustments (tax_adjustments): a positive value indicates a tax benefit/credit (reducing tax expense), and a negative value indicates a tax expense (increasing overall tax expense).\n"
        "   - Ensure that EBITA, Adjusted Taxes, and their components in the returned JSON have signs consistent with these rules so that math checks (e.g. Adjusted Taxes = Reported Tax Provision + Tax effect of adjustments - non-recurring tax benefits) work correctly.\n"
        "9. Reasoning rules for tax adjustments direction:\n"
        "   - When backing out non-operating adjustments to calculate Operating EBITA and Adjusted Taxes:\n"
        "     - EBITA adjustments are positive if they add back an expense (increasing EBITA), and negative if they subtract a gain (decreasing EBITA).\n"
        "     - Non-operating bridge items (like interest expense or interest income) must be tax-adjusted as well. An interest expense add-back is a positive pre-tax adjustment (since interest expense was subtracted to get Income Before Taxes). An interest income subtraction is a negative pre-tax adjustment.\n"
        "     - A positive adjustment increases taxable operating profit. Therefore, it increases tax expense (making the tax adjustment a negative value, representing additional tax expense).\n"
        "     - A negative adjustment decreases taxable operating profit. Therefore, it decreases tax expense (making the tax adjustment a positive value, representing a tax benefit/reduction).\n"
        "     - Exception: Non-deductible items like goodwill impairments have a tax impact of 0%, so they increase EBITA but have 0.0 associated tax adjustment.\n\n"
        "Example finalize tool call:\n"
        "{\n"
        '  "thought": "I will finalize the extraction. Operating Income is 2000.0. Operating EBITA is 2100.0 (restructuring of 100.0 added back). Reported pre-tax income is 1600.0 because of -400.0 interest expense. Tax rate is 25%. Restructuring tax effect is -25.0. Interest expense tax effect is -100.0. Total Adjusted Taxes is -400.0 (Reported Tax Provision) + -25.0 + -100.0 = -525.0.",\n'
        '  "tool": "finalize",\n'
        '  "arguments": {\n'
        '    "operating_income": 2000.0,\n'
        '    "income_before_taxes": 1600.0,\n'
        '    "reported_tax_provision": -400.0,\n'
        '    "operating_ebita": 2100.0,\n'
        '    "adjusted_taxes": -525.0,\n'
        '    "ebita_adjustments": [\n'
        '      {"name": "Restructuring", "value": 100.0}\n'
        "    ],\n"
        '    "tax_adjustments": [\n'
        '      {"name": "Tax effect of restructuring at 25%", "value": -25.0},\n'
        '      {"name": "Tax effect of interest expense at 25%", "value": -100.0}\n'
        "    ]\n"
        "  }\n"
        "}"
    )

    user_content = (
        "Start searching for EBITA adjustments and tax provisions. Remember, you have up to 4 turns.\n"
        "Here are some useful keywords to search for if needed: restructuring, amortization, impairment, "
        "write-off, non-recurring, one-time, tax benefit, tax adjustment, contingency, provision."
    )
    if income_statement_content:
        user_content += f'\n\nHere is the already extracted Income Statement for your reference:\n"""\n{income_statement_content}\n"""'

    if local_dict_guidance:
        user_content += f"\n\nLocal Dictionary Guidance:\n{local_dict_guidance}\n"

    history = [
        {
            "role": "user",
            "content": user_content,
        }
    ]

    for turn in range(4):
        if turn == 3:
            # We are on the last turn, append a strict instruction to finalize
            history[-1]["content"] += (
                "\n\nCRITICAL: This is your final turn (turn 4 of 4). You must call the 'finalize' tool immediately with your current best estimates. Do not call find_keyword_contexts or get_chunk_by_id again."
            )

        prompt = ""
        for h in history:
            prompt += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        try:
            resp = extractor.llm.generate(
                prompt, system_prompt=sys_prompt, stream_thinking=True
            ).strip()
        except Exception as e:
            logger.error(f"EBITA/Tax Agent failed at turn {turn}: {e}")
            break

        history.append({"role": "assistant", "content": resp})

        json_match = re.search(r"\{.*\}", resp, re.DOTALL)
        if not json_match:
            history.append(
                {
                    "role": "user",
                    "content": "Error: Your response did not contain a valid JSON tool call. Please respond using the specified JSON schema.",
                }
            )
            continue

        try:
            action = json.loads(json_match.group(0))
        except Exception as e:
            history.append(
                {
                    "role": "user",
                    "content": f"Error: Failed to parse JSON tool call: {e}. Please respond using a valid JSON schema.",
                }
            )
            continue

        tool = action.get("tool")
        args = action.get("arguments", {})

        if tool == "finalize":
            op_inc = float(args.get("operating_income", 0.0))
            inc_bt = float(args.get("income_before_taxes", 0.0))
            rep_tax = float(args.get("reported_tax_provision", 0.0))
            ebita = float(args.get("operating_ebita", op_inc))
            adj_taxes = float(args.get("adjusted_taxes", rep_tax))
            ebita_adjustments = args.get("ebita_adjustments", [])
            tax_adjustments = args.get("tax_adjustments", [])
            break
        elif tool == "find_keyword_contexts":
            kw = args.get("keywords", [])
            window = args.get("window", 250)
            res = str(find_keyword_contexts(content, kw, window))
            history.append(
                {
                    "role": "user",
                    "content": f"Observation from find_keyword_contexts:\n{res[:4000]}",
                }
            )
        elif tool == "get_chunk_by_id":
            try:
                chunk_id = int(args.get("chunk_id", 0))
                from src.pipeline.extractor_orchestrator import (
                    get_chunk_by_id as orchestrator_get_chunk,
                )

                res = orchestrator_get_chunk(content, chunk_id)
                if not res:
                    res = f"Chunk {chunk_id} not found or empty."
            except Exception as e:
                res = f"Error: {e}"
            history.append(
                {
                    "role": "user",
                    "content": f"Observation from get_chunk_by_id:\n{res[:4000]}",
                }
            )
        else:
            history.append(
                {
                    "role": "user",
                    "content": f"Error: Unknown tool '{tool}'. Please use find_keyword_contexts, get_chunk_by_id, or finalize.",
                }
            )

    return (
        op_inc,
        inc_bt,
        rep_tax,
        ebita,
        adj_taxes,
        ebita_adjustments,
        tax_adjustments,
    )
