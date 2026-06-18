import json
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from src.core.config import load_config
import src.utils.formatting as formatting
from src.rust_core import calculate_dcf

logger = logging.getLogger(__name__)


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

    match = re.search(r"(-?\d+\.?\d*)", cleaned)
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
    lines = text.split("\n")
    headers = []
    rows = []
    in_target_table = table_name is None
    in_table = False

    for i, line in enumerate(lines):
        if line.startswith("## ") or line.startswith("### ") or line.startswith("# "):
            if (
                table_name
                and table_name.lower().replace("#", "").strip()
                in line.lower().replace("#", "").strip()
            ):
                in_target_table = True
            elif in_target_table and table_name:
                in_target_table = False

        if in_target_table and "|" in line:
            if not in_table:
                # possible header
                if i + 1 < len(lines) and "|---" in lines[i + 1].replace(" ", ""):
                    headers = [x.strip() for x in line.split("|")[1:-1]]
                    in_table = True
            elif "---" not in line:
                row_vals = [x.strip() for x in line.split("|")[1:-1]]
                if len(row_vals) == len(headers):
                    rows.append(dict(zip(headers, row_vals)))
        elif in_table and not line.strip():
            in_table = False
            pass

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
    """Parse values from the Financial Summary markdown table."""
    metrics = {}
    # ⚡ Bolt Optimization: Fast string search instead of re.DOTALL
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
            for line in table_text.split("\n"):
                if "|" in line and "---" not in line and "Metric" not in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 3:
                        metric_name = parts[1].replace("**", "").strip()
                        metric_val = parts[2].replace("**", "").strip()
                        metrics[metric_name] = metric_val
    return metrics


def get_latest_extracted_shares(workspace: Path) -> Optional[float]:
    """Retrieve diluted shares outstanding from the latest extracted quarter or filing."""
    extracted_dir = workspace / "4_extracted_data"
    if not extracted_dir.exists():
        return None

    extracted_files = []
    for p in extracted_dir.glob("*_extracted.md"):
        # Match YYYYMMDD prefix
        match = re.match(r"^(\d{8})_", p.name)
        if match:
            date_str = match.group(1)
            extracted_files.append((date_str, p))

    # Sort descending by date (latest first)
    extracted_files.sort(key=lambda x: x[0], reverse=True)

    for date_str, file_path in extracted_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            metrics = parse_financial_summary(content)

            # Try Diluted Shares first
            diluted = metrics.get("Diluted Shares Outstanding")
            if diluted:
                val = clean_value(diluted)
                if val > 0:
                    return val
            # Try Basic Shares as a fallback
            basic = metrics.get("Basic Shares Outstanding")
            if basic:
                val = clean_value(basic)
                if val > 0:
                    return val
        except Exception as e:
            logger.warning(
                f"Error parsing shares outstanding from {file_path.name}: {e}"
            )

    return None


