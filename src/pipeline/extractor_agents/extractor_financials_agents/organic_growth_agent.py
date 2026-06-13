import re
import json
import logging
from pathlib import Path
from src.utils.tools import find_keyword_contexts

logger = logging.getLogger(__name__)


def run_organic_growth_agent(
    content: str,
    revenue: float,
    extractor,
    income_statement_content: str = "",
    is_quarterly: bool = True,
) -> tuple[float, float]:
    from src.pipeline.extractor_orchestrator import clean_val

    simple_growth = 0.0
    organic_growth = 0.0

    # Load extraction learnings
    learning_context = ""
    ticker = extractor.settings.active_ticker
    if ticker:
        learning_path = (
            Path(extractor.settings.active_workspace_path)
            / f"{ticker}_extract_learning.md"
        )
        if learning_path.exists():
            try:
                learning_context = learning_path.read_text(encoding="utf-8")
            except Exception:
                pass

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. Your goal is to determine the simple revenue growth and organic revenue growth.\n"
        f"Specifically, we are focused on the {focus_period} time period. Find the growth rates corresponding to this focused period.\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int}\n"
        "- 'finalize': arguments: {'simple_growth': str, 'organic_growth': str}\n\n"
        "Rules:\n"
        "1. Search the document for organic growth, constant currency adjustments, acquisitions, and revenue growth using find_keyword_contexts (hint: potential first keywords to search for include 'organic', 'currency', 'acquisition', 'growth').\n"
        "2. If organic growth or constant currency growth is explicitly reported, extract it. Check if there are M&A contributions that should be backed out.\n"
        "3. If organic growth is NOT explicitly reported, compute it: e.g. Organic Growth = Constant Currency Growth (if reported, otherwise simple growth) - (Acquisition revenue / Total revenue).\n"
        "4. Call 'finalize' with your final extracted/calculated growth rates. You must express the values as percentage float strings (e.g., '18.25%' for 18.25% growth, '8.00%' for 8% growth, or '0.50%' for 0.5% growth). Format the percentage with two decimal places."
    )

    user_content = (
        f"Find simple and organic revenue growth. The reported revenue is {revenue}. You have up to 4 turns. "
        f"(Hint: try searching for keywords like 'organic', 'currency', 'acquisition', 'contribute' or 'growth' first)."
    )
    if learning_context:
        user_content += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learning_context}\n"""'
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
            logger.error(f"Organic Growth Agent failed at turn {turn}: {e}")
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

            def clean_growth_val(val: str) -> float:
                val_str = str(val).strip()
                parsed = clean_val(val_str)
                if "%" not in val_str and abs(parsed) > 1.0:
                    parsed /= 100.0
                return round(parsed, 4)

            simple_growth = clean_growth_val(str(args.get("simple_growth", "0")))
            organic_growth = clean_growth_val(str(args.get("organic_growth", "0")))
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

    # After the loop finishes:
    try:
        from src.pipeline.curator_agent import CuratorAgent

        ticker = extractor.settings.active_ticker or "UNK"
        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(extractor.settings)
        curator.curate_agent(ticker, "organic growth", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for organic growth: {e}")

    if organic_growth == 0.0 and simple_growth != 0.0:
        organic_growth = simple_growth
    return simple_growth, organic_growth
