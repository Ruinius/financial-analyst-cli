import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple
from src.utils.tools import extract_json_from_text
from src.services.llm_client import LLMClient
from src.core.exceptions import LLMError
from src.tools.pull_markdown import pull_markdown_file

logger = logging.getLogger(__name__)


def run_dcf_modeling_agent(
    ticker: str,
    workspace: Path,
    base_assumptions: Dict[str, Any],
    llm: LLMClient,
    learning_context: str = "",
) -> Tuple[Dict[str, Any], str, str]:
    """
    Run a 10-turn DCF modeling agent.
    Sanity-checks the model inputs, tests valuation scenarios, corrects obvious errors
    (e.g., currency, shares outstanding, non-operating items), and writes comments/critique
    on the valuation results and assumptions.

    Returns:
        final_assumptions: Dict[str, Any]
        comments: str (val comments & critique)
        history_text: str (full logs of the agent run)
    """
    from src.pipeline.modeler_orchestrator import Modeler

    m = Modeler()

    # 1. Discover available files and load directory structures
    extracted_dir = workspace / "4_extracted_data"
    analysis_dir = workspace / "5_historical_analysis"

    index_path = workspace / f"{ticker}_folder_index.md"
    files_catalog_str = ""
    if index_path.exists():
        try:
            files_catalog_str = index_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not read index file: {e}")

    if not files_catalog_str:
        available_files = []
        if extracted_dir.exists():
            for p in extracted_dir.glob("*.md"):
                available_files.append(f"4_extracted_data/{p.name}")
        if analysis_dir.exists():
            for p in analysis_dir.glob("*.md"):
                available_files.append(f"5_historical_analysis/{p.name}")
        files_catalog_str = "\n".join(f"- {f}" for f in sorted(available_files))

    # Generate initial draft model context
    dcf_result, projections, valuation_table_str = m.run_valuation_calculation(
        ticker, workspace, base_assumptions
    )

    draft_model_md = f"""### Draft Valuation Summary (Initial Recommendations)
{valuation_table_str}

### Draft Projections Table
| Year | Revenue ($M) | Growth (%) | EBITA Margin (%) | Invested Capital ($M) | Free Cash Flow ($M) | Discount Factor | Discounted FCF |
|---|---|---|---|---|---|---|---|
"""
    for p in projections:
        draft_model_md += (
            f"| Year {p['year']} | {p['revenue']:,.1f} | {p['growth']*100:.2f}% | "
            f"{p['margin']*100:.2f}% | {p['ic']:,.1f} | {p['fcf']:,.1f} | {p['df']:.4f} | {p['pv']:,.1f} |\n"
        )

    # Initialize final assumptions and critique defaults
    final_assumptions = dict(base_assumptions)
    comments = "No commentary provided by modeler agent."

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst assistant. Your goal is to review and finalize the DCF valuation model.\n"
        "You have access to recommended assumptions from specialized sub-agents (WACC, Growth, Margin, Non-Operating).\n"
        "You must review these assumptions, verify if the results make logical sense (e.g. sanity check currency, scale, share price, shares outstanding, double-count checks), and make adjustments if needed.\n"
        "Crucially, you must also provide a detailed critique/commentary on the final valuation model, the assumptions used, and the results.\n\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'pull_historical_analysis_file': arguments: {'file_name': str}\n"
        "  Retrieves contents of a file in 5_historical_analysis/ (e.g. analyst_views.md, financials_quarter.md).\n"
        "- 'pull_extracted_data_file': arguments: {'file_name': str}\n"
        "  Retrieves contents of an individual extracted report in 4_extracted_data/ (e.g. YYYYMMDD_document_type_extracted.md).\n"
        "- 'get_market_data': arguments: {}\n"
        "  Retrieves Yahoo Finance market profile details for the active ticker (restricting details to current 'share_price' and 'currency').\n"
        "- 'run_valuation': arguments: wacc, revenue_growth_rate, terminal_growth_rate, margin_yr5, terminal_margin, capital_turnover, adjusted_tax_rate, cash, short_term_investments, debt, preferred_equity, minority_interest, other_financial, shares_outstanding, base_revenue, base_ic, currency, fx_rate, adr_ratio, share_price (all optional)\n"
        "  Recalculates the DCF model projections, Enterprise Value, Net Debt, Equity Value, and Intrinsic Value. Returns a markdown summary of the results.\n"
        "- 'finalize': arguments: {'assumptions': dict, 'comments': str}\n"
        "  Conclude modeling, returning the final validated assumptions dictionary and your detailed comments/critique on the valuation modeling, assumptions, and results.\n\n"
        "Rules:\n"
        "1. Check if the valuation result makes logical sense: Is the intrinsic value extremely far from current market price? If so, check for common errors:\n"
        "   - **Currency mismatch**: E.g. yfinance is in USD but company reports in EUR/JPY. Ensure the currency conversion (fx_rate, adr_ratio) is set correctly.\n"
        "   - **Scale issues**: E.g. values are in Thousands instead of Millions.\n"
        "   - **Shares outstanding**: Diluted vs basic shares. Verify if shares outstanding is in the correct unit (e.g., Millions).\n"
        "2. If you find any obvious errors, update them by calling 'run_valuation' with revised inputs to test them.\n"
        "3. Provide a clear reasoning/thought process in the 'thought' field of each turn.\n"
        "4. Your final comments must include: your opinion of the final valuation results, how sensitive the model is to key assumptions (like WACC or terminal growth), and why adjustments (if any) were made relative to the other agents' defaults.\n"
        "5. Call 'finalize' on your last turn. You have up to 10 turns."
    )

    user_content = (
        f"Review and finalize the DCF valuation model for {ticker}. You have up to 10 turns.\n\n"
        f"**Initial Modeler Agent Recommendations:**\n"
        f"{json.dumps({k: v for k, v in base_assumptions.items() if not k.endswith('explanation') and not k == 'wacc_explanation'}, indent=2)}\n\n"
        f"**Initial WACC explanation:** {base_assumptions.get('wacc_explanation', 'N/A')}\n"
        f"**Initial Growth explanation:** {base_assumptions.get('growth_explanation', 'N/A')}\n"
        f"**Initial Margin explanation:** {base_assumptions.get('margin_explanation', 'N/A')}\n"
        f"**Initial Non-Operating explanation:** {base_assumptions.get('non_operating_explanation', 'N/A')}\n\n"
        f"**Available Files Catalog in Workspace:**\n"
        f"{files_catalog_str}\n\n"
        f"--- STARTING DCF MODEL DRAFT ---\n"
        f"{draft_model_md}\n"
    )

    if learning_context:
        user_content += f'\n\nHere is the active company modeling learning context to guide your decisions:\n"""\n{learning_context}\n"""'

    history = [
        {
            "role": "user",
            "content": user_content,
        }
    ]

    for turn in range(10):
        if turn == 9:
            history[-1]["content"] += (
                "\n\nCRITICAL: This is your final turn (turn 10 of 10). You must call the 'finalize' tool immediately with your finalized inputs and detailed valuation critique/comments."
            )

        prompt_str = ""
        for h in history:
            prompt_str += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        try:
            resp = llm.generate(prompt_str, system_prompt=sys_prompt).strip()
        except Exception as e:
            logger.error(f"DCF Modeling Agent failed at turn {turn}: {e}")
            raise LLMError(
                f"DCF Modeling Agent failed during LLM generation at turn {turn}: {e}"
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
            final_assumptions = args.get("assumptions", final_assumptions)
            comments = str(args.get("comments", comments))
            break

        elif tool == "pull_historical_analysis_file":
            file_name = args.get("file_name", "")
            res = pull_markdown_file(workspace, file_name)
            history.append(
                {
                    "role": "user",
                    "content": f"Observation from pull_historical_analysis_file:\n{res[:8000]}",
                }
            )

        elif tool == "pull_extracted_data_file":
            file_name = args.get("file_name", "")
            res = pull_markdown_file(workspace, file_name)
            history.append(
                {
                    "role": "user",
                    "content": f"Observation from pull_extracted_data_file:\n{res[:8000]}",
                }
            )

        elif tool == "get_market_data":
            from src.services.market_data import get_market_profile

            try:
                prof = get_market_profile(ticker)
                m_data = {
                    "share_price": prof.get("share_price"),
                    "currency": prof.get("currency"),
                }
                history.append(
                    {
                        "role": "user",
                        "content": f"Observation from get_market_data:\n{json.dumps(m_data, indent=2)}",
                    }
                )
            except Exception as e:
                history.append(
                    {
                        "role": "user",
                        "content": f"Error fetching market data: {e}",
                    }
                )

        elif tool == "run_valuation":
            # Override current final_assumptions dynamically
            test_assumptions = dict(final_assumptions)
            for k in [
                "wacc",
                "revenue_growth_rate",
                "terminal_growth_rate",
                "margin_yr5",
                "terminal_margin",
                "capital_turnover",
                "adjusted_tax_rate",
                "cash",
                "short_term_investments",
                "debt",
                "preferred_equity",
                "minority_interest",
                "other_financial",
                "shares_outstanding",
                "base_revenue",
                "base_ic",
                "currency",
                "fx_rate",
                "adr_ratio",
                "share_price",
            ]:
                if k in args and args[k] is not None:
                    test_assumptions[k] = args[k]

            try:
                d_res, proj, val_tab = m.run_valuation_calculation(
                    ticker, workspace, test_assumptions
                )
                # Store test assumptions as final_assumptions so they persist
                final_assumptions = test_assumptions

                calc_summary_md = f"### Recalculated Valuation Results\n{val_tab}\n\n### Projections Summary\n"
                for p in proj:
                    calc_summary_md += (
                        f"| Year {p['year']} | Rev: ${p['revenue']:,.1f}M | Margin: {p['margin']*100:.1f}% | "
                        f"FCF: ${p['fcf']:,.1f}M | PV: ${p['pv']:,.1f}M |\n"
                    )

                history.append(
                    {
                        "role": "user",
                        "content": f"Observation from run_valuation:\n{calc_summary_md}",
                    }
                )
            except Exception as e:
                history.append(
                    {
                        "role": "user",
                        "content": f"Error running valuation calculations: {e}",
                    }
                )

        else:
            history.append({"role": "user", "content": f"Error: Unknown tool '{tool}'"})
    else:
        raise LLMError(
            "DCF Modeling Agent failed to finalize modeling assumptions within the maximum turn limit."
        )

    # Reconstruct history text for Curator Agent logs
    history_text = ""
    for h in history:
        history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

    return final_assumptions, comments, history_text
