import json
import logging
from src.utils.tools import find_keyword_contexts, extract_json_from_text

logger = logging.getLogger(__name__)


def run_ebita_agent(
    content: str,
    extractor,
    income_statement_content: str = "",
    is_quarterly: bool = True,
) -> tuple[float, float, list]:
    op_inc = 0.0
    ebita = 0.0
    ebita_adjustments = []

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
        "You are Sir Pennyworth, a senior financial analyst specializing in EBITA adjustments.\n"
        f"Your task is to identify and extract Operating Income directly from the income statement, "
        "identify non-operating/non-recurring operating adjustments (e.g. restructuring charges, asset impairments, "
        "amortization of acquired intangibles in opex) from the income statement and footnotes, and calculate clean Operating EBITA, "
        f"focusing specifically on the {focus_period} time period.\n\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int}\n"
        "- 'get_chunk_by_id': arguments: {'chunk_id': int}\n"
        "- 'finalize': arguments: {\n"
        "    'operating_income': float,\n"
        "    'operating_ebita': float,\n"
        "    'ebita_adjustments': list\n"
        "  }\n\n"
        "Rules:\n"
        "1. You have a maximum of 4 turns. Search for keyword contexts and chunks first to locate the figures.\n"
        "2. Extract Operating Income from the income statement content. Note that if the income statement does not explicitly list it, you must attempt to calculate it starting with a proxy line item that would be close (such as pre-tax income / income before taxes).\n"
        "3. Identify any non-recurring operating adjustments (e.g. restructuring, asset impairments, amortization of acquired intangibles).\n"
        "4. Calculate clean Operating EBITA = Operating Income + EBITA adjustments.\n"
        "5. Standardize positive/negative signs for the calculations and outputs:\n"
        "   - EBITA adjustments are positive if they add back an opex expense (increasing EBITA), and negative if they subtract an operating gain (decreasing EBITA).\n"
        "   - Verify that any number that effectively increases profit is expressed as a positive number.\n"
        "   - Pay special attention to ambiguous items: make sure their sign correctly reflects whether they are a net expense (negative) or net income/benefit (positive).\n"
        "   - Ensure that EBITA and its components in the returned JSON have signs consistent with these rules.\n"
        "6. For adjustments or values not found on the face of the income statement (e.g., found in footnotes or chunk disclosures), you must be extremely careful to use the value corresponding to the three-month period (quarter) rather than the year-to-date (six-month or nine-month) period when the focus period is a quarter. If only a year-to-date value is provided, calculate the quarterly value by subtracting the prior periods' values if available.\n"
        "7. If any individual adjustment value represents a large percentage of EBITA (or Operating Income), you must double-check the text/footnotes to ensure it is the correct value for the focus period and not an incorrect, aggregate, or multi-period value.\n"
        "8. Identify the currency and unit from the extracted income statement content (provided below). Ensure all extracted Operating Income and adjustments are in this same currency and unit (do not convert to USD unless the income statement itself is in USD).\n\n"
        "Example finalize tool call:\n"
        "{\n"
        '  "thought": "I will finalize the extraction. Operating Income is 2000.0. Restructuring of 100.0 needs to be added back. So Operating EBITA is 2100.0.",\n'
        '  "tool": "finalize",\n'
        '  "arguments": {\n'
        '    "operating_income": 2000.0,\n'
        '    "operating_ebita": 2100.0,\n'
        '    "ebita_adjustments": [\n'
        '      {"name": "Restructuring", "value": 100.0}\n'
        "    ]\n"
        "  }\n"
        "}"
    )

    user_content = (
        "Start searching for Operating Income and EBITA adjustments. Remember, you have up to 4 turns.\n"
        "(hint: try searching for keywords like 'restructur', 'amort', 'impair', 'goodwill', 'conting', 'acquire', 'intangible'), "
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
            logger.error(f"EBITA Agent failed at turn {turn}: {e}")
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
            op_inc = float(args.get("operating_income", 0.0))
            ebita = float(args.get("operating_ebita", op_inc))
            ebita_adjustments = args.get("ebita_adjustments", [])
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

    # After the loop finishes:
    try:
        from src.pipeline.curator_agent import CuratorAgent

        ticker = extractor.settings.active_ticker or "UNK"
        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(extractor.settings)
        curator.curate_agent(ticker, "ebita", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for ebita: {e}")

    return op_inc, ebita, ebita_adjustments
