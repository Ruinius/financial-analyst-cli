import re
import json
import logging
from pathlib import Path
from typing import Dict, Any

from src.services.llm_client import LLMClient

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

    # Cap WACC between 6% and 15% as per orchestrator rules
    wacc_final = max(0.06, min(0.15, wacc_raw))

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
        f"- **WACC (Final capped)** = **{wacc_final * 100:.2f}%** (capped between 6.00% and 15.00%)\n"
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


def pull_markdown_file(workspace: Path, file_name: str) -> str:
    """Safe lookup of markdown files within workspace directories."""
    clean_name = Path(file_name).name

    # 1. Check in 4_extracted_data
    p1 = workspace / "4_extracted_data" / clean_name
    if p1.exists():
        return p1.read_text(encoding="utf-8")

    # 2. Check in 5_historical_analysis
    p2 = workspace / "5_historical_analysis" / clean_name
    if p2.exists():
        return p2.read_text(encoding="utf-8")

    # 3. Check in workspace root
    p3 = workspace / clean_name
    if p3.exists():
        return p3.read_text(encoding="utf-8")

    return f"Error: File '{file_name}' not found in workspace."


def run_wacc_agent(
    ticker: str,
    workspace: Path,
    share_price: float,
    market_cap: float,
    beta: float,
    tax_rate: float,
    llm: LLMClient,
    learning_context: str = "",
) -> Dict[str, Any]:
    """
    Run the agentic WACC calculation workflow.
    Executes up to 4 turns, enabling Sir Pennyworth to pull financial markdowns,
    extract parameters, run a WACC calculation tool, and finalize results.
    """
    # 1. Discover available files in 4_extracted_data and 5_historical_analysis
    extracted_dir = workspace / "4_extracted_data"
    analysis_dir = workspace / "5_historical_analysis"

    available_files = []
    if extracted_dir.exists():
        for p in extracted_dir.glob("*.md"):
            available_files.append(p.name)
    if analysis_dir.exists():
        for p in analysis_dir.glob("*.md"):
            available_files.append(p.name)

    files_catalog_str = "\n".join(f"- {f}" for f in sorted(available_files))

    # Default results in case of failure or empty response
    final_wacc_results = {
        "wacc": 0.08,
        "net_debt": 0.0,
        "unlevered_beta": beta,
        "levered_beta": beta,
        "cost_equity": 0.042 + beta * 0.05,
        "cost_debt_pretax": 0.062,
        "cost_debt_aftertax": 0.062 * (1 - tax_rate),
        "weight_equity": 1.0,
        "weight_debt": 0.0,
        "explanation": "Default backup WACC calculated without agent details.",
    }

    # System prompt outlining roles, tools, and expectations
    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. Your goal is to determine the Weighted Average Cost of Capital (WACC) and net debt for a company.\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'pull_markdown_file': arguments: {'file_name': str}\n"
        "  Retrieves contents of a file. Use this to pull latest balance sheet, income statement, or extracted files to find debt, cash, and interest metrics.\n"
        "- 'calculate_wacc': arguments: {'risk_free_rate': float, 'equity_risk_premium': float, 'beta': float, 'share_price': float, 'shares_outstanding': float, 'total_debt': float, 'cash_and_equivalents': float, 'interest_expense': float, 'pretax_cost_of_debt': float, 'tax_rate': float, 'target_debt_to_equity': float, 'market_cap': float}\n"
        "  Run the WACC formula (supporting beta de-levering/re-levering). Use 0.0 for target_debt_to_equity or omit if not applicable. Pass values in millions.\n"
        "- 'finalize': arguments: {'wacc': float, 'total_debt': float, 'cash_and_equivalents': float, 'pretax_cost_of_debt': float, 'cost_of_equity': float, 'unlevered_beta': float, 'explanation': str}\n"
        "  Finalize the execution and present the final parameters.\n\n"
        "Rules:\n"
        "1. Identify and inspect the latest Balance Sheet and Income Statement (or extracted markdown summaries) to extract: Total Debt (Short-term debt + Long-term debt), Cash & equivalents, Interest Expense, and Tax Rate.\n"
        "2. Call 'calculate_wacc' with your extracted values. (Note: risk_free_rate defaults to 0.042 and equity_risk_premium to 0.05 if not specified. Tax rate defaults to the historical tax rate provided).\n"
        "3. Provide a clear reasoning/thought process in the 'thought' field of each turn.\n"
        "4. Call 'finalize' on your last turn. The explanation must describe the line items extracted and where they came from (e.g. filename and snippet)."
    )

    # Calculate default shares outstanding from market cap
    shares_outstanding = 0.0
    if share_price > 0:
        if market_cap > 1000000:
            shares_outstanding = (market_cap / 1000000.0) / share_price
        else:
            shares_outstanding = market_cap / share_price

    user_content = (
        f"Estimate the WACC for {ticker}. You have up to 4 turns.\n\n"
        f"**Initial Market Profile Details:**\n"
        f"- Share Price: ${share_price}\n"
        f"- Market Cap: ${market_cap}\n"
        f"- Raw Levered Beta: {beta}\n"
        f"- Historical/Baseline Tax Rate: {tax_rate * 100:.2f}%\n"
        f"- Shares Outstanding Estimate: {shares_outstanding:,.2f}M\n\n"
        f"**Available Files Catalog in Workspace:**\n"
        f"{files_catalog_str}\n"
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
            logger.error(f"WACC Agent failed at turn {turn}: {e}")
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
            final_wacc_results["wacc"] = float(args.get("wacc", 0.08))
            total_debt = float(args.get("total_debt", 0.0))
            cash = float(args.get("cash_and_equivalents", 0.0))
            final_wacc_results["net_debt"] = total_debt - cash
            final_wacc_results["unlevered_beta"] = float(
                args.get("unlevered_beta", beta)
            )
            final_wacc_results["levered_beta"] = beta
            final_wacc_results["cost_equity"] = float(args.get("cost_of_equity", 0.0))
            final_wacc_results["cost_debt_pretax"] = float(
                args.get("pretax_cost_of_debt", 0.0)
            )
            final_wacc_results["cost_debt_aftertax"] = final_wacc_results[
                "cost_debt_pretax"
            ] * (1 - tax_rate)
            final_wacc_results["explanation"] = str(args.get("explanation", ""))
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

        elif tool == "calculate_wacc":
            rf = float(args.get("risk_free_rate", 0.042))
            erp = float(args.get("equity_risk_premium", 0.05))
            b = float(args.get("beta", beta))
            sp = float(args.get("share_price", share_price))
            so = float(args.get("shares_outstanding", shares_outstanding))
            td = float(args.get("total_debt", 0.0))
            ca = float(args.get("cash_and_equivalents", 0.0))
            ie = float(args.get("interest_expense", 0.0))
            pt = float(args.get("pretax_cost_of_debt", 0.0))
            tr = float(args.get("tax_rate", tax_rate))
            tde = args.get("target_debt_to_equity")
            if tde is not None:
                tde = float(tde)
            mc = float(args.get("market_cap", market_cap))

            calc_res = calculate_wacc_formula(
                risk_free_rate=rf,
                equity_risk_premium=erp,
                beta=b,
                share_price=sp,
                shares_outstanding=so,
                total_debt=td,
                cash_and_equivalents=ca,
                interest_expense=ie,
                pretax_cost_of_debt=pt,
                tax_rate=tr,
                target_debt_to_equity=tde,
                market_cap=mc,
            )

            # Store calculation results in case agent finalizes using them
            final_wacc_results["wacc"] = calc_res["wacc_final"]
            final_wacc_results["net_debt"] = td - ca
            final_wacc_results["unlevered_beta"] = calc_res["unlevered_beta"]
            final_wacc_results["levered_beta"] = calc_res["levered_beta"]
            final_wacc_results["cost_equity"] = calc_res["cost_equity"]
            final_wacc_results["cost_debt_pretax"] = calc_res["cost_debt_pretax"]
            final_wacc_results["cost_debt_aftertax"] = calc_res["cost_debt_aftertax"]
            final_wacc_results["weight_equity"] = calc_res["weight_equity"]
            final_wacc_results["weight_debt"] = calc_res["weight_debt"]
            final_wacc_results["explanation"] = calc_res["explanation"]

            history.append(
                {
                    "role": "user",
                    "content": f"Observation from calculate_wacc:\n{json.dumps({k: v for k, v in calc_res.items() if k != 'explanation'}, indent=2)}\n\nCalculated explanation:\n{calc_res['explanation']}",
                }
            )

        else:
            history.append({"role": "user", "content": f"Error: Unknown tool '{tool}'"})

    # Trigger Curator Agent to capture lessons in model_learning.md
    try:
        from src.pipeline.curator_agent import CuratorAgent

        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(llm.settings)
        curator.curate_model_agent(ticker, "WACC", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for WACC agent: {e}")

    return final_wacc_results
