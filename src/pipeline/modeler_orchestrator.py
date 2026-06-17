import json
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from src.core.config import load_config
import src.utils.formatting as formatting
from src.rust_core.fallback import calculate_dcf

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
        if line.startswith("## ") or line.startswith("### "):
            if table_name and table_name.lower() in line.lower():
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
    match = re.search(
        r"## Financial Summary\s*\n(.*?)(?:\n---|\n##|$)", content, re.DOTALL
    )
    if match:
        table_text = match.group(1)
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

        # Phase 5 Implementation will be built out here
        assumptions = self.calculate_default_assumptions(active_ticker, workspace)
        assumptions = self.estimate_llm_assumptions(
            active_ticker, workspace, assumptions, learning_context
        )
        assumptions = self.propose_and_validate_assumptions(
            active_ticker, workspace, assumptions
        )
        self.generate_financial_model(active_ticker, workspace, assumptions)

        # Trigger Curator Agent
        logs = f"Executed modeling stage. Generated model projections with assumptions: {json.dumps(assumptions, indent=2)}"
        from src.pipeline.curator_agent import CuratorAgent

        CuratorAgent(self.settings).curate(active_ticker, "model", logs)

        formatting.print_success(f"Modeling finished for {active_ticker}.")

    def calculate_default_assumptions(
        self, ticker: str, workspace: Path
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

        hist_table = parse_markdown_table(quarter_content, "## Historical Financials")
        if len(hist_table) < 4:
            formatting.print_warning(
                "Less than 4 quarters of history. Using available data."
            )

        l4q = hist_table[-4:] if hist_table else []

        l4q_rev = sum(clean_value(q.get("Revenue")) for q in l4q)
        l4q_ebita = sum(clean_value(q.get("EBITA")) for q in l4q)
        l4q_growth = (
            sum(clean_value(q.get("Organic Growth")) / 100.0 for q in l4q) / len(l4q)
            if l4q
            else 0
        )
        l4q_tax = (
            sum(clean_value(q.get("Adj Tax Rate")) / 100.0 for q in l4q) / len(l4q)
            if l4q
            else 0.21
        )

        base_ic = clean_value(l4q[-1].get("Invested Capital", "0")) if l4q else 0
        (
            clean_value(str(l4q[-1].get("ROIC", "0")).replace("%", "")) / 100.0
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

        # For WACC (simplistic)
        rf = 0.042
        erp = 0.05

        debt = 0  # Need to fetch from extracted data if possible
        cash = 0

        cost_equity = rf + raw_beta * erp
        wacc_raw = cost_equity  # Simple unlevered WACC for now
        wacc = max(0.06, min(0.15, wacc_raw))

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

        base_rev = l4q_rev
        base_margin = l4q_ebita / l4q_rev if l4q_rev > 0 else 0

        assumptions = {
            "wacc": wacc,
            "base_wacc": wacc,
            "capital_turnover": mct,
            "base_capital_turnover": mct,
            "revenue_growth_rate": l4q_growth + growth_magnitude,
            "base_growth_rate": l4q_growth,
            "margin_yr5": base_margin + margin_magnitude,
            "base_margin": base_margin,
            "terminal_growth_rate": 0.04 if moat == "Wide" else 0.03,
            "base_terminal_growth": 0.04 if moat == "Wide" else 0.03,
            "adjusted_tax_rate": l4q_tax,
            "base_adjusted_tax_rate": l4q_tax,
            "base_revenue": base_rev,
            "base_ic": base_ic,
            "base_fcf": (base_rev * base_margin * (1 - l4q_tax)),  # simplistic fallback
            "moat": moat,
            "shares_outstanding": shares_out,
            "market_cap": market_cap,
            "share_price": share_price,
            "net_debt": debt - cash,
        }

        return assumptions

    def generate_financial_model(
        self, ticker: str, workspace: Path, assumptions: Dict[str, Any]
    ) -> None:
        """Generate the DCF model markdown and JSON."""
        model_dir = workspace / "6_financial_model"
        json_dir = workspace / "7_historical_model_json"

        model_dir.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)

        # Build projections
        rev = assumptions["base_revenue"]
        base_margin = assumptions["base_margin"]
        target_margin_yr5 = assumptions["margin_yr5"]
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
                m = target_margin_yr5

            growth_rates.append(g)

            prev_rev = rev
            rev = rev * (1 + g)
            ebita = rev * m
            nopat = ebita * (1 - l4q_tax)
            reinvestment = (rev - prev_rev) / mct
            fcf = nopat - reinvestment
            ic = ic + reinvestment
            roic = (nopat / ic) if ic != 0 else 0
            df = 1 / ((1 + wacc) ** yr)
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

        # Call Rust Core for valuation verification
        fcf_base = projections[0]["fcf"] / (1 + growth_rates[0]) if growth_rates else 0
        dcf_result_str = calculate_dcf(
            revenue_growth_projections=growth_rates,
            terminal_growth_rate=terminal_growth,
            wacc=wacc,
            free_cash_flow_base=fcf_base,
            shares_outstanding=assumptions["shares_outstanding"],
            net_debt=assumptions["net_debt"],
        )
        dcf_result = json.loads(dcf_result_str)

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

        md_content = f"""# Financial Model: {ticker}
Date: {today}

## Assumptions
- **WACC**: {wacc * 100:.2f}%
- **Revenue Growth Rate**: {target_growth_yr5 * 100:.2f}%
- **Terminal Growth Rate**: {terminal_growth * 100:.2f}%
- **Margin Yr5**: {target_margin_yr5 * 100:.2f}%
- **Capital Turnover**: {mct}x

## Valuation
- **Enterprise Value**: ${dcf_result["enterprise_value"]:,.0f}
- **Intrinsic Value Per Share**: ${dcf_result["intrinsic_value_per_share"]:.2f}

## Projections Summary
| Year | Revenue | Growth | EBITA Margin | FCF |
|---|---|---|---|---|
"""
        for p in projections:
            md_content += f"| Yr {p['year']} | {p['revenue']:,.0f} | {p['growth'] * 100:.2f}% | {p['margin'] * 100:.2f}% | {p['fcf']:,.0f} |\n"

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
        """Leverage historical financials and analyst views to estimate final assumptions."""
        # Simple implementation for now. In Phase 5, this would use the llm_client
        return base_assumptions

    def propose_and_validate_assumptions(
        self, ticker: str, workspace: Path, assumptions: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Render assumptions table using rich for user feedback."""
        # Cleaned up model_context.md and 6_company_context folder references
        return assumptions
