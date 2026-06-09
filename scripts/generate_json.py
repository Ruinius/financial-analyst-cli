import sys
import os
import re
import json

# Add tools to path
sys.path.append(os.path.dirname(__file__))
from markdown_parser import (
    parse_markdown_table,
    parse_kv_table,
    clean_value as base_clean_value,
)


def clean_value(val_str):
    if val_str is None:
        return 0
    s = (
        str(val_str)
        .replace("x", "")
        .replace("X", "")
        .replace("M", "")
        .replace("B", "")
        .replace("K", "")
        .replace("$", "")
        .replace(" ", "")
    )
    return base_clean_value(s)


def _parse_dcf_assumptions_kv(content):
    """Parse the 2-column KV table under ## DCF Assumptions.

    The DCF Assumptions section contains two tables:
      1. A stage table (Parameter | Stage 1 | Stage 2 | Terminal)
      2. A KV table (Parameter | Value) with Base Revenue, Adjusted Tax Rate, etc.

    parse_kv_table only finds the first table, so this function extracts the
    text after the first table and re-parses to find the KV table.
    """
    lines = content.split("\n")
    in_section = False
    first_table_found = False
    in_first_table = False
    kv_start = None

    for i, line in enumerate(lines):
        if line.startswith("## DCF Assumptions"):
            in_section = True
            continue
        if in_section and (line.startswith("## ") and not line.startswith("### ")):
            break
        if in_section and "|" in line and not first_table_found:
            in_first_table = True
        if in_section and in_first_table and not line.strip():
            first_table_found = True
            in_first_table = False
            kv_start = i
            continue
        if first_table_found and kv_start is not None and "|" in line:
            # Found the second table; parse from here
            remaining = "\n".join(lines[kv_start:])
            # Use parse_kv_table on a synthetic section so it finds this table
            synthetic = "## DCF Assumptions KV\n" + remaining
            return parse_kv_table(synthetic, "## DCF Assumptions KV")

    # Fallback: try the original approach
    return parse_kv_table(content, "## DCF Assumptions")


