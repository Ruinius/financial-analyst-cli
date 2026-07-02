import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from src.services.llm_client import LLMClient
from src.core.exceptions import LLMError
from src.agents.agent_executor import run_agent_loop
from src.core.blackboard import WorkspaceContext, CompanyMetadata

logger = logging.getLogger(__name__)


def run_dcf_modeling_agent(
    client: LLMClient,
    company_metadata: CompanyMetadata,
    workspace_state: WorkspaceContext,
    period_key: str,
    base_assumptions: Dict[str, Any],
    learnings: Optional[str] = None,
) -> Tuple[Dict[str, Any], str, str]:
    """
    Stateless agent that reviews and finalizes the DCF valuation model.
    Returns:
        final_assumptions: Dict[str, Any]
        comments: str
        history_text: str
    Enforces a 10-turn limit and tool restrictions.
    """
    # 1. Pre-flight dependency check
    if period_key not in workspace_state.reports:
        return (
            base_assumptions,
            "Error: Period key not found on the blackboard.",
            "No history.",
        )

    from src.agents.orchestrator_pipelines.model import Modeler

    m = Modeler()

    # Determine workspace directory
    settings = client.settings
    workspace = Path(settings.base_workspace_dir) / company_metadata.ticker

    # Generate initial draft model context
    dcf_result, projections, valuation_table_str = m.run_valuation_calculation(
        company_metadata.ticker, workspace, base_assumptions
    )

    draft_model_md = f"### Draft Valuation Summary (Initial Recommendations)\n{valuation_table_str}\n\n### Draft Projections Table\n"
    for p in projections:
        draft_model_md += (
            f"| Year {p['year']} | {p['revenue']:,.1f} | {p['growth'] * 100:.2f}% | "
            f"{p['margin'] * 100:.2f}% | {p['ic']:,.1f} | {p['fcf']:,.1f} | {p['df']:.4f} | {p['pv']:,.1f} |\n"
        )

    # Initialize final assumptions and critique defaults
    final_assumptions = dict(base_assumptions)
    comments = "No commentary provided by modeler agent."

    def query_blackboard(section: str, period: Optional[str] = None) -> str:
        """
        Query the active blackboard state in a read-only manner.
        Arguments:
          section: The section of the blackboard to query. Options: 'metadata', 'company_data', 'financial_data', 'other_data', 'reports'.
          period: Optional specific period (e.g., '2024_Q3') if querying 'financial_data' or 'other_data'. If not specified, defaults to the current active period.
        """
        from src.tools.query_blackboard import query_blackboard_helper

        return query_blackboard_helper(
            workspace_state=workspace_state,
            company_metadata=company_metadata,
            period_key=period_key,
            section=section,
            period=period,
        )

    def run_valuation(**kwargs) -> str:
        """
        Recalculates the DCF model projections, Enterprise Value, Net Debt, Equity Value, and Intrinsic Value.
        Returns a markdown summary of the results.
        All arguments are optional and will override the base assumptions.
        """
        test_assumptions = dict(final_assumptions)
        for k, v in kwargs.items():
            if v is not None:
                test_assumptions[k] = v

        try:
            d_res, proj, val_tab = m.run_valuation_calculation(
                company_metadata.ticker, workspace, test_assumptions
            )
            # Store test assumptions as final_assumptions so they persist
            for k, v in test_assumptions.items():
                final_assumptions[k] = v

            # ⚡ Bolt Optimization: Use list append and join instead of string concatenation inside loop
            calc_summary_parts = [f"### Recalculated Valuation Results\n{val_tab}\n\n### Projections Summary\n"]
            for p in proj:
                calc_summary_parts.append(
                    f"| Year {p['year']} | Rev: ${p['revenue']:,.1f}M | Margin: {p['margin'] * 100:.1f}% | "
                    f"FCF: ${p['fcf']:,.1f}M | PV: ${p['pv']:,.1f}M |\n"
                )
            return "".join(calc_summary_parts)
        except Exception as e:
            return f"Error running valuation calculations: {e}"

    def finalize(assumptions: dict, comments_arg: str) -> str:
        """Conclude modeling, returning the final validated assumptions dictionary and comments."""
        nonlocal final_assumptions, comments
        for k, v in assumptions.items():
            final_assumptions[k] = v
        comments = comments_arg
        return "DCF modeling finalized."

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the DCF Modeling Agent. Your goal is to review and finalize the DCF valuation model.\n"
        "You have access to recommended assumptions from specialized sub-agents (WACC, Growth, Margin, Non-Operating).\n"
        "You must review these assumptions, verify if the results make logical sense (e.g. sanity check currency, scale, share price, shares outstanding, double-count checks), and make adjustments if needed.\n"
        "Crucially, you must also provide a detailed critique/commentary on the final valuation model, the assumptions used, and the results.\n\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'query_blackboard': arguments: {'section': str, 'period': str}\n"
        "  Queries the active blackboard state.\n"
        "- 'run_valuation': arguments: wacc, revenue_growth_rate, terminal_growth_rate, margin_yr5, terminal_margin, capital_turnover, adjusted_tax_rate, cash, short_term_investments, debt, preferred_equity, minority_interest, other_financial, shares_outstanding, base_revenue, base_ic, currency, fx_rate, adr_ratio, share_price (all optional)\n"
        "  Recalculates the DCF model projections, Enterprise Value, Net Debt, Equity Value, and Intrinsic Value. Returns a markdown summary of the results.\n"
        "- 'finalize': arguments: {'assumptions': dict, 'comments_arg': str}\n"
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
        f"Review and finalize the DCF valuation model for {company_metadata.company_name or company_metadata.ticker}. You have up to 10 turns.\n\n"
        f"**Initial Modeler Agent Recommendations:**\n"
        f"{json.dumps({k: v for k, v in base_assumptions.items() if not k.endswith('explanation')}, indent=2)}\n\n"
        f"**Initial WACC explanation:** {base_assumptions.get('wacc_explanation', 'N/A')}\n"
        f"**Initial Growth explanation:** {base_assumptions.get('growth_explanation', 'N/A')}\n"
        f"**Initial Margin explanation:** {base_assumptions.get('margin_explanation', 'N/A')}\n"
        f"**Initial Non-Operating explanation:** {base_assumptions.get('non_operating_explanation', 'N/A')}\n\n"
        f"--- STARTING DCF MODEL DRAFT ---\n"
        f"{draft_model_md}\n"
    )

    if learnings:
        user_content += f'\n\nHere is the active company modeling learning context to guide your decisions:\n"""\n{learnings}\n"""'

    tools = [query_blackboard, run_valuation, finalize]

    try:
        finalized_args, history = run_agent_loop(
            client=client,
            system_prompt=sys_prompt,
            initial_prompt=user_content,
            tools=tools,
            max_turns=10,
        )
    except LLMError as e:
        raise LLMError(
            f"DCF Modeling Agent failed to finalize DCF calculations within the maximum turn limit: {e}"
        )
    except Exception as e:
        raise LLMError(f"DCF Modeling Agent failed during LLM generation: {e}")

    # Reconstruct history text for Curator Agent logs
    # ⚡ Bolt Optimization: Use list append and join instead of string concatenation inside loop
    history_parts = []
    for h in history:
        history_parts.append(f"\n\n--- {h['role'].upper()} ---\n{h['content']}")
    history_text = "".join(history_parts)

    if finalized_args:
        final_assumptions = finalized_args.get("assumptions", final_assumptions)
        comments = str(finalized_args.get("comments_arg", comments))

    return final_assumptions, comments, history_text
