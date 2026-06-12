import re
import json
import logging
from src.utils.tools import find_keyword_contexts

logger = logging.getLogger(__name__)


def run_diluted_shares_agent(
    content: str,
    extractor,
    income_statement_content: str = "",
    is_quarterly: bool = True,
) -> tuple[float, float]:
    from src.pipeline.extractor_orchestrator import clean_val

    basic_shares = 0.0
    diluted_shares = 0.0

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    sys_prompt = (
        "You are Sir Pennyworth, a precise financial analyst. Your goal is to find the exact basic and diluted shares outstanding in the document.\n"
        f"Specifically, we are focused on the {focus_period} time period. Ensure you find the shares outstanding corresponding to this focused period.\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int}\n"
        "- 'finalize': arguments: {'basic_shares': str, 'diluted_shares': str}\n\n"
        "Example format:\n"
        "{\n"
        '  "thought": "I will search for keyword contexts to locate shares outstanding.",\n'
        '  "tool": "find_keyword_contexts",\n'
        '  "arguments": {"keywords": ["shares outstanding", "weighted average shares"]}\n'
        "}\n\n"
        "Rules:\n"
        "1. You have a maximum of 4 turns. Search for keyword contexts first.\n"
        "2. When you find the values, call 'finalize' with the basic and diluted shares. You must express the values as float strings in millions of shares, formatted with two decimal places (e.g., '280.00' for 280 million shares, or '283.13' for 283,125,000 shares). Do not write 'million' or include commas in the values."
    )

    user_content = "Start searching for basic and diluted shares outstanding. Remember, you have up to 4 turns."
    if income_statement_content:
        user_content += f'\n\nHere is the already extracted Income Statement for your reference:\n"""\n{income_statement_content}\n"""'

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
                "\n\nCRITICAL: This is your final turn (turn 4 of 4). You must call the 'finalize' tool immediately with your current best estimates. Do not call find_keyword_contexts again."
            )

        prompt = ""
        for h in history:
            prompt += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"
        try:
            resp = extractor.llm.generate(prompt, system_prompt=sys_prompt).strip()
        except Exception as e:
            logger.error(f"Diluted Shares Agent failed at turn {turn}: {e}")
            break

        history.append({"role": "assistant", "content": resp})

        json_match = re.search(r"\{.*\}", resp, re.DOTALL)
        if not json_match:
            history.append(
                {
                    "role": "user",
                    "content": "Error: Your response did not contain a valid JSON tool call.",
                }
            )
            continue
        try:
            action = json.loads(json_match.group(0))
        except Exception as e:
            history.append({"role": "user", "content": f"Error parsing JSON: {e}"})
            continue

        tool = action.get("tool")
        args = action.get("arguments", {})

        if tool == "finalize":
            basic_shares = clean_val(str(args.get("basic_shares", "0")))
            diluted_shares = clean_val(str(args.get("diluted_shares", "0")))
            break
        elif tool == "find_keyword_contexts":
            kw = args.get("keywords", [])
            window = args.get("window", 200)
            res = str(find_keyword_contexts(content, kw, window))
            history.append(
                {
                    "role": "user",
                    "content": f"Observation from find_keyword_contexts:\n{res[:4000]}",
                }
            )
        else:
            history.append({"role": "user", "content": f"Error: Unknown tool {tool}"})

    return basic_shares, diluted_shares
