import json
import logging
from src.tools.keyword_search import find_keyword_contexts
from src.utils.tools import extract_json_from_text

logger = logging.getLogger(__name__)


def run_tax_agent(
    content: str,
    extractor,
    operating_income: float,
    operating_ebita: float,
    ebita_adjustments: list,
    income_statement_content: str = "",
    is_quarterly: bool = True,
) -> tuple[float, float, float, list]:
    inc_bt = 0.0
    rep_tax = 0.0
    adj_taxes = 0.0
    tax_adjustments = []

    # Load extraction learnings
    learning_context = extractor.get_extract_context()

    # Check local dictionary classifications to pass as guidance/override
    local_dict_guidance = ""
    is_dict = extractor.get_dictionary("income_statement")
    if is_dict:
        local_dict_guidance += f"--- Income Statement Dictionary ---\n{is_dict}\n"

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst specializing in tax provisions and adjustments.\n"
        f"Your task is to identify key income statement figures directly from the statement (specifically "
        "Income Before Taxes and Reported Tax Provision), identify non-operating bridge items and non-recurring tax "
        "benefits from footnotes, and calculate adjusted taxes, focusing specifically on the "
        f"{focus_period} time period.\n\n"
        "You have been provided with the already extracted Operating Income, Operating EBITA, and EBITA adjustments from a prior stage.\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int}\n"
        "- 'get_chunk_by_id': arguments: {'chunk_id': int}\n"
        "- 'finalize': arguments: {\n"
        "    'income_before_taxes': float,\n"
        "    'reported_tax_provision': float,\n"
        "    'adjusted_taxes': float,\n"
        "    'tax_adjustments': list\n"
        "  }\n\n"
        "Rules:\n"
        "1. You have a maximum of 4 turns. Search for keyword contexts and chunks first to locate the figures.\n"
        "2. Extract Reported Income Before Taxes and Reported Tax Provision from the income statement content.\n"
        "3. Back out the tax effect of non-operating adjustments at a statutory rate of 25% (21% federal, 4% state/local). This includes:\n"
        "   - The EBITA adjustments identified by the EBITA agent (e.g. restructuring, amortization).\n"
        "   - Non-operating items that bridge Income Before Taxes to Operating Income (e.g., interest expense, interest income, non-operating gains/losses).\n"
        "4. Identify any non-recurring tax benefits/credits in the footnotes.\n"
        "5. Calculate Adjusted Taxes = Reported Tax Provision + Tax effect of adjustments - non-recurring tax benefits.\n"
        "6. Standardize positive/negative signs for the calculations and outputs:\n"
        "   - The Reported Tax Provision is expressed as a negative number if it is a tax expense, and positive only if it is a tax benefit/credit.\n"
        "   - For the tax effect of non-operating adjustments (tax_adjustments): a positive value indicates a tax benefit/credit (reducing tax expense), and a negative value indicates a tax expense (increasing overall tax expense).\n"
        "   - Ensure that Adjusted Taxes and their components in the returned JSON have signs consistent with these rules so that math checks (e.g. Adjusted Taxes = Reported Tax Provision + Tax effect of adjustments - non-recurring tax benefits) work correctly.\n"
        "7. Reasoning rules for tax adjustments direction:\n"
        "   - When backing out adjustments to calculate Adjusted Taxes:\n"
        "     - Non-operating bridge items (like interest expense or interest income) must be tax-adjusted as well. An interest expense add-back is a positive pre-tax adjustment (since interest expense was subtracted to get Income Before Taxes). An interest income subtraction is a negative pre-tax adjustment.\n"
        "     - A positive adjustment increases taxable operating profit. Therefore, it increases tax expense (making the tax adjustment a negative value, representing additional tax expense).\n"
        "     - A negative adjustment decreases taxable operating profit. Therefore, it decreases tax expense (making the tax adjustment a positive value, representing a tax benefit/reduction).\n"
        "     - Exception: Non-deductible items like goodwill impairments have a tax impact of 0%, so they have 0.0 associated tax adjustment.\n"
        "8. Identify the currency and unit from the extracted income statement content (provided below). Ensure all pre-tax income, reported tax provision, and tax adjustments are in this same currency and unit (do not convert to USD unless the income statement itself is in USD).\n\n"
        "Example finalize tool call:\n"
        "{\n"
        '  "thought": "I will finalize the extraction. Reported pre-tax income is 1600.0. Tax rate is 25%. Restructuring tax effect of -25.0 (based on 100.0 EBITA adjustment) and interest expense tax effect of -100.0. Total Adjusted Taxes is -400.0 (Reported Tax Provision) + -25.0 + -100.0 = -525.0.",\n'
        '  "tool": "finalize",\n'
        '  "arguments": {\n'
        '    "income_before_taxes": 1600.0,\n'
        '    "reported_tax_provision": -400.0,\n'
        '    "adjusted_taxes": -525.0,\n'
        '    "tax_adjustments": [\n'
        '      {"name": "Tax effect of restructuring at 25%", "value": -25.0},\n'
        '      {"name": "Tax effect of interest expense at 25%", "value": -100.0}\n'
        "    ]\n"
        "  }\n"
        "}"
    )

    user_content = (
        "Start searching for tax provisions and non-operating bridge items. Remember, you have up to 4 turns.\n"
        f"The EBITA Agent has already determined:\n"
        f"- Operating Income: {operating_income}\n"
        f"- Operating EBITA: {operating_ebita}\n"
        f"- EBITA Adjustments: {json.dumps(ebita_adjustments)}\n\n"
        "Here are some useful keywords to search for if needed: interest, gain, loss, tax benefit, tax adjustment, provision, statutory."
    )
    if learning_context:
        user_content += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learning_context}\n"""'
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
            logger.error(f"Tax Agent failed at turn {turn}: {e}")
            break

        history.append({"role": "assistant", "content": resp})

        json_str = extract_json_from_text(resp)
        if not json_str:
            history.append(
                {
                    "role": "user",
                    "content": "Error: Your response did not contain a valid JSON tool call. Please respond using the specified JSON schema.",
                }
            )
            continue

        try:
            action = json.loads(json_str)
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
            inc_bt = float(args.get("income_before_taxes", 0.0))
            rep_tax = float(args.get("reported_tax_provision", 0.0))
            adj_taxes = float(args.get("adjusted_taxes", rep_tax))
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
                from src.tools.find_chunk import (
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

    # After the loop finishes:
    try:
        from src.pipeline.curator_agent import CuratorAgent

        ticker = extractor.settings.active_ticker or "UNK"
        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(extractor.settings)
        curator.curate_agent(ticker, "tax", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for tax: {e}")

    return inc_bt, rep_tax, adj_taxes, tax_adjustments
