import json
import logging
from pathlib import Path
from src.utils.tools import extract_json_from_text
from src.tools.pull_markdown import pull_markdown_file
from typing import Dict, Any

from src.services.llm_client import LLMClient
from src.core.exceptions import LLMError

logger = logging.getLogger(__name__)


def run_margin_agent(
    ticker: str,
    workspace: Path,
    base_margin: float,
    margin_yr5: float,
    terminal_margin: float,
    llm: LLMClient,
    learning_context: str = "",
) -> Dict[str, Any]:
    """
    Run the agentic EBITA margins calculation workflow.
    Executes up to 4 turns, enabling Sir Pennyworth to pull financial and qualitative trend markdowns,
    analyze margin metrics, and finalize three EBITA margin assumptions (base_margin, margin_yr5, terminal_margin).
    """
    # 1. Discover available files or load folder index if available
    extracted_dir = workspace / "4_extracted_data"
    analysis_dir = workspace / "5_historical_analysis"

    index_path = workspace / f"{ticker}_folder_index.md"
    if index_path.exists():
        try:
            files_catalog_str = index_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not read index file: {e}")
            index_path = None

    if not index_path or not index_path.exists():
        available_files = []
        if extracted_dir.exists():
            for p in extracted_dir.glob("*.md"):
                available_files.append(p.name)
        if analysis_dir.exists():
            for p in analysis_dir.glob("*.md"):
                available_files.append(p.name)
        files_catalog_str = "\n".join(f"- {f}" for f in sorted(available_files))

    # Read starting documents
    def read_opt(p: Path) -> str:
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception as e:
                return f"Error reading file: {e}"
        return "Not available."

    financials_quarter_str = read_opt(analysis_dir / "financials_quarter.md")
    analyst_views_str = read_opt(analysis_dir / "analyst_views.md")
    news_trend_str = read_opt(analysis_dir / "news_trend.md")
    transcript_trend_str = read_opt(analysis_dir / "transcript_trend.md")

    # Default results in case of failure or empty response
    final_margin_results = {
        "base_margin": base_margin,
        "margin_yr5": margin_yr5,
        "terminal_margin": terminal_margin,
        "explanation": "Default backup EBITA margins calculated without agent details.",
    }

    # System prompt outlining roles, tools, and expectations
    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. Your goal is to determine three future EBITA margins for a valuation model with a detailed rationale:\n"
        "1. base_margin: Near-term / base starting EBITA margin (often based on historical EBITA run-rate or recent quarters).\n"
        "2. margin_yr5: Mid-term Year 5 target EBITA margin (where operating margins mature to by year 5).\n"
        "3. terminal_margin: Long-term / Terminal EBITA margin (stable margin beyond year 10, typically stable depending on market share and moat).\n\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'pull_markdown_file': arguments: {'file_name': str}\n"
        "  Retrieves contents of a file. Use this to pull specific quarterly or annual extracted summaries/files if you need deep-dives.\n"
        "- 'finalize': arguments: {'base_margin': float, 'margin_yr5': float, 'terminal_margin': float, 'explanation': str}\n"
        "  Finalize the execution and present the final parameters.\n\n"
        "Rules:\n"
        "1. Identify historical EBITA margins, cost structures, operating leverage, qualitative margin outlooks, news trends, and conference call transcripts details.\n"
        "2. Think step-by-step about what the right three EBITA margins should be and construct a strong rationale.\n"
        "3. Call 'finalize' on your last turn. The explanation must describe the line items, trends, or source details extracted and your reasoning."
    )

    user_content = (
        f"Estimate the EBITA margin assumptions for {ticker}. You have up to 4 turns.\n\n"
        f"**Starting Default Estimations:**\n"
        f"- Base (Starting) Margin: {base_margin * 100:.2f}%\n"
        f"- Target Year 5 Margin: {margin_yr5 * 100:.2f}%\n"
        f"- Terminal Margin: {terminal_margin * 100:.2f}%\n\n"
        f"**Available Files Catalog in Workspace:**\n"
        f"{files_catalog_str}\n\n"
        f"--- STARTING DOCUMENTS ---\n\n"
        f"### financials_quarter.md\n"
        f'"""\n{financials_quarter_str[:6000]}\n"""\n\n'
        f"### analyst_views.md\n"
        f'"""\n{analyst_views_str[:6000]}\n"""\n\n'
        f"### news_trend.md\n"
        f'"""\n{news_trend_str[:4000]}\n"""\n\n'
        f"### transcript_trend.md\n"
        f'"""\n{transcript_trend_str[:4000]}\n"""\n'
    )
    if learning_context:
        user_content += f'\n\nHere is the active company modeling learning context to guide your decisions:\n"""\n{learning_context}\n"""'

    history = [
        {
            "role": "user",
            "content": user_content,
        }
    ]

    for turn in range(4):
        if turn == 3:
            history[-1]["content"] += (
                "\n\nCRITICAL: This is your final turn (turn 4 of 4). You must call the 'finalize' tool immediately with your current best estimates."
            )

        prompt_str = ""
        for h in history:
            prompt_str += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        try:
            resp = llm.generate(prompt_str, system_prompt=sys_prompt).strip()
        except Exception as e:
            logger.error(f"Margin Agent failed at turn {turn}: {e}")
            raise LLMError(
                f"Margin Agent failed during LLM generation at turn {turn}: {e}"
            ) from e

        history.append({"role": "assistant", "content": resp})

        json_str = extract_json_from_text(resp)
        if not json_str:
            history.append(
                {
                    "role": "user",
                    "content": "Error: Your response did not contain a valid JSON tool call.",
                }
            )
            continue

        try:
            action = json.loads(json_str)
        except Exception as e:
            history.append({"role": "user", "content": f"Error parsing JSON: {e}"})
            continue

        tool = action.get("tool")
        args = action.get("arguments", {})

        if tool == "finalize":
            final_margin_results["base_margin"] = float(
                args.get("base_margin", base_margin)
            )
            final_margin_results["margin_yr5"] = float(
                args.get("margin_yr5", margin_yr5)
            )
            final_margin_results["terminal_margin"] = float(
                args.get("terminal_margin", terminal_margin)
            )
            final_margin_results["explanation"] = str(args.get("explanation", ""))
            break

        elif tool == "pull_markdown_file":
            file_name = args.get("file_name", "")
            res = pull_markdown_file(workspace, file_name)
            # Truncate content to keep prompt window within reasonable limits
            history.append(
                {
                    "role": "user",
                    "content": f"Observation from pull_markdown_file:\n{res[:8000]}",
                }
            )

        else:
            history.append({"role": "user", "content": f"Error: Unknown tool '{tool}'"})
    else:
        raise LLMError(
            "Margin Agent failed to finalize EBITA margin assumptions within the maximum turn limit."
        )

    # Trigger Curator Agent to capture lessons in model_learning.md
    try:
        from src.agents.curator_agent import CuratorAgent

        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(llm.settings)
        curator.curate_model_agent(ticker, "Margin", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for Margin agent: {e}")

    return final_margin_results