class Modeler:
    def __init__(self):
        self.settings = load_config()

    def run_modeling(self, ticker: Optional[str] = None) -> None:
        """Run the valuation modeling pipeline for the active or provided ticker."""
        if ticker:
            from src.cli.commands.use import main_use

            main_use(ticker)
            self.settings = load_config()

        if not self.settings.active_workspace_path:
            raise ValueError(
                "No active workspace is selected. Use 'fa use <ticker>' first."
            )

        workspace = Path(self.settings.active_workspace_path)
        analysis_dir = workspace / "5_historical_analysis"

        # Determine the company ticker symbol
        active_ticker = self.settings.active_ticker

        formatting.print_info(f"--- Financial Modeling Started for {active_ticker} ---")

        # Check required files
        analyst_views_path = analysis_dir / "analyst_views.md"
        financials_quarter_path = analysis_dir / "financials_quarter.md"

        if not analyst_views_path.exists() or not financials_quarter_path.exists():
            formatting.print_warning(
                f"Required historical analysis files missing in {analysis_dir}. Run extraction and historical synthesis first."
            )
            return

        # Load modeling learnings if available
        learning_context = ""
        learning_path = workspace / f"{active_ticker}_model_learning.md"
        if learning_path.exists():
            try:
                learning_context = learning_path.read_text(encoding="utf-8")
            except Exception:
                pass

        # 1. Run WACC, Growth, Margin, Non-Operating sub-agents
        assumptions = self.calculate_default_assumptions(
            active_ticker, workspace, learning_context
        )

        # 2. Run Curator Agent first time (before DCF Modeling Agent starts)
        # to consolidate/curate lessons from WACC, Growth, Margin, Non-Operating sub-agents
        from src.pipeline.curator_agent import CuratorAgent

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
            CuratorAgent(self.settings).curate(active_ticker, "model", sub_agent_logs)
        except Exception as e:
            logger.error(f"Failed to run curator before DCF Modeling Agent: {e}")

        # Reload updated model learning context after curation
        curated_learning_context = ""
        if learning_path.exists():
            try:
                curated_learning_context = learning_path.read_text(encoding="utf-8")
            except Exception:
                pass

        # 3. Run the 10-turn DCF Modeling Agent with curated learning context
        assumptions = self.estimate_llm_assumptions(
            active_ticker, workspace, assumptions, curated_learning_context
        )

        # 4. Propose and validate assumptions (e.g. user override screen)
        assumptions = self.propose_and_validate_assumptions(
            active_ticker, workspace, assumptions
        )

        # 5. Generate final model
        self.generate_financial_model(active_ticker, workspace, assumptions)

        # 6. Run Curator Agent a second time (incorporating DCF Modeling Agent's logs)
        # This will curate model_learning.md and update wiki.md
        try:
            formatting.print_info(
                "Curating final DCF modeling run and updating wiki..."
            )
            dcf_agent_logs = assumptions.get("dcf_agent_log", "")
            if not dcf_agent_logs:
                dcf_agent_logs = f"Executed modeling stage. Generated model projections with assumptions: {json.dumps(assumptions, indent=2)}"
            CuratorAgent(self.settings).curate(active_ticker, "model", dcf_agent_logs)
        except Exception as e:
            logger.error(f"Failed to run curator after DCF Modeling Agent: {e}")

        # Trigger Indexer Agent to update folder index
        try:
            from src.pipeline.indexer_agent import IndexerAgent

            IndexerAgent(self.settings).run_indexing(active_ticker)
        except Exception as e:
            logger.error(f"Failed to run indexer agent after modeling: {e}")

        formatting.print_success(f"Modeling finished for {active_ticker}.")

    def calculate_default_assumptions(
        self, ticker: str, workspace: Path, learning_context: str = ""
    ) -> Dict[str, Any]:
        """Develop deterministic estimators for base WACC, capital turnover, and growth rates."""
        analysis_dir = workspace / "5_historical_analysis"

        # 1. Fetch Latest Market Data
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

        # Try to retrieve diluted shares outstanding from latest extracted quarter/filing
        extracted_shares = get_latest_extracted_shares(workspace)
        if extracted_shares is not None:
            shares_out = extracted_shares
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

        # Read historical quarterly data
        quarter_path = analysis_dir / "financials_quarter.md"
        with open(quarter_path, "r", encoding="utf-8") as f:
            quarter_content = f.read()

        def get_median(lst: List[float]) -> float:
            if not lst:
                return 0.0
            sorted_lst = sorted(lst)
            n = len(sorted_lst)
            if n % 2 == 1:
                return sorted_lst[n // 2]
            else:
                return (sorted_lst[n // 2 - 1] + sorted_lst[n // 2]) / 2.0

        hist_table = parse_markdown_table(quarter_content, "## Historical Financials")
        num_quarters = len(hist_table)

        ltm_warning = False
        if num_quarters < 4:
            formatting.print_warning(
                "Less than 4 quarters of history. LTM is absolutely not available."
            )
            ltm_warning = True

        l4q = hist_table[-4:] if hist_table else []

        # 1. Base revenue: sum of last 4 quarters (LTM), or annualized if fewer than 4 quarters
        if num_quarters >= 4:
            base_rev = sum(clean_value(q.get("Revenue")) for q in l4q)
        elif num_quarters > 0:
            base_rev = sum(clean_value(q.get("Revenue")) for q in hist_table) * (
                4.0 / num_quarters
            )
        else:
            base_rev = 0.0

        # 2. Base invested capital: median of LTM, or median of available quarters if fewer than 4 quarters
        if num_quarters >= 4:
            base_ic = get_median([clean_value(q.get("Invested Capital")) for q in l4q])
        elif num_quarters > 0:
            base_ic = get_median(
                [clean_value(q.get("Invested Capital")) for q in hist_table]
            )
        else:
            base_ic = 0.0

        # 3. Adjusted tax rate: median of all available quarters
        if num_quarters > 0:
            adjusted_tax = get_median(
                [clean_value(q.get("Adj Tax Rate")) / 100.0 for q in hist_table]
            )
        else:
            adjusted_tax = 0.21

        l4q_rev = sum(clean_value(q.get("Revenue")) for q in l4q) if l4q else 0.0
        l4q_ebita = sum(clean_value(q.get("EBITA")) for q in l4q) if l4q else 0.0
        l4q_growth = (
            sum(clean_value(q.get("Organic Growth")) / 100.0 for q in l4q) / len(l4q)
            if l4q
            else 0
        )

        # Parse analyst views for qualitative magnitudes
        analyst_views_path = analysis_dir / "analyst_views.md"
        with open(analyst_views_path, "r", encoding="utf-8") as f:
            analyst_content = f.read()

        views_table = parse_markdown_table(analyst_content, "## Analyst Views")
        latest_view = views_table[-1] if views_table else {}

        moat = latest_view.get("Economic Moat", "Narrow").replace("**", "").strip()
        margin_mag_str = latest_view.get("Margin Magnitude", "0")
        m_mag_match = re.search(r"([+-]?\d+)\s*pp", margin_mag_str)
        margin_magnitude = (float(m_mag_match.group(1)) / 100.0) if m_mag_match else 0

        growth_mag_str = latest_view.get("Growth Magnitude", "0")
        g_mag_match = re.search(r"([+-]?\d+)\s*pp", growth_mag_str)
        growth_magnitude = (float(g_mag_match.group(1)) / 100.0) if g_mag_match else 0

        # For WACC (agentic calculation)
        from src.services.llm_client import LLMClient
        from src.pipeline.modeler_agents.wacc_agent import run_wacc_agent
        from src.pipeline.modeler_agents.growth_agent import run_growth_agent
        from src.pipeline.modeler_agents.margin_agent import run_margin_agent
        from src.pipeline.modeler_agents.non_operating_agent import (
            run_non_operating_agent,
        )

        llm = LLMClient()
        wacc_results = run_wacc_agent(
            ticker=ticker,
            workspace=workspace,
            share_price=share_price,
            market_cap=market_cap,
            beta=raw_beta,
            tax_rate=adjusted_tax,
            llm=llm,
            learning_context=learning_context,
        )

        wacc = wacc_results["wacc"]
        wacc_explanation = wacc_results.get("explanation", "")

        # For non-operating categories (agentic calculation)
        non_op_results = run_non_operating_agent(
            ticker=ticker,
            workspace=workspace,
            llm=llm,
        )

        cash = non_op_results["cash"]
        short_term_investments = non_op_results["short_term_investments"]
        debt = non_op_results["debt"]
        preferred_equity = non_op_results["preferred_equity"]
        minority_interest = non_op_results["minority_interest"]
        other_financial = non_op_results["other_financial"]
        non_operating_explanation = non_op_results.get("explanation", "")

        # Calculate net_debt for backward compatibility
        net_debt = (
            debt
            + preferred_equity
            + minority_interest
            - cash
            - short_term_investments
            - other_financial
        )

        # For Growth rates (agentic calculation)
        growth_results = run_growth_agent(
            ticker=ticker,
            workspace=workspace,
            base_growth_rate=l4q_growth,
            target_growth_yr5=l4q_growth + growth_magnitude,
            terminal_growth_rate=0.04 if moat == "Wide" else 0.03,
            llm=llm,
            learning_context=learning_context,
        )

        # For Margins (agentic calculation)
        base_margin_init = l4q_ebita / l4q_rev if l4q_rev > 0 else 0
        margin_results = run_margin_agent(
            ticker=ticker,
            workspace=workspace,
            base_margin=base_margin_init,
            margin_yr5=base_margin_init + margin_magnitude,
            terminal_margin=base_margin_init + margin_magnitude,
            llm=llm,
            learning_context=learning_context,
        )

        # Turnovers
        l4q_turnovers = []
        for q in l4q:
            t_val = clean_value(str(q.get("Capital Turnover", "0")).replace("x", ""))
            l4q_turnovers.append(t_val)
        avg_turnover = (
            sum(l4q_turnovers) / len(l4q_turnovers) if l4q_turnovers else 100.0
        )

        if avg_turnover <= 0 or avg_turnover > 100:
            mct = 100.0
        else:
            mct = round(avg_turnover, 1)

        base_margin = margin_results["base_margin"]

        # Determine currency, fx_rate, and adr_ratio
        model_learning_path = workspace / f"{ticker}_model_learning.md"
        extract_learning_path = workspace / f"{ticker}_extract_learning.md"

        def get_metadata_from_learning(path: Path, pattern: str) -> Optional[str]:
            if not path.exists():
                return None
            try:
                content = path.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    match = re.search(pattern, line.strip(), re.IGNORECASE)
                    if match:
                        return match.group(1).strip()
            except Exception:
                pass
            return None

        # 1. Currency
        # Look in model_learning.md first, then extract_learning.md, then market_data, default to USD
        currency = None
        for p in [model_learning_path, extract_learning_path]:
            currency = get_metadata_from_learning(
                p, r"(?:Preferred\s*)?Currency:\s*([A-Za-z]{3})"
            )
            if currency:
                break
        if not currency:
            currency = market_data.get("currency")
        if not currency:
            currency = "USD"
        currency = currency.upper()

        # 2. FX Rate
        # Look in model_learning.md, default to None (we will compute or default to 1.0)
        fx_rate_str = get_metadata_from_learning(
            model_learning_path,
            r"(?:FX\s*Rate|FX\s*Rate\s*Applied|Exchange\s*Rate):\s*([0-9.]+)",
        )
        if not fx_rate_str:
            # Also try strict - FX: 0.15
            fx_rate_str = get_metadata_from_learning(
                model_learning_path, r"^-\s*FX:\s*([0-9.]+)\s*$"
            )

        fx_rate = None
        if fx_rate_str:
            try:
                fx_rate = float(fx_rate_str)
            except ValueError:
                pass

        # If FX rate not set, dynamically check if currencies differ
        if fx_rate is None:
            trading_currency = (market_data.get("currency") or "USD").upper()
            if currency != trading_currency:
                # Fetch exchange rate
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

        # 3. ADR Ratio
        # Look in model_learning.md, default to 1.0
        adr_ratio_str = get_metadata_from_learning(
            model_learning_path,
            r"(?:ADR\s*Ratio|ADR\s*Ratio\s*Applied|ADR):\s*([0-9.]+)",
        )
        if not adr_ratio_str:
            adr_ratio_str = get_metadata_from_learning(
                model_learning_path, r"^-\s*ADR:\s*([0-9.]+)\s*$"
            )

        adr_ratio = 1.0
        if adr_ratio_str:
            try:
                adr_ratio = float(adr_ratio_str)
            except ValueError:
                pass

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
            "base_fcf": (
                base_rev * base_margin * (1 - adjusted_tax)
            ),  # simplistic fallback
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
        """
        Run the projections and DCF valuation logic.
        Returns:
            dcf_result: The dictionary returned by calculate_dcf.
            projections: The list of projections for years 1-10.
            valuation_table_str: The formatted markdown table showing valuation results.
        """
        # Build projections using mid-year adjustment convention for discount factor
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

        # Call Rust Core for valuation verification using mid-year convention
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

        # Calculate Equity Value and updated Intrinsic Value per share in trading currency
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

        # Construct valuation table
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

        # Update dcf_result with recalculated values for JSON state
        dcf_result["intrinsic_value_per_share"] = intrinsic_value_per_share
        dcf_result["equity_value"] = equity_value
        dcf_result["upside_downside"] = upside_downside_str
        dcf_result["calculation_date"] = calculation_date

        return dcf_result, projections, valuation_table_str

    def generate_financial_model(
        self, ticker: str, workspace: Path, assumptions: Dict[str, Any]
    ) -> None:
        """Generate the DCF model markdown and JSON."""
        model_dir = workspace / "6_financial_model"
        json_dir = workspace / "7_historical_model_json"

        model_dir.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)

        dcf_result, projections, valuation_table_str = self.run_valuation_calculation(
            ticker, workspace, assumptions
        )

        target_margin_yr5 = assumptions["margin_yr5"]
        terminal_margin = assumptions.get("terminal_margin", target_margin_yr5)
        target_growth_yr5 = assumptions["revenue_growth_rate"]
        terminal_growth = assumptions["terminal_growth_rate"]
        wacc = assumptions["wacc"]
        mct = assumptions["capital_turnover"]
        l4q_tax = assumptions["adjusted_tax_rate"]

        # Create output JSON
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

        # Create output Markdown
        md_path = model_dir / f"{today}_{ticker}_model.md"

        wacc_explanation_str = assumptions.get("wacc_explanation", "")
        if wacc_explanation_str:
            wacc_explanation_str = f"\n{wacc_explanation_str}\n"

        growth_explanation_str = assumptions.get("growth_explanation", "")
        if growth_explanation_str:
            growth_explanation_str = f"\n{growth_explanation_str}\n"

        margin_explanation_str = assumptions.get("margin_explanation", "")
        if margin_explanation_str:
            margin_explanation_str = f"\n{margin_explanation_str}\n"

        non_operating_explanation_str = assumptions.get("non_operating_explanation", "")
        if non_operating_explanation_str:
            non_operating_explanation_str = f"\n{non_operating_explanation_str}\n"

        # Read historical quarters to include them in the summary table
        analysis_dir = workspace / "5_historical_analysis"
        quarter_path = analysis_dir / "financials_quarter.md"
        hist_table = []
        if quarter_path.exists():
            try:
                quarter_content = quarter_path.read_text(encoding="utf-8")
                hist_table = parse_markdown_table(
                    quarter_content, "## Historical Financials"
                )
            except Exception as e:
                logger.warning(
                    f"Error parsing historical financials in generate_financial_model: {e}"
                )

        # Construct rows for summary table
        table_rows = []

        # 1. Historical quarters (last 4, or whatever is available)
        for q in hist_table[-4:] if hist_table else []:
            time_period = q.get("Time Period") or q.get("Period End") or "N/A"
            rev_val = clean_value(q.get("Revenue"))
            growth_val = clean_value(q.get("Organic Growth"))
            margin_val = clean_value(q.get("EBITA Margin"))
            ic_val = clean_value(q.get("Invested Capital"))
            table_rows.append(
                f"| {time_period} | {rev_val:,.1f} | {growth_val:,.2f}% | {margin_val:,.2f}% | {ic_val:,.1f} | N/A | N/A | N/A |"
            )

        # 2. Base (Year 0)
        base_rev = assumptions["base_revenue"]
        base_margin = assumptions["base_margin"]
        base_ic = assumptions["base_ic"]
        base_fcf = assumptions.get("base_fcf", base_rev * base_margin * (1 - l4q_tax))
        table_rows.append(
            f"| Base (Year 0) | {base_rev:,.1f} | N/A | {base_margin * 100:.2f}% | {base_ic:,.1f} | {base_fcf:,.1f} | N/A | N/A |"
        )

        # 3. Projected Years 1 to 10
        for p in projections:
            yr = p["year"]
            rev_val = p["revenue"]
            growth_val = p["growth"] * 100
            margin_val = p["margin"] * 100
            ic_val = p["ic"]
            fcf_val = p["fcf"]
            df_val = p["df"]
            pv_val = p["pv"]
            table_rows.append(
                f"| Year {yr} | {rev_val:,.1f} | {growth_val:,.2f}% | {margin_val:,.2f}% | {ic_val:,.1f} | {fcf_val:,.1f} | {df_val:.4f} | {pv_val:,.1f} |"
            )

        # 4. Terminal Value
        terminal_fcf = dcf_result["terminal_value"]
        pv_terminal_value = terminal_fcf / ((1.0 + wacc) ** 10)
        table_rows.append(
            f"| Terminal | N/A | {terminal_growth * 100:.2f}% | {terminal_margin * 100:.2f}% | N/A | {terminal_fcf:,.1f} | {1.0 / ((1.0 + wacc) ** 10):.4f} | {pv_terminal_value:,.1f} |"
        )

        table_header = (
            "| Time Period | Revenue ($M) | Growth (%) | EBITA Margin (%) | Invested Capital ($M) | Free Cash Flow ($M) | Discount Factor | Discounted FCF |\n"
            "|---|---|---|---|---|---|---|---|"
        )
        table_str = table_header + "\n" + "\n".join(table_rows)

        warning_block = ""
        if assumptions.get("ltm_warning"):
            num_quarters = len(hist_table)
            warning_block = f"""
> [!WARNING]
> LTM is absolutely not available due to having fewer than 4 quarters of history (only {num_quarters} quarter(s) available).
> - Base Revenue has been annualized to ${base_rev:,.2f}M based on available quarters.
> - Base Invested Capital has been set to the median of available quarters: ${base_ic:,.2f}M.
"""

        # Construct assumptions comparison table
        base_wacc = assumptions.get("base_wacc", wacc)
        base_growth = assumptions.get("base_growth_rate", target_growth_yr5)
        base_term_growth = assumptions.get("base_terminal_growth", terminal_growth)
        base_margin_yr5 = assumptions.get("base_margin", base_margin)
        base_term_margin = assumptions.get("base_terminal_margin", terminal_margin)
        base_turnover = assumptions.get("base_capital_turnover", mct)
        base_tax = assumptions.get("base_adjusted_tax_rate", l4q_tax)
        comparison_table_str = f"""## Assumptions Used vs. Modeler Agents Recommendations

| Parameter | Recommended by Modeler Agents | Actually Used | Status |
|:---|:---|:---|:---|
| **WACC** | {base_wacc * 100:.2f}% | {wacc * 100:.2f}% | {'Updated' if abs(base_wacc - wacc) > 1e-6 else 'Unchanged'} |
| **Year 5 Growth** | {base_growth * 100:.2f}% | {target_growth_yr5 * 100:.2f}% | {'Updated' if abs(base_growth - target_growth_yr5) > 1e-6 else 'Unchanged'} |
| **Terminal Growth** | {base_term_growth * 100:.2f}% | {terminal_growth * 100:.2f}% | {'Updated' if abs(base_term_growth - terminal_growth) > 1e-6 else 'Unchanged'} |
| **Year 5 Margin** | {base_margin_yr5 * 100:.2f}% | {target_margin_yr5 * 100:.2f}% | {'Updated' if abs(base_margin_yr5 - target_margin_yr5) > 1e-6 else 'Unchanged'} |
| **Terminal Margin** | {base_term_margin * 100:.2f}% | {terminal_margin * 100:.2f}% | {'Updated' if abs(base_term_margin - terminal_margin) > 1e-6 else 'Unchanged'} |
| **Capital Turnover** | {base_turnover:.1f}x | {mct:.1f}x | {'Updated' if abs(base_turnover - mct) > 1e-6 else 'Unchanged'} |
| **Adjusted Tax Rate** | {base_tax * 100:.2f}% | {l4q_tax * 100:.2f}% | {'Updated' if abs(base_tax - l4q_tax) > 1e-6 else 'Unchanged'} |
"""

        valuation_commentary = assumptions.get("valuation_commentary", "")
        valuation_commentary_str = ""
        if valuation_commentary:
            valuation_commentary_str = f"""## Valuation Commentary & Modeler Critique
{valuation_commentary}
"""

        md_content = f"""# Financial Model: {ticker}
Date: {today}
{warning_block}
## Assumptions
- **WACC**: {wacc * 100:.2f}%
- **Revenue Growth Rate**: {target_growth_yr5 * 100:.2f}%
- **Terminal Growth Rate**: {terminal_growth * 100:.2f}%
- **Margin Yr5**: {target_margin_yr5 * 100:.2f}%
- **Terminal Margin**: {terminal_margin * 100:.2f}%
- **Capital Turnover**: {mct}x

{wacc_explanation_str}
{growth_explanation_str}
{margin_explanation_str}
{non_operating_explanation_str}

{comparison_table_str}

{valuation_commentary_str}

## Valuation
{valuation_table_str}

## Projections Summary
{table_str}
"""

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        formatting.print_success(
            f"Generated DCF model and saved to {md_path} and {out_json_path}"
        )

    def estimate_llm_assumptions(
        self,
        ticker: str,
        workspace: Path,
        base_assumptions: Dict[str, Any],
        learning_context: str = "",
    ) -> Dict[str, Any]:
        """Leverage the 10-turn DCF modeling agent to estimate final assumptions."""
        from src.services.llm_client import LLMClient
        from src.pipeline.modeler_agents.dcf_modeling_agent import (
            run_dcf_modeling_agent,
        )

        formatting.print_info(f"Running 10-Turn DCF Modeling Agent for {ticker}...")
        llm = LLMClient()
        final_assumptions, comments, history_text = run_dcf_modeling_agent(
            ticker=ticker,
            workspace=workspace,
            base_assumptions=base_assumptions,
            llm=llm,
            learning_context=learning_context,
        )

        final_assumptions["valuation_commentary"] = comments
        final_assumptions["dcf_agent_log"] = history_text
        return final_assumptions

    def propose_and_validate_assumptions(
        self, ticker: str, workspace: Path, assumptions: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Render assumptions table using rich for user feedback."""
        # Cleaned up model_context.md and 6_company_context folder references
        return assumptions
