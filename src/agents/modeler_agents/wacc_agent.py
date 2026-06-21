import json
import logging
from typing import Dict, Any, Optional

from src.services.llm_client import LLMClient
from src.core.exceptions import LLMError
from src.agents.agent_executor import run_agent_loop
from src.core.blackboard import WorkspaceContext, CompanyMetadata

logger = logging.getLogger(__name__)


def calculate_wacc_formula(
    risk_free_rate: float,
    equity_risk_premium: float,
    beta: float,
    share_price: float,
    shares_outstanding: float,
    total_debt: float,
    cash_and_equivalents: float,
    interest_expense: float,
    pretax_cost_of_debt: float,
    tax_rate: float,
    target_debt_to_equity: float = None,
    market_cap: float = 0.0,
) -> Dict[str, Any]:
    """
    Perform the de-levering/re-levering beta and WACC calculation.
    All dollar/currency values (total_debt, cash_and_equivalents, market_cap, interest_expense)
    should be in millions to ensure consistent scaling.
    """
    # 1. Calculate Equity Value (Market Cap in millions)
    if market_cap > 1000000:
        market_cap_m = market_cap / 1000000.0
    elif market_cap > 0:
        market_cap_m = market_cap
    else:
        market_cap_m = share_price * shares_outstanding

    # 2. Delever Beta
    # Formula: Beta_unlevered = Beta_levered / (1 + (1 - Tax_Rate) * (Debt / Equity))
    # If Equity is 0, default to levered beta as unlevered beta.
    de_ratio = total_debt / market_cap_m if market_cap_m > 0 else 0.0
    beta_unlevered = (
        beta / (1 + (1 - tax_rate) * de_ratio) if market_cap_m > 0 else beta
    )

    # 3. Relever Beta
    # Formula: Beta_relevered = Beta_unlevered * (1 + (1 - Tax_Rate) * (Target_D_E_Ratio))
    if target_debt_to_equity is not None:
        beta_relevered = beta_unlevered * (1 + (1 - tax_rate) * target_debt_to_equity)
        chosen_de_ratio = target_debt_to_equity
    else:
        beta_relevered = beta_unlevered * (1 + (1 - tax_rate) * de_ratio)
        chosen_de_ratio = de_ratio

    # 4. Cost of Equity (CAPM)
    # Formula: Re = Rf + Beta_relevered * ERP
    cost_of_equity = risk_free_rate + (beta_relevered * equity_risk_premium)

    # 5. Pre-tax Cost of Debt
    if pretax_cost_of_debt > 0:
        cost_of_debt_pretax = pretax_cost_of_debt
    elif total_debt > 0 and interest_expense > 0:
        cost_of_debt_pretax = interest_expense / total_debt
    else:
        cost_of_debt_pretax = (
            risk_free_rate + 0.02
        )  # Fallback: Rf + 2.0% corporate spread

    # Ensure pre-tax cost of debt is reasonable
    if cost_of_debt_pretax < 0:
        cost_of_debt_pretax = risk_free_rate + 0.02

    cost_of_debt_aftertax = cost_of_debt_pretax * (1 - tax_rate)

    # 6. Capital Weights
    total_capital = market_cap_m + total_debt
    if total_capital > 0:
        weight_equity = market_cap_m / total_capital
        weight_debt = total_debt / total_capital
    else:
        weight_equity = 1.0
        weight_debt = 0.0

    # 7. WACC
    # Formula: WACC = (Weight_Equity * Re) + (Weight_Debt * Rd_aftertax)
    wacc_raw = (weight_equity * cost_of_equity) + (weight_debt * cost_of_debt_aftertax)

    # Cap WACC between 6% and 11% as per orchestrator rules
    wacc_final = max(0.06, min(0.11, wacc_raw))

    # 8. Generate Detailed Explanation
    explanation = (
        f"### WACC Calculation & Beta Delevering Audit Trail\n\n"
        f"**1. Input Parameters:**\n"
        f"- Market Cap (Equity): ${market_cap_m:,.2f}M (Share Price: ${share_price:.2f}, Shares Outstanding: {shares_outstanding:,.2f}M)\n"
        f"- Total Debt: ${total_debt:,.2f}M\n"
        f"- Cash & Equivalents: ${cash_and_equivalents:,.2f}M\n"
        f"- Net Debt: ${total_debt - cash_and_equivalents:,.2f}M\n"
        f"- Raw Levered Beta: {beta:.4f}\n"
        f"- Tax Rate: {tax_rate * 100:.2f}%\n"
        f"- Risk-Free Rate: {risk_free_rate * 100:.2f}%\n"
        f"- Equity Risk Premium (ERP): {equity_risk_premium * 100:.2f}%\n\n"
        f"**2. Beta Delevering & Relevering:**\n"
        f"- Debt / Equity Ratio (D/E): {de_ratio:.4f}\n"
        f"- **Unlevered Beta (Asset Beta)** = Beta_levered / [1 + (1 - T) * (D/E)] = {beta:.4f} / [1 + (1 - {tax_rate:.4f}) * {de_ratio:.4f}] = **{beta_unlevered:.4f}**\n"
        f"- **Relevered Beta** = Unlevered_Beta * [1 + (1 - T) * (Chosen_D/E)] = **{beta_relevered:.4f}** (using D/E = {chosen_de_ratio:.4f})\n\n"
        f"**3. Cost of Capital Components:**\n"
        f"- **Cost of Equity (Re)** = Rf + (Beta_relevered * ERP) = {risk_free_rate * 100:.2f}% + ({beta_relevered:.4f} * {equity_risk_premium * 100:.2f}%) = **{cost_of_equity * 100:.2f}%**\n"
        f"- **Pre-tax Cost of Debt (Rd)** = {cost_of_debt_pretax * 100:.2f}% "
        f"{'(calculated from Interest Expense / Total Debt)' if pretax_cost_of_debt <= 0 and total_debt > 0 and interest_expense > 0 else '(using provided/fallback rate)'}\n"
        f"- **After-tax Cost of Debt** = Rd * (1 - T) = {cost_of_debt_aftertax * 100:.2f}%\n\n"
        f"**4. Weighted Average Cost of Capital (WACC):**\n"
        f"- Weight of Equity (E / V) = {weight_equity * 100:.2f}%\n"
        f"- Weight of Debt (D / V) = {weight_debt * 100:.2f}%\n"
        f"- **WACC (Raw)** = (Weight_Equity * Re) + (Weight_Debt * Rd_aftertax) = **{wacc_raw * 100:.2f}%**\n"
        f"- **WACC (Final capped)** = **{wacc_final * 100:.2f}%** (capped between 6.00% and 11.00%)\n"
    )

    return {
        "unlevered_beta": beta_unlevered,
        "levered_beta": beta_relevered,
        "cost_equity": cost_of_equity,
        "cost_debt_pretax": cost_of_debt_pretax,
        "cost_debt_aftertax": cost_of_debt_aftertax,
        "weight_equity": weight_equity,
        "weight_debt": weight_debt,
        "wacc_raw": wacc_raw,
        "wacc_final": wacc_final,
        "market_cap_m": market_cap_m,
        "explanation": explanation,
    }


