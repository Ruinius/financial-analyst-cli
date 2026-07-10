import asyncio
import logging
from pathlib import Path
from typing import Optional

from src.core.exceptions import WorkspaceError
from src.core.blackboard import (
    load_workspace_state,
    DCFProjectionYear,
    ModelAssumptions,
    BaseFinancialModel,
)
from src.agents.curator_agent import CuratorAgent

import json
from datetime import datetime
from typing import Dict, Any, List, Tuple

from src.core.config import load_config
import src.utils.formatting as formatting
from src.utils.financial_math import NUMBER_EXTRACT_RE
from src.rust_core import calculate_dcf


def clean_value(val_str: Any) -> float:
    if val_str is None:
        return 0.0
    val_str_cleaned = str(val_str).strip()
    if val_str_cleaned == "N/A" or val_str_cleaned == "--" or not val_str_cleaned:
        return 0.0
    cleaned = (
        val_str_cleaned.replace(",", "")
        .replace("$", "")
        .replace("x", "")
        .replace("X", "")
        .strip()
    )
    is_negative = False
    if cleaned.startswith("("):
        is_negative = True
        cleaned = cleaned.strip("()")

    cleaned = cleaned.replace("%", "")

    # ⚡ Bolt Optimization: Fast path for clean numeric strings
    try:
        num = float(cleaned)
        if is_negative:
            num = -num
        return num
    except ValueError:
        pass

    # ⚡ Bolt Optimization: Replace re.search with precompiled regex to bypass regex recompilation overhead (~4.5x speedup)
    match = NUMBER_EXTRACT_RE.search(cleaned)
    if match:
        try:
            num = float(match.group(1))
            if is_negative:
                num = -num
            return num
        except ValueError:
            return 0.0
    return 0.0


def parse_markdown_table(
    text: str, table_name: Optional[str] = None
) -> List[Dict[str, str]]:
    start_idx = 0
    end_idx = len(text)
    target_name = None

    if table_name:
        target_name = table_name.lower().replace("#", "").strip()
        text_lower = text.lower()

        if target_name not in text_lower:
            return []

        search_idx = 0
        found = False
        while True:
            h_idx = text_lower.find(target_name, search_idx)
            if h_idx == -1:
                break

            line_start = text_lower.rfind("\n", 0, h_idx)
            if line_start == -1:
                line_start = 0
            else:
                line_start += 1

            if text_lower[line_start] == "#":
                start_idx = line_start
                found = True
                break

            search_idx = h_idx + 1

        if not found:
            return []

        # Fast fail and avoid splitting huge string by calculating exact bounds
        # Find the last occurrence of the target name to ensure we capture all sub-tables
        last_target_idx = -1
        search_idx_end = len(text_lower)
        while True:
            h_idx = text_lower.rfind(target_name, 0, search_idx_end)
            if h_idx == -1:
                break
            line_start = text_lower.rfind("\n", 0, h_idx)
            if line_start == -1:
                line_start = 0
            else:
                line_start += 1
            if text_lower[line_start] == "#":
                last_target_idx = h_idx
                break
            search_idx_end = h_idx

        if last_target_idx != -1:
            end_idx1 = text_lower.find("\n## ", last_target_idx + 1)
            end_idx2 = text_lower.find("\n# ", last_target_idx + 1)
            if end_idx1 != -1 and end_idx2 != -1:
                end_idx = min(end_idx1, end_idx2)
            elif end_idx1 != -1:
                end_idx = end_idx1
            elif end_idx2 != -1:
                end_idx = end_idx2

    # Fast parsing
    headers = []
    rows = []
    in_target_table = table_name is None
    in_table = False

    # We only care about the table within the bounds
    table_text = text[start_idx:end_idx]

    # ⚡ Bolt Optimization: Fast path to bypass expensive `.split("\n")` allocation on large file slices
    # Fast fail if the sliced section obviously contains no markdown table elements
    if "|" not in table_text:
        return []

    lines = table_text.split("\n")
    for i, line in enumerate(lines):
        if line and line[0] == "#" and line.startswith(("# ", "## ", "### ")):
            if target_name:
                cleaned_line = line.lower().replace("#", "").strip()
                if target_name in cleaned_line:
                    in_target_table = True
                elif in_target_table:
                    in_target_table = False

        if in_target_table and "|" in line:
            if not in_table:
                if i + 1 < len(lines) and "|---" in lines[i + 1].replace(" ", ""):
                    headers = [x.strip() for x in line.split("|")[1:-1]]
                    in_table = True
            elif "---" not in line:
                # ⚡ Bolt Optimization: Fast-fail by checking native character count before expensive list allocation and split operations
                if line.count("|") - 1 == len(headers):
                    row_vals = [x.strip() for x in line.split("|")[1:-1]]
                    if len(row_vals) == len(headers):
                        rows.append(dict(zip(headers, row_vals)))
        elif in_table and not line.strip():
            in_table = False

    return rows


def parse_kv_table(text: str, section_name: str) -> Dict[str, str]:
    rows = parse_markdown_table(text, section_name)
    result = {}
    for r in rows:
        keys = list(r.keys())
        if len(keys) >= 2:
            key = r[keys[0]].strip().replace("**", "")
            val = r[keys[1]].strip().replace("**", "")
            result[key] = val
    return result