def generate_json(ticker, md_path):
    print(f"--- Generating Model JSON for {ticker} ---")

    if not os.path.exists(md_path):
        print(f"Error: Path {md_path} does not exist.")
        return

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse Header Info
    unit_label = "thousands"
    local_currency = "USD"
    company_name = ticker

    meta_lines = content.split("\n")
    in_top_table = False
    for line in meta_lines:
        if line.startswith("# "):
            in_top_table = True
            name_match = re.search(r"#\s*(.*?)\s*\((.*?)\)", line)
            if name_match:
                company_name = name_match.group(1).strip()
        elif in_top_table and "|" in line:
            if "Unit" in line:
                m = re.search(r"\|\s*Unit\s*\|\s*([^|]+)\s*\|", line, re.IGNORECASE)
                if m:
                    unit_label = m.group(1).strip().lower()
            elif "Currency" in line:
                m = re.search(r"\|\s*Currency\s*\|\s*([^|]+)\s*\|", line, re.IGNORECASE)
                if m:
                    local_currency = m.group(1).strip().upper()
        elif in_top_table and line.startswith("##"):
            break

    # Parse Financial History
    hist_table = parse_markdown_table(content, "## Financial History")
    hist_json = []
    for q in hist_table:
        hist_json.append(
            {
                "time_period": q.get("Time Period", ""),
                "revenue": clean_value(q.get("Revenue")),
                "ebita": clean_value(q.get("EBITA")),
                "ebita_margin": clean_value(q.get("EBITA Margin")),
                "adj_tax_rate": clean_value(q.get("Adj Tax Rate")),
                "nopat": clean_value(q.get("NOPAT")),
                "invested_capital": clean_value(q.get("Invested Capital")),
                "organic_growth": clean_value(q.get("Organic Growth")),
            }
        )

    # Parse WACC
    wacc_kv = parse_kv_table(content, "## WACC")

    # Parse DCF Assumptions
    # The section has TWO tables: a stage table (Parameter/Stage1/Stage2/Terminal)
    # followed by a KV table (Parameter/Value) with Base Revenue, Tax Rate, etc.
    # parse_kv_table only finds the first table, so we need to extract the KV
    # table separately by finding it after the stage table.
    assump_kv = _parse_dcf_assumptions_kv(content)
    base_ic = clean_value(assump_kv.get("Base Invested Capital", "0"))

    # Assumptions table with stages
    assump_table = parse_markdown_table(content, "## DCF Assumptions")
    stage_data = {}
    for row in assump_table:
        param = row.get("Parameter", "").strip()
        if "Revenue Growth" in param:
            stage_data["revenue_growth_stage1"] = clean_value(
                row.get("Stage 1 (Yr 1-5)", "0")
            )
            stage_data["revenue_growth_stage2"] = clean_value(
                row.get("Stage 2 (Yr 6-10)", "0")
            )
            stage_data["revenue_growth_terminal"] = clean_value(
                row.get("Terminal", "0")
            )
        elif "EBITA Margin" in param:
            stage_data["ebita_margin_stage1"] = clean_value(
                row.get("Stage 1 (Yr 1-5)", "0")
            )
            stage_data["ebita_margin_stage2"] = clean_value(
                row.get("Stage 2 (Yr 6-10)", "0")
            )
            stage_data["ebita_margin_terminal"] = clean_value(row.get("Terminal", "0"))
        elif "Marginal Capital Turnover" in param:
            stage_data["marginal_capital_turnover_stage1"] = clean_value(
                row.get("Stage 1 (Yr 1-5)", "0")
            )
            stage_data["marginal_capital_turnover_stage2"] = clean_value(
                row.get("Stage 2 (Yr 6-10)", "0")
            )
            stage_data["marginal_capital_turnover_terminal"] = clean_value(
                row.get("Terminal", "0")
            )

    # Parse Intrinsic Value
    val_kv = parse_kv_table(content, "## Intrinsic Value")

    # Parse DCF Projections
    dcf_lines = []
    in_dcf = False
    for line in meta_lines:
        if line.startswith("## DCF Model"):
            in_dcf = True
        elif in_dcf and line.startswith("### Valuation"):
            break
        elif in_dcf:
            dcf_lines.append(line)

    proj_table = parse_markdown_table("\n".join(dcf_lines), "### Projections")

    # Transpose projections back into yearly dictionaries
    proj_json = []

    # Extract row arrays
    def get_row(label):
        for r in proj_table:
            if (
                label.lower() in r.get("", "").lower()
                or label.lower() in r.get(" ", "").lower()
            ):
                return r
        return {}

    rev_row = get_row("Revenue")
    growth_row = get_row("Growth")
    ebita_row = get_row("EBITA")
    nopat_row = get_row("NOPAT")
    fcf_row = get_row("FCF")
    pv_row = get_row("PV of FCF")

    current_ic = base_ic

    for i in range(11):
        if i == 0:
            yr_key = "Base"
            p_year = "Base"
        else:
            yr_key = f"Yr {i}"
            p_year = i

        p_rev = clean_value(rev_row.get(yr_key, "0"))
        p_growth = clean_value(growth_row.get(yr_key, "0"))
        p_ebita = clean_value(ebita_row.get(yr_key, "0"))
        p_nopat = clean_value(nopat_row.get(yr_key, "0"))
        p_fcf = clean_value(fcf_row.get(yr_key, "0"))
        p_pv = clean_value(pv_row.get(yr_key, "0"))

        delta_ic = 0
        if i > 0:
            delta_ic = p_nopat - p_fcf
            current_ic += delta_ic

        proj_json.append(
            {
                "year": p_year,
                "revenue": p_rev,
                "growth_rate": p_growth if p_growth else None,
                "ebita": p_ebita,
                "margin": p_ebita / p_rev if p_rev else 0,
                "nopat": p_nopat,
                "invested_capital": current_ic if i > 0 else base_ic,
                "delta_ic": delta_ic if i > 0 else None,
                "roic": p_nopat / current_ic if current_ic else 0,
                "fcf": p_fcf if p_fcf else None,
                "discount_factor": p_pv / p_fcf if p_fcf else None,
                "pv_fcf": p_pv if p_pv else None,
            }
        )

    # Terminal block
    term_rev = clean_value(rev_row.get("Terminal", "0"))
    term_growth = clean_value(growth_row.get("Terminal", "0"))
    term_ebita = clean_value(ebita_row.get("Terminal", "0"))
    term_nopat = clean_value(nopat_row.get("Terminal", "0"))
    term_fcf = clean_value(fcf_row.get("Terminal", "0"))
    term_pv = clean_value(pv_row.get("Terminal", "0"))

    val_table_kv = parse_kv_table(content, "### Valuation")

    mct_term = stage_data.get("marginal_capital_turnover_terminal", 100)
    if not mct_term:
        mct_term = 100
    term_ic = current_ic + (term_rev - proj_json[-1]["revenue"]) / mct_term
    term_roic = term_nopat / term_ic if current_ic else 0

    js_data = {
        "ticker": ticker,
        "company_name": company_name,
        "currency": local_currency,
        "unit": unit_label,
        "generated_date": wacc_kv.get("Calculation Date", ""),
        "historical": hist_json,
        "wacc": {
            "risk_free_rate": clean_value(wacc_kv.get("Risk-Free Rate", "0")),
            "equity_risk_premium": clean_value(wacc_kv.get("Equity Risk Premium", "0")),
            "beta_levered": clean_value(wacc_kv.get("Raw Levered Beta", "0")),
            "beta_unlevered": clean_value(wacc_kv.get("Unlevered Beta", "0")),
            "beta_adjusted": clean_value(wacc_kv.get("Adjusted Beta (Blume's)", "0")),
            "cost_of_equity": clean_value(wacc_kv.get("Cost of Equity", "0")),
            "total_debt": clean_value(wacc_kv.get("Total Debt", "0")),
            "interest_expense_annual": clean_value(
                wacc_kv.get("Interest Expense (Ann.)", "0")
            ),
            "cost_of_debt": clean_value(wacc_kv.get("Cost of Debt", "0")),
            "market_cap_usd": clean_value(wacc_kv.get("Market Cap", "0")),
            "weight_equity": clean_value(wacc_kv.get("Weight of Equity", "0")),
            "weight_debt": clean_value(wacc_kv.get("Weight of Debt", "0")),
            "tax_rate": clean_value(wacc_kv.get("Tax Rate (Statutory)", "0")),
            "wacc_calculated": clean_value(wacc_kv.get("Calculated WACC", "0")),
            "wacc": clean_value(wacc_kv.get("WACC (Bounded)", "0")),
        },
        "assumptions": {
            "revenue_growth_stage1": stage_data.get("revenue_growth_stage1", 0),
            "revenue_growth_stage2": stage_data.get("revenue_growth_stage2", 0),
            "revenue_growth_terminal": stage_data.get("revenue_growth_terminal", 0),
            "ebita_margin_stage1": stage_data.get("ebita_margin_stage1", 0),
            "ebita_margin_stage2": stage_data.get("ebita_margin_stage2", 0),
            "ebita_margin_terminal": stage_data.get("ebita_margin_terminal", 0),
            "marginal_capital_turnover_stage1": stage_data.get(
                "marginal_capital_turnover_stage1", 100
            ),
            "marginal_capital_turnover_stage2": stage_data.get(
                "marginal_capital_turnover_stage2", 100
            ),
            "marginal_capital_turnover_terminal": stage_data.get(
                "marginal_capital_turnover_terminal", 100
            ),
            "adjusted_tax_rate": clean_value(assump_kv.get("Adjusted Tax Rate", "0")),
            "base_revenue": clean_value(
                assump_kv.get("Base Revenue (Annualized)", "0")
            ),
            "base_invested_capital": base_ic,
        },
        "projections": proj_json,
        "terminal": {
            "revenue": term_rev,
            "growth_rate": term_growth,
            "ebita": term_ebita,
            "margin": term_ebita / term_rev if term_rev else 0,
            "nopat": term_nopat,
            "invested_capital": term_ic,
            "roic": term_roic,
            "reinvestment_rate": 0,
            "fcf_terminal": term_fcf,
            "terminal_value": clean_value(
                val_table_kv.get("Terminal Value (undiscounted)", "0")
            ),
            "discount_factor": term_pv / term_fcf if term_fcf else 0,
            "pv_terminal": clean_value(val_table_kv.get("PV of Terminal Value", "0")),
        },
        "valuation": {
            "sum_pv_fcf": clean_value(val_table_kv.get("Sum of PV (Years 1-10)", "0")),
            "pv_terminal_value": clean_value(
                val_table_kv.get("PV of Terminal Value", "0")
            ),
            "enterprise_value": clean_value(val_kv.get("Enterprise Value", "0")),
            "cash_and_equivalents": clean_value(
                val_kv.get("(+) Cash and Equivalents", "0")
            ),
            "short_term_investments": 0,
            "long_term_investments": 0,
            "total_debt": clean_value(val_kv.get("(-) Total Debt", "0")),
            "equity_value": clean_value(val_kv.get("Equity Value", "0")),
            "diluted_shares": clean_value(
                val_kv.get("Diluted Shares Outstanding", "0")
            ),
            "intrinsic_value_per_share": clean_value(
                val_kv.get("Intrinsic Value Per Share", "0")
            ),
            "current_price": clean_value(val_kv.get("Current Market Price", "0")),
            "upside_downside_pct": clean_value(val_kv.get("Upside/Downside", "0")),
        },
    }

    json_path = md_path.replace("_metadata.md", "_financial_model.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(js_data, f, indent=2)

    print(f"Saved cleanly structured JSON to {json_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python generate_json.py <ticker> <metadata_path>")
        sys.exit(1)
    generate_json(sys.argv[1], sys.argv[2])
