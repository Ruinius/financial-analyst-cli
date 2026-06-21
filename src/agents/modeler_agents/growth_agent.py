import logging
from typing import Dict, Any, Optional

from src.services.llm_client import LLMClient
from src.core.exceptions import LLMError
from src.agents.agent_executor import run_agent_loop
from src.core.blackboard import WorkspaceContext, CompanyMetadata

logger = logging.getLogger(__name__)


def run_growth_agent(
    client: LLMClient,
    company_metadata: CompanyMetadata,
    workspace_state: WorkspaceContext,
    period_key: str,
    learnings: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Stateless agent that determines future revenue growth rate assumptions for a company.
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

    default_base_growth = (
        latest_q.organic_growth / 100.0
        if (latest_q and latest_q.organic_growth)
        else 0.05
    )
    default_yr5_growth = default_base_growth
    default_terminal_growth = 0.03

    # Default results in case of failure or empty response
    final_growth_results = {
        "base_growth_rate": default_base_growth,
        "revenue_growth_rate": default_yr5_growth,
        "terminal_growth_rate": default_terminal_growth,
        "explanation": "Default backup growth rates calculated without agent details.",
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
        base_growth_rate: float,
        revenue_growth_rate: float,
        terminal_growth_rate: float,
        explanation: str,
    ) -> str:
        """Conclude growth rate estimation, specifying base, year 5, and terminal growth rates."""
        final_growth_results["base_growth_rate"] = base_growth_rate
        final_growth_results["revenue_growth_rate"] = revenue_growth_rate
        final_growth_results["terminal_growth_rate"] = terminal_growth_rate
        final_growth_results["explanation"] = explanation
        return "Growth rate assumptions finalized."

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the Growth Agent. Your goal is to determine three future revenue growth rates for a valuation model with a detailed rationale:\n"
        "1. base_growth_rate: Near-term / base starting growth rate (often based on historical run-rate or recent quarters).\n"
        "2. revenue_growth_rate: Mid-term Year 5 target growth rate (where simple/organic revenue growth matures to after year 5).\n"
        "3. terminal_growth_rate: Long-term / Terminal growth rate (stable growth rate beyond year 10, typically 2-4% depending on moat).\n\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'query_blackboard': arguments: {'section': str, 'period': str}\n"
        "  Queries the active blackboard state.\n"
        "- 'web_search': arguments: {'query': str}\n"
        "  Search the web for news, transcripts, or competitor growth rates.\n"
        "- 'finalize': arguments: {'base_growth_rate': float, 'revenue_growth_rate': float, 'terminal_growth_rate': float, 'explanation': str}\n"
        "  Conclude growth rate estimation and present the final parameters.\n\n"
        "Rules:\n"
        "1. Identify historical revenue growth rates, moat characteristics, qualitative analyst sentiment, news trends, and transcripts details on the blackboard or via web_search.\n"
        "2. Think step-by-step about what the right three growth rates should be and construct a strong rationale.\n"
        "3. Call 'finalize' on your last turn. The explanation must describe the trends or source details extracted and your reasoning."
    )

    user_content = (
        f"Estimate the growth rate assumptions for {company_metadata.company_name or company_metadata.ticker}. You have up to 10 turns.\n\n"
        f"**Initial Context Details:**\n"
        f"- Ticker: {company_metadata.ticker}\n"
        f"- Target Period: {period_key}\n"
        f"- Default Base Growth Rate: {default_base_growth * 100:.2f}%\n"
        f"- Default Year 5 Growth Rate: {default_yr5_growth * 100:.2f}%\n"
        f"- Default Terminal Growth Rate: {default_terminal_growth * 100:.2f}%\n"
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
            f"Growth Agent failed to finalize growth rate assumptions within the maximum turn limit: {e}"
        )
    except Exception as e:
        raise LLMError(f"Growth Agent failed during LLM generation: {e}")

    # Trigger Curator Agent to capture lessons in model_learning.md
    try:
        from src.agents.curator_agent import CuratorAgent

        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(client.settings)
        curator.curate_model_agent(company_metadata.ticker, "Growth", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for Growth agent: {e}")

    return final_growth_results