def parse_financial_summary(content: str) -> Dict[str, str]:
    metrics = {}
    content_lower = content.lower()
    start_idx = content_lower.find("## financial summary")
    if start_idx != -1:
        start_idx = content_lower.find("\n", start_idx)
        if start_idx != -1:
            end_idx = len(content)
            for h in ["\n---", "\n##"]:
                pos = content_lower.find(h, start_idx)
                if pos != -1 and pos < end_idx:
                    end_idx = pos

            table_text = content[start_idx:end_idx].strip()

            # ⚡ Bolt Optimization: Fast path to bypass expensive `.split("\n")` allocation on large file slices
            if "|" not in table_text:
                return metrics

            for line in table_text.split("\n"):
                if "|" in line and "---" not in line and "Metric" not in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 3:
                        metric_name = parts[1].replace("**", "").strip()
                        metric_val = parts[2].replace("**", "").strip()
                        metrics[metric_name] = metric_val
    return metrics


class Modeler:
    def __init__(self):
        self.settings = load_config()

    def run_modeling(self, ticker: Optional[str] = None) -> None:
        if ticker:
            from src.cli.commands.use import main_use

            main_use(ticker)
            self.settings = load_config()

        if not self.settings.active_workspace_path:
            raise ValueError(
                "No active workspace is selected. Use 'fa use <ticker>' first."
            )

        workspace = Path(self.settings.active_workspace_path)
        active_ticker = self.settings.active_ticker

        formatting.print_info(f"--- Financial Modeling Started for {active_ticker} ---")

        state = load_workspace_state(active_ticker)
        has_blackboard_data = bool(
            state.company_data.quarterly_financials
            or state.company_data.yearly_financials
        )

        if not has_blackboard_data:
            formatting.print_warning(
                "Required historical analysis missing. Run extraction and historical synthesis first."
            )
            return

        learning_context = ""
        assumptions = self.calculate_default_assumptions(
            active_ticker, workspace, learning_context
        )

        try:
            formatting.print_info(
                "Curating initial recommendations from WACC, Growth, Margin, and Non-Operating sub-agents..."
            )
            sub_agent_logs = (
                f"WACC explanation: {assumptions.get('wacc_explanation', '')}\n"
                f"Growth explanation: {assumptions.get('growth_explanation', '')}\n"
                f"Margin explanation: {assumptions.get('margin_explanation', '')}\n"
                f"Non-Operating explanation: {assumptions.get('non_operating_explanation', '')}"
            )
            CuratorAgent(self.settings).curate(
                active_ticker, "model", sub_agent_logs, update_wiki=False
            )
        except Exception as e:
            logger.error(f"Failed to run curator before DCF Modeling Agent: {e}")

        curated_learning_context = ""
        assumptions = self.estimate_llm_assumptions(
            active_ticker, workspace, assumptions, curated_learning_context
        )

        assumptions = self.propose_and_validate_assumptions(
            active_ticker, workspace, assumptions
        )

        self.generate_financial_model(active_ticker, workspace, assumptions)

        try:
            formatting.print_info(
                "Curating final DCF modeling run and updating wiki..."
            )
            dcf_agent_logs = assumptions.get("dcf_agent_log", "")
            if not dcf_agent_logs:
                dcf_agent_logs = f"Executed modeling stage. Generated model projections with assumptions: {json.dumps(assumptions, indent=2)}"
            CuratorAgent(self.settings).curate(
                active_ticker, "model", dcf_agent_logs, update_wiki=True
            )
        except Exception as e:
            logger.error(f"Failed to run curator after DCF Modeling Agent: {e}")

        formatting.print_success(f"Modeling finished for {active_ticker}.")

    def calculate_default_assumptions(
        self, ticker: str, workspace: Path, learning_context: str = ""
    ) -> Dict[str, Any]:
        from src.services.market_data import get_market_profile

        market_data = {}
        try:
            market_data = get_market_profile(ticker)
            if not market_data.get("valid"):
                formatting.print_warning(
                    f"Error fetching market data: {market_data.get('error')}"
                )
        except Exception as e:
            formatting.print_warning(f"Error fetching/parsing market data: {e}")

        share_price = market_data.get("share_price") or 0
        market_cap = market_data.get("market_cap") or 0
        raw_beta = market_data.get("beta")
        if raw_beta is None:
            raw_beta = 1.0

        workspace_state = load_workspace_state(ticker)

        # Get shares outstanding from blackboard or fallback to disk
        shares_out = 0.0
        completed_reports = sorted(
            [
                r
                for r in workspace_state.reports.values()
                if r.income_statement_status == "completed"
            ],
            key=lambda r: (r.fiscal_year, r.fiscal_period),
            reverse=True,
        )
        if completed_reports:
            latest_report = completed_reports[0]
            shares_out = (
                latest_report.financial_data.diluted_shares
                or latest_report.financial_data.basic_shares
            )

        if shares_out <= 0.0 and workspace_state.company_data.quarterly_financials:
            shares_out = (
                workspace_state.company_data.quarterly_financials[-1].diluted_shares
                or workspace_state.company_data.quarterly_financials[-1].basic_shares
            )

        if shares_out > 0.0:
            formatting.print_info(
                f"Using latest extracted quarter diluted shares outstanding: {shares_out:,.2f}M"
            )
        else:
            shares_out = market_data.get("shares_outstanding") or 0
            if shares_out > 100000:
                shares_out = shares_out / 1000000.0
            formatting.print_info(
                f"No extracted shares found. Using market data shares outstanding: {shares_out:,.2f}M"
            )

        hist_financials = workspace_state.company_data.quarterly_financials
        historical_views = workspace_state.company_data.historical_analyst_views

        def get_median(lst: List[float]) -> float:
            if not lst:
                return 0.0
            sorted_lst = sorted(lst)
            n = len(sorted_lst)
            if n % 2 == 1:
                return sorted_lst[n // 2]
            else:
                return (sorted_lst[n // 2 - 1] + sorted_lst[n // 2]) / 2.0

        num_quarters = len(hist_financials)

        ltm_warning = False
        if num_quarters < 4:
            formatting.print_warning(
                "Less than 4 quarters of history. LTM is absolutely not available."
            )
            ltm_warning = True

        l4q = hist_financials[-4:] if hist_financials else []

        if num_quarters >= 4:
            base_rev = sum(q.revenue for q in l4q)
            base_ic = get_median([q.invested_capital for q in l4q])
        elif num_quarters > 0:
            base_rev = sum(q.revenue for q in hist_financials) * (4.0 / num_quarters)
            base_ic = get_median([q.invested_capital for q in hist_financials])
        else:
            base_rev = 0.0
            base_ic = 0.0

        if num_quarters > 0:
            adjusted_tax = get_median([q.adjusted_tax_rate for q in hist_financials])
        else:
            adjusted_tax = 0.21

        latest_view = historical_views[-1] if historical_views else None
        moat = latest_view.economic_moat if latest_view else "Narrow"
        if moat:
            moat = moat.replace("**", "").strip()
        else:
            moat = "Narrow"

        from src.services.llm_client import get_llm_client
        from src.agents.modeler_agents.wacc_agent import run_wacc_agent
        from src.agents.modeler_agents.growth_agent import run_growth_agent
        from src.agents.modeler_agents.margin_agent import run_margin_agent
        from src.agents.modeler_agents.non_operating_agent import (
            run_non_operating_agent,
        )
        from src.core.blackboard import (
            TemporalBlackboard,
        )

        llm = get_llm_client()
        company_metadata = workspace_state.metadata
        if not company_metadata.company_name:
            company_metadata.company_name = ticker

        latest_period_record = hist_financials[-1] if hist_financials else None
        if latest_period_record:
            period_key = f"{latest_period_record.fiscal_year}_{latest_period_record.fiscal_period}"
        else:
            period_key = "2024_FY"

        if period_key not in workspace_state.reports:
            is_quarter = "Q" in period_key
            fy_str, fp_str = period_key.split("_")
            workspace_state.reports[period_key] = TemporalBlackboard(
                fiscal_year=int(fy_str) if fy_str.isdigit() else 2024,
                fiscal_period=fp_str,
                is_quarterly=is_quarter,
            )

        report = workspace_state.reports[period_key]
        if not report.financial_data.adjusted_tax_rate:
            report.financial_data.adjusted_tax_rate = adjusted_tax

        report.balance_sheet_status = "completed"
        report.income_statement_status = "completed"

        wacc_results = run_wacc_agent(
            client=llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key=period_key,
            learnings=learning_context,
        )

        wacc = wacc_results.get("wacc", 0.08)
        wacc_explanation = wacc_results.get("explanation", "")

        non_op_results = run_non_operating_agent(
            client=llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key=period_key,
            learnings=learning_context,
        )

        cash = non_op_results.get("cash", 0.0)
        short_term_investments = non_op_results.get("short_term_investments", 0.0)
        debt = non_op_results.get("debt", 0.0)
        preferred_equity = non_op_results.get("preferred_equity", 0.0)
        minority_interest = non_op_results.get("minority_interest", 0.0)
        other_financial = non_op_results.get("other_financial", 0.0)
        non_operating_explanation = non_op_results.get("explanation", "")

        net_debt = (
            debt
            + preferred_equity
            + minority_interest
            - cash
            - short_term_investments
            - other_financial
        )

        growth_results = run_growth_agent(
            client=llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key=period_key,
            learnings=learning_context,
        )

        margin_results = run_margin_agent(
            client=llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key=period_key,
            learnings=learning_context,
        )

        l4q_turnovers = []
        for q in l4q:
            t_val = q.capital_turnover
            l4q_turnovers.append(t_val)
        avg_turnover = (
            sum(l4q_turnovers) / len(l4q_turnovers) if l4q_turnovers else 100.0
        )

        if avg_turnover <= 0 or avg_turnover > 100:
            mct = 100.0
        else:
            mct = round(avg_turnover, 1)

        base_margin = margin_results["base_margin"]

        # Get currency, fx_rate, adr_ratio directly from blackboard metadata
        currency = (workspace_state.metadata.reporting_currency or "USD").upper()
        fx_rate = workspace_state.metadata.fx_rate
        adr_ratio = (
            workspace_state.metadata.adr_ratio
            if workspace_state.metadata.adr_ratio is not None
            else 1.0
        )

        # If fx_rate is default (1.0) and currency differs from trading_currency, try to dynamically fetch it
        trading_currency = (market_data.get("currency") or "USD").upper()
        if fx_rate == 1.0 and currency != trading_currency:
            from src.services.market_data import get_exchange_rate

            try:
                fx_data = get_exchange_rate(currency, trading_currency)
                if fx_data.get("rate"):
                    fx_rate = fx_data["rate"]
                    formatting.print_info(
                        f"Dynamically fetched exchange rate {currency} -> {trading_currency}: {fx_rate}"
                    )
            except Exception as e:
                formatting.print_warning(
                    f"Failed to dynamically fetch exchange rate for {currency} -> {trading_currency}: {e}"
                )

        if fx_rate is None:
            fx_rate = 1.0

        assumptions = {
            "wacc": wacc,
            "base_wacc": wacc,
            "capital_turnover": mct,
            "base_capital_turnover": mct,
            "revenue_growth_rate": growth_results["revenue_growth_rate"],
            "base_growth_rate": growth_results["base_growth_rate"],
            "margin_yr5": margin_results["margin_yr5"],
            "base_margin": base_margin,
            "terminal_margin": margin_results["terminal_margin"],
            "terminal_growth_rate": growth_results["terminal_growth_rate"],
            "base_terminal_growth": 0.04 if moat == "Wide" else 0.03,
            "adjusted_tax_rate": adjusted_tax,
            "base_adjusted_tax_rate": adjusted_tax,
            "base_revenue": base_rev,
            "base_ic": base_ic,
            "base_fcf": (base_rev * base_margin * (1 - adjusted_tax)),
            "moat": moat,
            "shares_outstanding": shares_out,
            "market_cap": market_cap,
            "share_price": share_price,
            "cash": cash,
            "short_term_investments": short_term_investments,
            "debt": debt,
            "preferred_equity": preferred_equity,
            "minority_interest": minority_interest,
            "other_financial": other_financial,
            "net_debt": net_debt,
            "wacc_explanation": wacc_explanation,
            "growth_explanation": growth_results.get("explanation", ""),
            "margin_explanation": margin_results.get("explanation", ""),
            "non_operating_explanation": non_operating_explanation,
            "ltm_warning": ltm_warning,
            "currency": currency,
            "fx_rate": fx_rate,
            "adr_ratio": adr_ratio,
        }

        return assumptions

    def run_valuation_calculation(
        self, ticker: str, workspace: Path, assumptions: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
        rev = assumptions["base_revenue"]
        base_margin = assumptions["base_margin"]
        target_margin_yr5 = assumptions["margin_yr5"]
        terminal_margin = assumptions.get("terminal_margin", target_margin_yr5)
        target_growth_yr5 = assumptions["revenue_growth_rate"]
        l4q_growth = assumptions["base_growth_rate"]
        terminal_growth = assumptions["terminal_growth_rate"]
        wacc = assumptions["wacc"]
        mct = assumptions["capital_turnover"]
        l4q_tax = assumptions["adjusted_tax_rate"]
        ic = assumptions["base_ic"]

        projections = []
        growth_rates = []
        for yr in range(1, 11):
            if yr <= 5:
                g = l4q_growth + (target_growth_yr5 - l4q_growth) * (yr / 5.0)
                m = base_margin + (target_margin_yr5 - base_margin) * (yr / 5.0)
            else:
                g = target_growth_yr5 + (terminal_growth - target_growth_yr5) * (
                    (yr - 5) / 5.0
                )
                m = target_margin_yr5 + (terminal_margin - target_margin_yr5) * (
                    (yr - 5) / 5.0
                )

            growth_rates.append(g)

            prev_rev = rev
            rev = rev * (1 + g)
            ebita = rev * m
            nopat = ebita * (1 - l4q_tax)
            reinvestment = (rev - prev_rev) / mct
            fcf = nopat - reinvestment
            ic = ic + reinvestment
            roic = (nopat / ic) if ic != 0 else 0
            df = 1 / ((1 + wacc) ** (yr - 0.5))
            pv = fcf * df

            projections.append(
                {
                    "year": yr,
                    "revenue": rev,
                    "growth": g,
                    "ebita": ebita,
                    "margin": m,
                    "nopat": nopat,
                    "reinvestment": reinvestment,
                    "ic": ic,
                    "roic": roic,
                    "fcf": fcf,
                    "df": df,
                    "pv": pv,
                }
            )

        fcf_base = projections[0]["fcf"] / (1 + growth_rates[0]) if growth_rates else 0
        dcf_result_str = calculate_dcf(
            revenue_growth_projections=growth_rates,
            terminal_growth_rate=terminal_growth,
            wacc=wacc,
            free_cash_flow_base=fcf_base,
            shares_outstanding=assumptions["shares_outstanding"],
            cash=assumptions.get("cash", 0.0),
            short_term_investments=assumptions.get("short_term_investments", 0.0),
            debt=assumptions.get("debt", 0.0),
            preferred_equity=assumptions.get("preferred_equity", 0.0),
            minority_interest=assumptions.get("minority_interest", 0.0),
            other_financial=assumptions.get("other_financial", 0.0),
            mid_year=True,
        )
        dcf_result = json.loads(dcf_result_str)

        currency = assumptions.get("currency", "USD")
        fx_rate = assumptions.get("fx_rate", 1.0)
        adr_ratio = assumptions.get("adr_ratio", 1.0)
        share_price = assumptions.get("share_price", 0.0)

        enterprise_value = dcf_result["enterprise_value"]
        cash_val = assumptions.get("cash", 0.0)
        st_inv_val = assumptions.get("short_term_investments", 0.0)
        debt_val = assumptions.get("debt", 0.0)
        pref_eq_val = assumptions.get("preferred_equity", 0.0)
        min_int_val = assumptions.get("minority_interest", 0.0)
        other_fin_val = assumptions.get("other_financial", 0.0)

        non_op_rows = []
        non_op_rows.append(f"| (+) Cash and Equivalents | ${cash_val:,.0f}M |")
        if st_inv_val != 0:
            non_op_rows.append(f"| (+) Short-term Investments | ${st_inv_val:,.0f}M |")
        non_op_rows.append(f"| (-) Total Debt | ${debt_val:,.0f}M |")
        if pref_eq_val != 0:
            non_op_rows.append(f"| (-) Preferred Equity | ${pref_eq_val:,.0f}M |")
        if min_int_val != 0:
            non_op_rows.append(f"| (-) Minority Interest | ${min_int_val:,.0f}M |")
        if other_fin_val > 0:
            non_op_rows.append(
                f"| (+) Other Financial Net Assets | ${other_fin_val:,.0f}M |"
            )
        elif other_fin_val < 0:
            non_op_rows.append(
                f"| (-) Other Financial Net Liabilities | ${abs(other_fin_val):,.0f}M |"
            )

        net_debt = (
            debt_val + pref_eq_val + min_int_val - cash_val - st_inv_val - other_fin_val
        )
        equity_value = enterprise_value - net_debt
        shares_outstanding = assumptions["shares_outstanding"]

        if shares_outstanding > 0:
            intrinsic_value_per_share = (
                (equity_value / shares_outstanding) * fx_rate * adr_ratio
            )
        else:
            intrinsic_value_per_share = 0.0

        if share_price > 0:
            upside_downside = (intrinsic_value_per_share - share_price) / share_price
            upside_downside_str = (
                f"+{upside_downside * 100:.1f}%"
                if upside_downside >= 0
                else f"{upside_downside * 100:.1f}%"
            )
        else:
            upside_downside_str = "N/A"

        calculation_date = datetime.now().strftime("%Y-%m-%d")

        val_table_rows = [
            "| Field | Value |",
            "| ----------------------------- | ------------- |",
            f"| Enterprise Value | ${enterprise_value:,.0f}M |",
        ]
        val_table_rows.extend(non_op_rows)
        val_table_rows.extend(
            [
                f"| **Equity Value** | **${equity_value:,.0f}M** |",
                f"| Diluted Shares Outstanding | {shares_outstanding:,.0f}M |",
                f"| **Intrinsic Value Per Share** | **${intrinsic_value_per_share:.2f}** |",
                f"| Currency | {currency} |",
                f"| FX Rate Applied | {fx_rate:.4f} |",
                f"| ADR Ratio Applied | {adr_ratio:.1f} |",
                f"| Current Market Price | ${share_price:.2f} |",
                f"| **Upside/Downside** | **{upside_downside_str}** |",
                f"| Calculation Date | {calculation_date} |",
            ]
        )
        valuation_table_str = "\n".join(val_table_rows)

        dcf_result["intrinsic_value_per_share"] = intrinsic_value_per_share
        dcf_result["equity_value"] = equity_value
        dcf_result["upside_downside"] = upside_downside_str
        dcf_result["calculation_date"] = calculation_date

        return dcf_result, projections, valuation_table_str

    def generate_financial_model(
        self, ticker: str, workspace: Path, assumptions: Dict[str, Any]
    ) -> None:
        json_dir = workspace / "9_scenario_model_json"
        json_dir.mkdir(parents=True, exist_ok=True)

        dcf_result, projections, valuation_table_str = self.run_valuation_calculation(
            ticker, workspace, assumptions
        )

        today = datetime.now().strftime("%Y%m%d")
        out_json_path = json_dir / f"{today}_{ticker}_0.json"

        model_state = {
            "ticker": ticker,
            "date": today,
            "assumptions": assumptions,
            "projections": projections,
            "valuation": dcf_result,
        }

        with open(out_json_path, "w", encoding="utf-8") as f:
            json.dump(model_state, f, indent=2)

        formatting.print_success(f"Generated DCF model and saved to {out_json_path}")

    def estimate_llm_assumptions(
        self,
        ticker: str,
        workspace: Path,
        base_assumptions: Dict[str, Any],
        learning_context: str = "",
    ) -> Dict[str, Any]:
        from src.services.llm_client import get_llm_client
        from src.agents.modeler_agents.dcf_modeling_agent import (
            run_dcf_modeling_agent,
        )
        from src.core.blackboard import load_workspace_state

        formatting.print_info(f"Running 10-Turn DCF Modeling Agent for {ticker}...")
        llm = get_llm_client()

        workspace_state = load_workspace_state(ticker)
        company_metadata = workspace_state.metadata
        if not company_metadata.company_name:
            company_metadata.company_name = ticker

        period_key = "2024_FY"
        if workspace_state.company_data.quarterly_financials:
            latest_q = workspace_state.company_data.quarterly_financials[-1]
            period_key = f"{latest_q.fiscal_year}_{latest_q.fiscal_period}"
        elif workspace_state.company_data.yearly_financials:
            latest_y = workspace_state.company_data.yearly_financials[-1]
            period_key = f"{latest_y.fiscal_year}_{latest_y.fiscal_period}"

        final_assumptions, comments, history_text = run_dcf_modeling_agent(
            client=llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key=period_key,
            base_assumptions=base_assumptions,
            learnings=learning_context,
        )

        final_assumptions["valuation_commentary"] = comments
        final_assumptions["dcf_agent_log"] = history_text
        return final_assumptions

    def propose_and_validate_assumptions(
        self, ticker: str, workspace: Path, assumptions: Dict[str, Any]
    ) -> Dict[str, Any]:
        return assumptions


logger = logging.getLogger(__name__)


async def orchestrate_model(
    orchestrator,
    ticker: str,
    agent: Optional[str] = None,
    non_interactive: bool = False,
) -> None:
    import src.agents.blackboard_orchestrator as bo

    def run_modeler_with_learning(agent_fn, agent_name, *args, **kwargs):
        from src.agents.agent_executor import last_agent_run

        # Clear any prior run state
        last_agent_run.set(None)

        res = agent_fn(*args, **kwargs)

        # Try to run learning
        run_info = last_agent_run.get()
        if run_info:
            turn_count, run_logs = run_info
            try:
                from src.agents.learning_agent import LearningAgent

                learning_agent = LearningAgent(
                    settings=orchestrator.settings, client=orchestrator.client
                )
                learning_agent.run_learning(
                    ticker=ticker,
                    agent_name=agent_name,
                    document_type="model",
                    turn_count=turn_count,
                    run_logs=run_logs,
                )
            except Exception as le:
                logger.error(f"LearningAgent run failed for {agent_name}: {le}")
        return res

    state = load_workspace_state(ticker)

    extract_agent_map = {
        "metadata": "metadata",
        "metadata_agent": "metadata",
        "balance_sheet": "balance_sheet",
        "balance_sheet_agent": "balance_sheet",
        "income_statement": "income_statement",
        "income_statement_agent": "income_statement",
        "shares": "shares",
        "shares_agent": "shares",
        "diluted_shares": "shares",
        "diluted_shares_agent": "shares",
        "organic_growth": "organic_growth",
        "organic_growth_agent": "organic_growth",
        "interpretation": "interpretation",
        "interpretation_agent": "interpretation",
        "ebita": "ebita",
        "ebita_agent": "ebita",
        "operating_ebita": "ebita",
        "operating_ebita_agent": "ebita",
        "tax": "tax",
        "tax_agent": "tax",
        "adjusted_taxes": "tax",
        "adjusted_taxes_agent": "tax",
        "analyst_report": "analyst_report",
        "analyst_report_agent": "analyst_report",
        "other": "other",
        "other_doc": "other",
        "other_doc_agent": "other",
    }

    model_agent_map = {
        "wacc": "wacc_agent",
        "wacc_agent": "wacc_agent",
        "growth": "growth_agent",
        "growth_agent": "growth_agent",
        "margin": "margin_agent",
        "margin_agent": "margin_agent",
        "non_operating": "non_operating_agent",
        "non_operating_agent": "non_operating_agent",
        "dcf": "dcf_modeling",
        "dcf_modeling": "dcf_modeling",
        "dcf_modeling_agent": "dcf_modeling",
    }

    normalized_agent = None
    if agent:
        agent_lower = agent.lower().strip()
        if agent_lower in model_agent_map:
            normalized_agent = model_agent_map[agent_lower]
        elif agent_lower in extract_agent_map:
            # Extraction agent, bypass this stage
            return
        else:
            raise WorkspaceError(f"Unknown agent: '{agent}'")

    # Verify global dependencies for model stage
    if normalized_agent:
        if state.metadata_status != "completed":
            raise WorkspaceError(
                "Missing dependency: Company metadata extraction must be completed first."
            )
        if not state.reports:
            raise WorkspaceError("No periods initialized on the blackboard.")

    if not state.reports:
        logger.warning("No reports found to execute modeling.")
        return

    # Find latest period key
    latest_period = sorted(list(state.reports.keys()))[-1]
    report = state.reports[latest_period]

    # Verify specific modeling dependencies
    if normalized_agent == "wacc_agent":
        if (
            report.balance_sheet_status != "completed"
            or report.income_statement_status != "completed"
        ):
            raise WorkspaceError(
                "Missing dependency: Balance sheet and income statement must be completed for the latest period before running WACC agent."
            )
    elif normalized_agent == "growth_agent":
        if state.analyzer_status != "completed":
            raise WorkspaceError(
                "Missing dependency: Trend analysis stage must be completed before running growth agent."
            )
    elif normalized_agent == "margin_agent":
        if state.analyzer_status != "completed":
            raise WorkspaceError(
                "Missing dependency: Trend analysis stage must be completed before running margin agent."
            )
    elif normalized_agent == "non_operating_agent":
        if report.balance_sheet_status != "completed":
            raise WorkspaceError(
                "Missing dependency: Balance sheet must be completed for the latest period before running non-operating agent."
            )
    elif normalized_agent == "dcf_modeling":
        if (
            report.wacc_agent_status != "completed"
            or report.growth_agent_status != "completed"
            or report.margin_agent_status != "completed"
            or report.non_operating_agent_status != "completed"
        ):
            raise WorkspaceError(
                "Missing dependency: All modeling assumptions (WACC, growth, margin, non-operating) must be completed before running DCF modeling agent."
            )

    learning_context = ""
    learnings_path = (
        Path(orchestrator.settings.active_workspace_path)
        / f"{ticker}_model_learning.md"
    )
    if learnings_path.exists():
        try:
            learning_context = learnings_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # Level 1 (Parallel): wacc_agent, growth_agent, margin_agent, non_operating_agent
    async def process_modeling_l1():
        tasks = []

        # A. WACC Agent
        if normalized_agent is None or normalized_agent == "wacc_agent":
            if (
                report.wacc_agent_status in ("pending", "failed", "running")
                or normalized_agent == "wacc_agent"
            ):

                async def run_wacc():
                    async with orchestrator.phase_sem:
                        orchestrator.checkout_status(
                            ticker, "wacc_agent", period=latest_period
                        )
                        try:
                            wacc_res = await asyncio.to_thread(
                                run_modeler_with_learning,
                                agent_fn=bo.run_wacc_agent,
                                agent_name="wacc",
                                client=orchestrator.client,
                                company_metadata=state.metadata,
                                workspace_state=state,
                                period_key=latest_period,
                                learnings=learning_context,
                            )
                            orchestrator.checkin_status(
                                ticker,
                                "wacc_agent",
                                "completed",
                                period=latest_period,
                                payload=wacc_res,
                            )
                        except Exception as e:
                            logger.error(f"WACC Agent failed: {e}")
                            orchestrator.checkin_status(
                                ticker, "wacc_agent", "failed", period=latest_period
                            )
                            raise

                tasks.append(
                    orchestrator.wrap_task("wacc_agent", latest_period, None, run_wacc)
                )

        # B. Growth Agent
        if normalized_agent is None or normalized_agent == "growth_agent":
            if (
                report.growth_agent_status in ("pending", "failed", "running")
                or normalized_agent == "growth_agent"
            ):

                async def run_growth():
                    async with orchestrator.phase_sem:
                        orchestrator.checkout_status(
                            ticker, "growth_agent", period=latest_period
                        )
                        try:
                            growth_res = await asyncio.to_thread(
                                run_modeler_with_learning,
                                agent_fn=bo.run_growth_agent,
                                agent_name="growth",
                                client=orchestrator.client,
                                company_metadata=state.metadata,
                                workspace_state=state,
                                period_key=latest_period,
                                learnings=learning_context,
                            )
                            orchestrator.checkin_status(
                                ticker,
                                "growth_agent",
                                "completed",
                                period=latest_period,
                                payload=growth_res,
                            )
                        except Exception as e:
                            logger.error(f"Growth Agent failed: {e}")
                            orchestrator.checkin_status(
                                ticker, "growth_agent", "failed", period=latest_period
                            )
                            raise

                tasks.append(
                    orchestrator.wrap_task(
                        "growth_agent", latest_period, None, run_growth
                    )
                )

        # C. Margin Agent
        if normalized_agent is None or normalized_agent == "margin_agent":
            if (
                report.margin_agent_status in ("pending", "failed", "running")
                or normalized_agent == "margin_agent"
            ):

                async def run_margin():
                    async with orchestrator.phase_sem:
                        orchestrator.checkout_status(
                            ticker, "margin_agent", period=latest_period
                        )
                        try:
                            margin_res = await asyncio.to_thread(
                                run_modeler_with_learning,
                                agent_fn=bo.run_margin_agent,
                                agent_name="margin",
                                client=orchestrator.client,
                                company_metadata=state.metadata,
                                workspace_state=state,
                                period_key=latest_period,
                                learnings=learning_context,
                            )
                            orchestrator.checkin_status(
                                ticker,
                                "margin_agent",
                                "completed",
                                period=latest_period,
                                payload=margin_res,
                            )
                        except Exception as e:
                            logger.error(f"Margin Agent failed: {e}")
                            orchestrator.checkin_status(
                                ticker, "margin_agent", "failed", period=latest_period
                            )
                            raise

                tasks.append(
                    orchestrator.wrap_task(
                        "margin_agent", latest_period, None, run_margin
                    )
                )

        # D. Non-Operating Agent
        if normalized_agent is None or normalized_agent == "non_operating_agent":
            if (
                report.non_operating_agent_status in ("pending", "failed", "running")
                or normalized_agent == "non_operating_agent"
            ):

                async def run_non_operating():
                    async with orchestrator.phase_sem:
                        orchestrator.checkout_status(
                            ticker, "non_operating_agent", period=latest_period
                        )
                        try:
                            non_op_res = await asyncio.to_thread(
                                run_modeler_with_learning,
                                agent_fn=bo.run_non_operating_agent,
                                agent_name="non_operating",
                                client=orchestrator.client,
                                company_metadata=state.metadata,
                                workspace_state=state,
                                period_key=latest_period,
                                learnings=learning_context,
                            )
                            orchestrator.checkin_status(
                                ticker,
                                "non_operating_agent",
                                "completed",
                                period=latest_period,
                                payload=non_op_res,
                            )
                        except Exception as e:
                            logger.error(f"Non-Operating Agent failed: {e}")
                            orchestrator.checkin_status(
                                ticker,
                                "non_operating_agent",
                                "failed",
                                period=latest_period,
                            )
                            raise

                tasks.append(
                    orchestrator.wrap_task(
                        "non_operating_agent",
                        latest_period,
                        None,
                        run_non_operating,
                    )
                )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            await orchestrator._process_failure_queue(ticker, non_interactive)

    await process_modeling_l1()

    if normalized_agent in (
        "wacc_agent",
        "growth_agent",
        "margin_agent",
        "non_operating_agent",
    ):
        return

    # Compile DCF model assumptions
    cur_state = load_workspace_state(ticker)
    cur_report = cur_state.reports[latest_period]

    if not cur_report.base_model or cur_report.dcf_modeling_status in (
        "pending",
        "failed",
        "running",
    ):
        modeler = Modeler()

        workspace = Path(orchestrator.settings.active_workspace_path)
        base_assumptions = modeler.calculate_default_assumptions(
            ticker, workspace, learning_context
        )

        try:
            sub_agent_logs = (
                f"WACC explanation: {base_assumptions.get('wacc_explanation', '')}\n"
                f"Growth explanation: {base_assumptions.get('growth_explanation', '')}\n"
                f"Margin explanation: {base_assumptions.get('margin_explanation', '')}\n"
                f"Non-Operating explanation: {base_assumptions.get('non_operating_explanation', '')}"
            )
            CuratorAgent(orchestrator.settings).curate(
                ticker, "model", sub_agent_logs, update_wiki=False
            )
        except Exception as e:
            logger.error(f"Curator initial model curation failed: {e}")

        # Reload updated model learning context after curation
        curated_learning_context = ""
        if learnings_path.exists():
            try:
                curated_learning_context = learnings_path.read_text(encoding="utf-8")
            except Exception:
                pass

        # Level 2 (Sequential): Run dcf_modeling_agent in a wrapped task
        async def run_dcf_modeling():
            orchestrator.checkout_status(ticker, "dcf_modeling", period=latest_period)
            try:
                final_assumptions = await asyncio.to_thread(
                    run_modeler_with_learning,
                    modeler.estimate_llm_assumptions,
                    "dcf_modeling",
                    ticker,
                    workspace,
                    base_assumptions,
                    curated_learning_context,
                )

                # Recalculate projections and output
                dcf_result, projections, valuation_table_str = (
                    modeler.run_valuation_calculation(
                        ticker, workspace, final_assumptions
                    )
                )

                # Create BaseFinancialModel Pydantic model
                model_assumptions = ModelAssumptions(
                    wacc=final_assumptions["wacc"],
                    company_beta_levered=final_assumptions.get("levered_beta", 1.0),
                    company_beta_unlevered=final_assumptions.get("unlevered_beta", 1.0),
                    industry_beta_unlevered=final_assumptions.get(
                        "unlevered_beta", 1.0
                    ),
                    risk_free_rate=final_assumptions.get("risk_free_rate", 0.042),
                    equity_risk_premium=final_assumptions.get(
                        "equity_risk_premium", 0.05
                    ),
                    pretax_cost_of_debt=final_assumptions.get(
                        "cost_debt_pretax", 0.062
                    ),
                    cost_of_equity=final_assumptions.get("cost_equity", 0.092),
                    weight_equity=final_assumptions.get("weight_equity", 1.0),
                    weight_debt=final_assumptions.get("weight_debt", 0.0),
                    target_debt_to_equity=final_assumptions.get(
                        "target_debt_to_equity", 0.0
                    ),
                    interest_expense=final_assumptions.get("interest_expense", 0.0),
                    capital_turnover=final_assumptions["capital_turnover"],
                    base_revenue=final_assumptions["base_revenue"],
                    base_invested_capital=final_assumptions["base_ic"],
                    revenue_growth_base=final_assumptions["base_growth_rate"],
                    revenue_growth_yr5=final_assumptions["revenue_growth_rate"],
                    ebita_margin_base=final_assumptions["base_margin"],
                    ebita_margin_yr5=final_assumptions["margin_yr5"],
                    terminal_margin=final_assumptions["terminal_margin"],
                    terminal_growth_rate=final_assumptions["terminal_growth_rate"],
                    adjusted_tax_rate=final_assumptions["adjusted_tax_rate"],
                    excess_cash=final_assumptions.get("cash", 0.0),
                    short_term_investments=final_assumptions.get(
                        "short_term_investments", 0.0
                    ),
                    debt=final_assumptions.get("debt", 0.0),
                    preferred_equity=final_assumptions.get("preferred_equity", 0.0),
                    minority_interest=final_assumptions.get("minority_interest", 0.0),
                    other_financial_assets_net=final_assumptions.get(
                        "other_financial", 0.0
                    ),
                    net_debt=final_assumptions.get("net_debt", 0.0),
                    shares_outstanding=final_assumptions["shares_outstanding"],
                    share_price=final_assumptions.get("share_price", 0.0),
                    market_cap=final_assumptions.get("market_cap", 0.0),
                )

                proj_years = [
                    DCFProjectionYear(
                        year=p["year"],
                        revenue=p["revenue"],
                        growth=p["growth"],
                        ebita=p["ebita"],
                        margin=p["margin"],
                        nopat=p["nopat"],
                        reinvestment=p["reinvestment"],
                        invested_capital=p["ic"],
                        roic=p["roic"],
                        fcf=p["fcf"],
                        discount_factor=p["df"],
                        present_value=p["pv"],
                    )
                    for p in projections
                ]

                base_model = BaseFinancialModel(
                    assumptions=model_assumptions,
                    projections=proj_years,
                    calculated_intrinsic_value_per_share=dcf_result[
                        "intrinsic_value_per_share"
                    ],
                    calculated_equity_value=dcf_result["equity_value"],
                    calculated_enterprise_value=dcf_result["enterprise_value"],
                    upside_downside_percentage=dcf_result["upside_downside"],
                    dcf_run_date=dcf_result["calculation_date"],
                )

                orchestrator.checkin_status(
                    ticker,
                    "dcf_modeling",
                    "completed",
                    period=latest_period,
                    payload=base_model,
                )

                # Generate financial model files on disk for backward compatibility
                modeler.generate_financial_model(ticker, workspace, final_assumptions)

                # Curate wiki
                dcf_agent_logs = final_assumptions.get("dcf_agent_log", "")
                CuratorAgent(orchestrator.settings).curate(
                    ticker, "model", dcf_agent_logs, update_wiki=True
                )

            except Exception as e:
                logger.error(f"DCF Modeling Agent failed: {e}")
                orchestrator.checkin_status(
                    ticker, "dcf_modeling", "failed", period=latest_period
                )
                raise

        await orchestrator.wrap_task(
            "dcf_modeling", latest_period, None, run_dcf_modeling
        )
        await orchestrator._process_failure_queue(ticker, non_interactive)