def run_wacc_agent(
    client: LLMClient,
    company_metadata: CompanyMetadata,
    workspace_state: WorkspaceContext,
    period_key: str,
    learnings: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Stateless agent that determines the Weighted Average Cost of Capital (WACC)
    and net debt for a company. Returns a dictionary of results.
    Enforces a 10-turn limit and tool restrictions.
    """
    # 1. Pre-flight dependency check
    if period_key not in workspace_state.reports:
        return {
            "status": "failed",
            "error": f"Missing dependency: Period '{period_key}' not initialized on the blackboard.",
        }

    report = workspace_state.reports[period_key]
    if (
        report.balance_sheet_status != "completed"
        or report.income_statement_status != "completed"
    ):
        return {
            "status": "failed",
            "error": f"Missing dependency: Balance sheet or Income statement not completed for period '{period_key}'.",
        }

    tax_rate = report.financial_data.adjusted_tax_rate or 0.21

    # Default results in case of failure or empty response
    final_wacc_results = {
        "wacc": 0.08,
        "net_debt": 0.0,
        "unlevered_beta": 1.0,
        "levered_beta": 1.0,
        "cost_equity": 0.042 + 1.0 * 0.05,
        "cost_debt_pretax": 0.062,
        "cost_debt_aftertax": 0.062 * (1 - tax_rate),
        "weight_equity": 1.0,
        "weight_debt": 0.0,
        "explanation": "Default backup WACC calculated without agent details.",
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

    def get_market_data() -> str:
        """Fetch current share price, market cap, and beta for the active ticker from Yahoo Finance."""
        from src.services.market_data import get_market_profile

        try:
            profile = get_market_profile(company_metadata.ticker)
            return json.dumps(
                {
                    "share_price": profile.get("share_price", 0.0),
                    "market_cap": profile.get("market_cap", 0.0),
                    "beta": profile.get("beta", 1.0),
                }
            )
        except Exception as e:
            return f"Error fetching market data: {e}"

    def calculate_wacc(
        risk_free_rate: float,
        equity_risk_premium: float,
        beta: float,
        share_price: float,
        shares_outstanding: float,
        total_debt: float,
        cash_and_equivalents: float,
        interest_expense: float,
        pretax_cost_of_debt: float,
        tax_rate: float,
        target_debt_to_equity: Optional[float] = None,
        market_cap: float = 0.0,
    ) -> str:
        """
        Run the WACC formula (supporting beta de-levering/re-levering).
        All dollar/currency values should be in millions.
        """
        calc_res = calculate_wacc_formula(
            risk_free_rate=risk_free_rate,
            equity_risk_premium=equity_risk_premium,
            beta=beta,
            share_price=share_price,
            shares_outstanding=shares_outstanding,
            total_debt=total_debt,
            cash_and_equivalents=cash_and_equivalents,
            interest_expense=interest_expense,
            pretax_cost_of_debt=pretax_cost_of_debt,
            tax_rate=tax_rate,
            target_debt_to_equity=target_debt_to_equity,
            market_cap=market_cap,
        )
        # Store calculation results in case agent finalizes using them
        final_wacc_results["wacc"] = calc_res["wacc_final"]
        final_wacc_results["net_debt"] = total_debt - cash_and_equivalents
        final_wacc_results["unlevered_beta"] = calc_res["unlevered_beta"]
        final_wacc_results["levered_beta"] = calc_res["levered_beta"]
        final_wacc_results["cost_equity"] = calc_res["cost_equity"]
        final_wacc_results["cost_debt_pretax"] = calc_res["cost_debt_pretax"]
        final_wacc_results["cost_debt_aftertax"] = calc_res["cost_debt_aftertax"]
        final_wacc_results["weight_equity"] = calc_res["weight_equity"]
        final_wacc_results["weight_debt"] = calc_res["weight_debt"]
        final_wacc_results["explanation"] = calc_res["explanation"]
        return json.dumps({k: v for k, v in calc_res.items() if k != "explanation"})

    def finalize(
        wacc: float,
        total_debt: float,
        cash_and_equivalents: float,
        pretax_cost_of_debt: float,
        cost_of_equity: float,
        unlevered_beta: float,
        explanation: str,
    ) -> str:
        """Finalize the WACC calculation."""
        final_wacc_results["wacc"] = wacc
        final_wacc_results["net_debt"] = total_debt - cash_and_equivalents
        final_wacc_results["unlevered_beta"] = unlevered_beta
        final_wacc_results["cost_equity"] = cost_of_equity
        final_wacc_results["cost_debt_pretax"] = pretax_cost_of_debt
        final_wacc_results["cost_debt_aftertax"] = pretax_cost_of_debt * (1 - tax_rate)
        final_wacc_results["explanation"] = explanation
        return "WACC calculation finalized."

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the WACC Agent. Your goal is to determine the Weighted Average Cost of Capital (WACC) and net debt for a company.\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'query_blackboard': arguments: {'section': str, 'period': str}\n"
        "  Queries the active blackboard state.\n"
        "- 'get_market_data': arguments: {}\n"
        "  Fetches current share price, market cap, and beta for the active ticker from Yahoo Finance.\n"
        "- 'calculate_wacc': arguments: {'risk_free_rate': float, 'equity_risk_premium': float, 'beta': float, 'share_price': float, 'shares_outstanding': float, 'total_debt': float, 'cash_and_equivalents': float, 'interest_expense': float, 'pretax_cost_of_debt': float, 'tax_rate': float, 'target_debt_to_equity': float, 'market_cap': float}\n"
        "  Run the WACC formula (supporting beta de-levering/re-levering). Use 0.0 for target_debt_to_equity or omit if not applicable. Pass values in millions.\n"
        "- 'finalize': arguments: {'wacc': float, 'total_debt': float, 'cash_and_equivalents': float, 'pretax_cost_of_debt': float, 'cost_of_equity': float, 'unlevered_beta': float, 'explanation': str}\n"
        "  Finalize the execution and present the final parameters.\n\n"
        "Rules:\n"
        "1. Identify the latest Balance Sheet and Income Statement data on the blackboard (using query_blackboard with section='financial_data' and period='[period]') to extract: Total Debt (Short-term debt + Long-term debt), Cash & equivalents, Interest Expense, and Tax Rate.\n"
        "2. Call 'get_market_data' to retrieve the current share price, market cap, and beta.\n"
        "3. Call 'calculate_wacc' with your extracted values. (Note: risk_free_rate defaults to 0.042 and equity_risk_premium to 0.05 if not specified. Tax rate defaults to the historical tax rate provided).\n"
        "4. Provide a clear reasoning/thought process in the 'thought' field of each turn.\n"
        "5. Call 'finalize' on your last turn. The explanation must describe the line items extracted and where they came from."
    )

    user_content = (
        f"Estimate the WACC for {company_metadata.company_name or company_metadata.ticker}. You have up to 10 turns.\n\n"
        f"**Initial Context Details:**\n"
        f"- Ticker: {company_metadata.ticker}\n"
        f"- Target Period: {period_key}\n"
        f"- Baseline Tax Rate: {tax_rate * 100:.2f}%\n"
    )
    if learnings:
        user_content += f'\n\nHere is the active company modeling learning context to guide your decisions:\n"""\n{learnings}\n"""'

    tools = [query_blackboard, get_market_data, calculate_wacc, finalize]

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
            f"WACC Agent failed to finalize WACC calculations within the maximum turn limit: {e}"
        )
    except Exception as e:
        raise LLMError(f"WACC Agent failed during LLM generation: {e}")

    # Trigger Curator Agent to capture lessons in model_learning.md
    try:
        from src.agents.curator_agent import CuratorAgent

        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(client.settings)
        curator.curate_model_agent(company_metadata.ticker, "WACC", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for WACC agent: {e}")

    return final_wacc_results
