import logging
from typing import Dict, Any, Optional

from src.services.llm_client import LLMClient
from src.core.exceptions import LLMError
from src.agents.agent_executor import run_agent_loop
from src.core.blackboard import WorkspaceContext, CompanyMetadata

logger = logging.getLogger(__name__)


def run_margin_agent(
    client: LLMClient,
    company_metadata: CompanyMetadata,
    workspace_state: WorkspaceContext,
    period_key: str,
    learnings: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Stateless agent that determines future EBITA margin assumptions for a company.
    Returns a dictionary of results.
    Enforces a 10-turn limit and tool restrictions.
    """
    # 1. Pre-flight dependency check
    if period_key not in workspace_state.reports:
        return {
            "status": "failed",
            "error": f"Missing dependency: Period '{period_key}' not initialized on the blackboard.",
        }

    # Retrieve defaults from blackboard if available
    q_fin = workspace_state.company_data.quarterly_financials
    latest_q = q_fin[-1] if q_fin else None

    default_base_margin = (
        (latest_q.ebita / latest_q.revenue)
        if (latest_q and latest_q.revenue and latest_q.ebita)
        else 0.15
    )
    default_yr5_margin = default_base_margin
    default_terminal_margin = default_base_margin

    # Default results in case of failure or empty response
    final_margin_results = {
        "base_margin": default_base_margin,
        "margin_yr5": default_yr5_margin,
        "terminal_margin": default_terminal_margin,
        "explanation": "Default backup EBITA margins calculated without agent details.",
    }

    # Define tools as inner functions closed over state
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

    def web_search(query: str) -> str:
        """Search DuckDuckGo with the given query and return summaries of results."""
        from src.services.ddg_search import ddg_search

        results = ddg_search(query, max_results=3)
        if results:
            snippets = []
            for res in results:
                snippets.append(f"{res.get('title')}: {res.get('body')}")
            return "\n".join(snippets)
        return "No search results found."

    def finalize(
        base_margin: float,
        margin_yr5: float,
        terminal_margin: float,
        explanation: str,
    ) -> str:
        """Conclude margin estimation, specifying base, year 5, and terminal EBITA margins."""
        final_margin_results["base_margin"] = base_margin
        final_margin_results["margin_yr5"] = margin_yr5
        final_margin_results["terminal_margin"] = terminal_margin
        final_margin_results["explanation"] = explanation
        return "Margin assumptions finalized."

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the Margin Agent. Your goal is to determine three future EBITA margins for a valuation model with a detailed rationale:\n"
        "1. base_margin: Near-term / base starting EBITA margin (often based on historical EBITA run-rate or recent quarters).\n"
        "2. margin_yr5: Mid-term Year 5 target EBITA margin (where operating margins mature to by year 5).\n"
        "3. terminal_margin: Long-term / Terminal EBITA margin (stable margin beyond year 10, typically stable depending on market share and moat).\n\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'query_blackboard': arguments: {'section': str, 'period': str}\n"
        "  Queries the active blackboard state.\n"
        "- 'web_search': arguments: {'query': str}\n"
        "  Search the web for news, transcripts, or competitor EBITA margins.\n"
        "- 'finalize': arguments: {'base_margin': float, 'margin_yr5': float, 'terminal_margin': float, 'explanation': str}\n"
        "  Conclude margin estimation and present the final parameters.\n\n"
        "Rules:\n"
        "1. Identify historical EBITA margins, cost structures, operating leverage, qualitative margin outlooks, news trends, and conference call transcripts details on the blackboard or via web_search.\n"
        "2. Think step-by-step about what the right three EBITA margins should be and construct a strong rationale.\n"
        "3. Call 'finalize' on your last turn. The explanation must describe the trends or source details extracted and your reasoning."
    )

    user_content = (
        f"Estimate the EBITA margin assumptions for {company_metadata.company_name or company_metadata.ticker}. You have up to 10 turns.\n\n"
        f"**Initial Context Details:**\n"
        f"- Ticker: {company_metadata.ticker}\n"
        f"- Target Period: {period_key}\n"
        f"- Default Base Margin: {default_base_margin * 100:.2f}%\n"
        f"- Default Year 5 Margin: {default_yr5_margin * 100:.2f}%\n"
        f"- Default Terminal Margin: {default_terminal_margin * 100:.2f}%\n"
    )
    if learnings:
        user_content += f'\n\nHere is the active company modeling learning context to guide your decisions:\n"""\n{learnings}\n"""'

    tools = [query_blackboard, web_search, finalize]

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
            f"Margin Agent failed to finalize EBITA margin assumptions within the maximum turn limit: {e}"
        )
    except Exception as e:
        raise LLMError(f"Margin Agent failed during LLM generation: {e}")

    # Trigger Curator Agent to capture lessons in model_learning.md
    try:
        from src.agents.curator_agent import CuratorAgent

        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(client.settings)
        curator.curate_model_agent(company_metadata.ticker, "Margin", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for Margin agent: {e}")

    return final_margin_results
