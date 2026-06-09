import sys
import os
import re
import json
from datetime import datetime

# Add tools to path
sys.path.append(os.path.dirname(__file__))
from markdown_parser import parse_markdown_table, parse_kv_table, clean_value

def calculate_modeling(ticker, md_path):
    print(f"--- Financial Modeling Started for {ticker} ---")
    
    if not os.path.exists(md_path):
        print(f"Error: Path {md_path} does not exist.")
        return

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Fetch Latest Market Data
    import subprocess
    profile_cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "market_data.py"), "profile", ticker]
    res = subprocess.run(profile_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error fetching market data: {res.stderr}")
        return
    
    try:
        market_data = json.loads(res.stdout)
    except Exception as e:
        print(f"Error parsing market data JSON: {e}")
        return

    share_price = market_data.get("share_price") or 0
    market_cap = market_data.get("market_cap") or 0
    raw_beta = market_data.get("beta")
    if raw_beta is None: raw_beta = 1.0
    shares_out = market_data.get("shares_outstanding") or 0

    # 2. Read metadata unit & company name
    unit_label = "thousands"
    local_currency = "USD"
    adr_ratio = 1.0
    company_name = ticker
    
    meta_lines = content.split('\n')
    
    # Extract company name from first line: "# Company Name (TICKER)"
    if meta_lines and meta_lines[0].startswith('# '):
        name_match = re.search(r'#\s*(.*?)\s*\((.*?)\)', meta_lines[0])
        if name_match:
            company_name = name_match.group(1).strip()
    
    in_top_table = False
    for line in meta_lines:
        if line.startswith('# '):
            in_top_table = True
        elif in_top_table and '|' in line:
            if 'Unit' in line:
                m = re.search(r'\|\s*Unit\s*\|\s*([^|]+)\s*\|', line, re.IGNORECASE)
                if m: unit_label = m.group(1).strip().lower()
            elif 'Currency' in line:
                m = re.search(r'\|\s*Currency\s*\|\s*([^|]+)\s*\|', line, re.IGNORECASE)
                if m: local_currency = m.group(1).strip().upper()
            elif 'ADR Ratio' in line:
                m = re.search(r'\|\s*ADR Ratio\s*\|\s*([\d\.]+)\s*\|', line, re.IGNORECASE)
                if m: adr_ratio = float(m.group(1).strip())
        elif in_top_table and line.startswith('##'):
            break

    unit_suffix_map = {"thousands": "K", "millions": "M", "billions": "B"}
    unit_suffix = unit_suffix_map.get(unit_label, "")
    unit_factor_map = {"ones": 1, "thousands": 1_000, "millions": 1_000_000, "billions": 1_000_000_000}
    unit_factor = unit_factor_map.get(unit_label, 1_000)

    fx_rate = 1.0
    if local_currency != "USD":
        query_curr = "CNY" if local_currency == "RMB" else local_currency
        fx_cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "market_data.py"), "profile", f"{query_curr}USD=X"]
        fx_res = subprocess.run(fx_cmd, capture_output=True, text=True)
        if fx_res.returncode == 0:
            try:
                fx_data = json.loads(fx_res.stdout)
                if fx_data.get("valid"):
                    fx_rate = fx_data.get("share_price", 1.0)
                    print(f"  Fetched FX Rate: 1 {local_currency} ({query_curr}) = {fx_rate} USD")
                else:
                    print(f"  FX fetch failed for {query_curr}USD=X")
            except Exception as e:
                print(f"Error parsing FX data: {e}")

    # 2b. Historical & Qualitative Data
    hist_table = parse_markdown_table(content, "## Financial History")
    if len(hist_table) < 4:
        print("Warning: Less than 4 quarters of history. Using available data.")
    
    l4q = hist_table[-4:]
    l4q_rev = sum(clean_value(q.get("Revenue")) for q in l4q)
    l4q_ebita = sum(clean_value(q.get("EBITA")) for q in l4q)
    l4q_growth = sum(clean_value(q.get("Organic Growth")) for q in l4q) / len(l4q) if l4q else 0
    l4q_tax = sum(clean_value(q.get("Adj Tax Rate")) for q in l4q) / len(l4q) if l4q else 0.21
    base_ic = clean_value(l4q[-1].get("Invested Capital", "0")) if l4q else 0
    base_roic = clean_value(str(l4q[-1].get("ROIC", "0")).replace('%', '')) / 100.0 if l4q else 0
    
    moat_kv = parse_kv_table(content, "### Economic Moat")
    moat = moat_kv.get("Rating", "Narrow").replace("**","").strip()
    
    margin_kv = parse_kv_table(content, "### EBITA Margin Outlook")
    margin_mag_str = margin_kv.get("Magnitude", "0")
    m_mag_match = re.search(r'([+-]?\d+)\s*pp', margin_mag_str)
    margin_magnitude = (float(m_mag_match.group(1)) / 100.0) if m_mag_match else 0
    
    growth_kv = parse_kv_table(content, "### Organic Growth Outlook")
    growth_mag_str = growth_kv.get("Magnitude", "0")
    g_mag_match = re.search(r'([+-]?\d+)\s*pp', growth_mag_str)
    growth_magnitude = (float(g_mag_match.group(1)) / 100.0) if g_mag_match else 0

    # 2c. Read balance sheet data from the most recent processed financial report
    doc_table = parse_markdown_table(content, "## Processed Documents")
    cash = 0
    debt = 0
    interest = 0
    if doc_table:
        # Find the most recent financial report (EA, 10Q, 10K)
        last_fin_report = None
        for doc in reversed(doc_table):
            dtype = doc.get("Document Type", "").strip()
            if dtype in ["earnings_announcement", "quarterly_filing", "annual_filing"]:
                last_fin_report = doc
                break
        
        if last_fin_report:
            last_doc = last_fin_report
        doc_file = re.search(r'\[([^\]]+\.md)\]', last_doc.get("File", ""))
        if doc_file:
            doc_dir = os.path.dirname(md_path)
            doc_path = os.path.join(doc_dir, doc_file.group(1))
            if os.path.exists(doc_path):
                with open(doc_path, "r", encoding="utf-8") as df:
                    doc_content = df.read()
                # Parse balance sheet line items for cash/debt
                bs_items = parse_markdown_table(doc_content, "### Line Items")
                # Also try financial summary for interest
                fin_summary = parse_kv_table(doc_content, "## Financial Summary")
                
                debt_names = ["short_term_debt", "long_term_debt", "current_portion_long_term_debt",
                              "short_term_borrowings", "long_term_borrowings", "notes_payable"]
                cash_names = ["cash_and_equivalents", "short_term_investments", "long_term_investments"]
                interest_names = ["interest_expense", "interest_expense_net"]
                
                line_item_interest = 0
                for item in bs_items:
                    std = item.get("Standardized Name", "").strip()
                    val = clean_value(item.get("Value", "0"))
                    if std in cash_names:
                        cash += abs(val)
                    if std in debt_names:
                        debt += abs(val)
                    if std in interest_names:
                        line_item_interest += abs(val)
                
                # Interest expense from financial summary or line items
                int_val = clean_value(fin_summary.get("Interest Expense", "0"))
                if int_val == 0:
                    int_val = line_item_interest
                
                interest = abs(int_val) * 4  # Annualize quarterly
                
                reported_shares = clean_value(fin_summary.get("Diluted Shares Outstanding", "0"))
                if reported_shares > 0:
                    shares_out = (reported_shares * unit_factor) / adr_ratio
                    print(f"  Using reported shares ({reported_shares} {unit_label}) / ADR ratio {adr_ratio} -> {shares_out:,.0f} pricing shares")
                
                print(f"  Balance sheet data from {doc_file.group(1)}: cash={cash}, debt={debt}, interest_ann={interest}")
    
    if debt == 0:
        print("  Note: No debt found on balance sheet. Company appears debt-free.")

    # 3. WACC Calculation
    rf = 0.042
    erp = 0.05
    tax_stat = 0.25
    
    # Convert debt to same scale as market cap for weight calculation
    debt_abs = debt * unit_factor  # Convert to absolute dollars
    mcap_local = market_cap / fx_rate if fx_rate else market_cap
    
    # Unlever beta using Hamada equation
    d_to_e = debt_abs / mcap_local if mcap_local > 0 else 0
    unlevered_beta = raw_beta / (1 + (1 - tax_stat) * d_to_e)
    
    # Blume's adjustment on Unlevered Beta
    adj_unlevered_beta = (2/3) * unlevered_beta + (1/3) * 1.0
    
    # Re-lever adjusted beta
    adj_beta = adj_unlevered_beta * (1 + (1 - tax_stat) * d_to_e)
    
    cost_equity = rf + adj_beta * erp
    cost_debt = max(0.05, (interest / debt) if debt > 0 else 0.05)
    
    w_e = mcap_local / (mcap_local + debt_abs) if (mcap_local + debt_abs) else 1.0
    w_d = 1.0 - w_e
    wacc_raw = w_e * cost_equity + w_d * cost_debt * (1 - tax_stat) if debt > 0 else cost_equity
    wacc = max(0.06, min(0.15, wacc_raw))
    wacc = max(0.06, min(0.15, wacc_raw))

    # 4. DCF Assumptions
    base_rev = l4q_rev
    base_margin = l4q_ebita / l4q_rev if l4q_rev else 0
    target_growth_yr5 = l4q_growth + growth_magnitude
    target_margin_yr5 = base_margin + margin_magnitude
    terminal_growth = 0.04 if moat == "Wide" else 0.03

    l4q_turnovers = []
    for q in l4q:
        t_val = clean_value(str(q.get("Capital Turnover", "0")).replace('x', ''))
        l4q_turnovers.append(t_val)
    avg_turnover = sum(l4q_turnovers) / len(l4q_turnovers) if l4q_turnovers else 100.0
    
    if avg_turnover < 0 or avg_turnover > 100:
        mct = 100.0
        mct_rationale = f"Defaulted to 100.0x because historical average ({avg_turnover:.1f}x) is negative or >100."
    else:
        if avg_turnover == 0:
            mct = 100.0
            mct_rationale = f"Defaulted to 100.0x because historical average is 0."
        else:
            mct = round(avg_turnover, 1)
            mct_rationale = f"Based on historical L4Q average ({avg_turnover:.1f}x)."

    # 5. Projections
    projections = []
    rev = base_rev
    ic = base_ic
    for yr in range(1, 11):
        if yr <= 5:
            # Interpolated Stage 1
            g = l4q_growth + (target_growth_yr5 - l4q_growth) * (yr/5.0)
            m = base_margin + (target_margin_yr5 - base_margin) * (yr/5.0)
        else:
            # Interpolated Stage 2
            g = target_growth_yr5 + (terminal_growth - target_growth_yr5) * ((yr-5)/5.0)
            m = target_margin_yr5 # Flat margin in Stage 2
        
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
        
        projections.append({
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
            "pv": pv
        })
    
    # Terminal Value
    fcf_10 = projections[-1]["fcf"]
    tv_fcf = fcf_10 * (1 + terminal_growth)
    terminal_val = tv_fcf / (wacc - terminal_growth)
    pv_tv = terminal_val * projections[-1]["df"]
    
    sum_pv_fcf = sum(p["pv"] for p in projections)
    enterprise_val = sum_pv_fcf + pv_tv
    
    # 6. Intrinsic Value (cash and debt already read from balance sheet above)
    equity_val = enterprise_val + cash - debt
    # Convert equity value to absolute dollars, then divide by absolute shares
    equity_val_abs = equity_val * unit_factor  # e.g. thousands * 1000 = dollars
    ivps_local = equity_val_abs / shares_out if shares_out else 0
    ivps = ivps_local * fx_rate

    # 7. Update Metadata.md
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Build sections
    U = unit_suffix  # shorthand
    wacc_section = f"""## WACC

| Field | Value |
|-------|-------|
| Risk-Free Rate | {rf*100:.2f}% |
| Equity Risk Premium | {erp*100:.2f}% |
| Country Risk Premium | 0.00% |
| Raw Levered Beta | {raw_beta:.3f} |
| Unlevered Beta | {unlevered_beta:.4f} |
| Adjusted Beta (Blume's) | {adj_beta:.4f} |
| Cost of Equity | {cost_equity*100:.2f}% |
| Total Debt | ${debt:,.0f}{U} |
| Interest Expense (Ann.) | ${interest:,.0f}{U} |
| Cost of Debt | {cost_debt*100:.2f}% |
| Market Cap | ${market_cap:,} |
| Weight of Equity | {w_e*100:.2f}% |
| Weight of Debt | {w_d*100:.2f}% |
| Tax Rate (Statutory) | {tax_stat*100:.2f}% |
| Calculated WACC | {wacc_raw*100:.2f}% |
| **WACC (Bounded)** | **{wacc*100:.2f}%** |
| Calculation Date | {today} |
"""

    assumptions_section = f"""## DCF Assumptions

| Parameter | Stage 1 (Yr 1-5) | Stage 2 (Yr 6-10) | Terminal |
|-----------|-------------------|--------------------|----------|
| Revenue Growth | {target_growth_yr5*100:.2f}% | {terminal_growth*100:.2f}% | {terminal_growth*100:.2f}% |
| EBITA Margin | {target_margin_yr5*100:.2f}% | {target_margin_yr5*100:.2f}% | {target_margin_yr5*100:.2f}% |
| Marginal Capital Turnover | {mct}x | {mct}x | {mct}x |

| Parameter | Value |
|-----------|-------|
| Adjusted Tax Rate | {l4q_tax*100:.2f}% |
| WACC | {wacc*100:.2f}% |
| Base Revenue (Annualized) | ${base_rev:,.0f}{U} |
| Base Invested Capital | ${base_ic:,.0f}{U} |
| Calculation Date | {today} |

### Assumption Rationale

- **Revenue Growth**: L4Q organic growth averages {l4q_growth*100:.1f}%. Qualitative outlook: {growth_magnitude*100:+.1f} pp, target yr5 {target_growth_yr5*100:.1f}%. {moat} moat supports terminal {terminal_growth*100:.1f}%.
- **EBITA Margin**: L4Q margin {base_margin*100:.1f}%. Qualitative outlook: {margin_magnitude*100:+.1f} pp, target yr5 {target_margin_yr5*100:.1f}%.
- **Capital Turnover**: {mct_rationale}
"""

    # Projections Table
    proj_headers = "| | Base | " + " | ".join([f"Yr {p['year']}" for p in projections]) + " | Terminal |"
    proj_sep = "|---|------|" + "|".join(["---"] * 10) + "|----------|"
    
    rev_row = f"| Revenue | {base_rev:,.0f} | " + " | ".join([f"{p['revenue']:,.0f}" for p in projections]) + f" | {rev*(1+terminal_growth):,.0f} |"
    growth_row = "| Growth | -- | " + " | ".join([f"{p['growth']*100:.2f}%" for p in projections]) + f" | {terminal_growth*100:.2f}% |"
    ebita_row = f"| EBITA | {l4q_ebita:,.0f} | " + " | ".join([f"{p['ebita']:,.0f}" for p in projections]) + f" | {rev*(1+terminal_growth)*target_margin_yr5:,.0f} |"
    nopat_row = f"| NOPAT | {l4q_ebita*(1-l4q_tax):,.0f} | " + " | ".join([f"{p['nopat']:,.0f}" for p in projections]) + f" | {rev*(1+terminal_growth)*target_margin_yr5*(1-l4q_tax):,.0f} |"
    ic_row = f"| Invested Capital | {base_ic:,.0f} | " + " | ".join([f"{p['ic']:,.0f}" for p in projections]) + " | -- |"
    roic_row = f"| ROIC | {base_roic*100:.1f}% | " + " | ".join([f"{p['roic']*100:.1f}%" for p in projections]) + " | -- |"
    fcf_row = "| FCF | -- | " + " | ".join([f"{p['fcf']:,.0f}" for p in projections]) + f" | {tv_fcf:,.0f} |"
    pv_row = "| PV of FCF | -- | " + " | ".join([f"{p['pv']:,.0f}" for p in projections]) + f" | {pv_tv:,.0f} |"

    dcf_section = f"""## DCF Model

### Projections

{proj_headers}
{proj_sep}
{rev_row}
{growth_row}
{ebita_row}
{nopat_row}
{ic_row}
{roic_row}
{fcf_row}
{pv_row}

### Valuation

| Field | Value |
|-------|-------|
| Sum of PV (Years 1-10) | ${sum_pv_fcf:,.0f}{U} |
| PV of Terminal Value | ${pv_tv:,.0f}{U} |
| Terminal Value (undiscounted) | ${terminal_val:,.0f}{U} |
| **Enterprise Value** | **${enterprise_val:,.0f}{U}** |
| TV as % of EV | {pv_tv/enterprise_val*100:.1f}% |
| Calculation Date | {today} |
"""

    intrinsic_section = f"""## Intrinsic Value

| Field | Value |
|-------|-------|
| Enterprise Value | ${enterprise_val:,.0f}{U} |
| (+) Cash and Equivalents | ${cash:,.0f}{U} |
| (-) Total Debt | ${debt:,.0f}{U} |
| **Equity Value** | **${equity_val:,.0f}{U}** |
| Diluted Shares Outstanding | {shares_out / 1e6:.0f}M |
| **Intrinsic Value Per Share** | **${ivps:.2f}** |
| Currency | USD |
| FX Rate Applied | {fx_rate:.4f} |
| ADR Ratio Applied | {adr_ratio:.1f} |
| Current Market Price | ${share_price:.2f} |
| **Upside/Downside** | **{(ivps/share_price - 1)*100:+.1f}%** |
| Calculation Date | {today} |
"""

    # Replacement logic
    new_content = content
    
    def replace_section(full_txt, header, new_txt):
        pattern = re.compile(rf"{header}.*?(?=\n## |$)", re.DOTALL)
        if pattern.search(full_txt):
            return pattern.sub(new_txt.strip() + "\n", full_txt)
        else:
            return full_txt + "\n" + new_txt

    new_content = replace_section(new_content, "## WACC", wacc_section)
    new_content = replace_section(new_content, "## DCF Assumptions", assumptions_section)
    new_content = replace_section(new_content, "## DCF Model", dcf_section)
    new_content = replace_section(new_content, "## Intrinsic Value", intrinsic_section)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    


    print(f"--- Financial Modeling Complete for {ticker} ---")
    print(f"New IVPS: {ivps:.2f} (Upside: {(ivps/share_price - 1)*100:+.1f}%)")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python calculate.py <ticker> <metadata_path>")
        sys.exit(1)
    calculate_modeling(sys.argv[1], sys.argv[2])
