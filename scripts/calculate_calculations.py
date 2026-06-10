import sys
import os
import re
from datetime import datetime

sys.path.append(os.path.dirname(__file__))
from markdown_parser import parse_markdown_table, parse_kv_table, clean_value

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _get_revenue(is_items):
    """Extract revenue using strict standardized name matching."""
    for item in is_items:
        std_name = item.get("Standardized Name", "").lower()
        if (std_name == "revenue" and item.get("Calculated", "No") == "No") or (
            std_name == "total_revenue" and item.get("Calculated", "No") == "Yes"
        ):
            return clean_value(item.get("Value", "0"))
    return 0


def _get_time_period(content):
    """Extract time period and annualization multiplier."""
    match = re.search(r"\|\s*Time Period\s*\|\s*(.*?)\s*\|", content)
    time_period = match.group(1).strip() if match else "Q"
    multiplier = 4 if time_period.startswith("Q") else 1
    return time_period, multiplier


def _section_content(content, section_header):
    """Extract the markdown content scoped to a specific ## section."""
    if section_header in content:
        parts = content.split(section_header)
        after_header = parts[1]
        # Look for the next ## header at the start of a line to avoid splitting on ###
        res = re.split(r"\n##\s+", after_header, maxsplit=1)
        return res[0]
    return content


# ---------------------------------------------------------------------------
# Step 1: EBITA
# ---------------------------------------------------------------------------


def calculate_ebita(content, is_items):
    """Calculate EBITA from Income Statement and GAAP Reconciliation data."""
    revenue = _get_revenue(is_items)

    # Get GAAP Reconciliation items if available
    gaap_items = parse_markdown_table(content, "### Reconciliation Items")

    # Starting Point: prefer Operating Income, fall back to Income Before Taxes
    starting_val = 0
    starting_name = "Operating Income"
    for item in is_items:
        if item.get("Standardized Name") == "operating_income":
            starting_val = clean_value(item.get("Value", "0"))
            break
    else:
        for item in is_items:
            if item.get("Standardized Name") == "income_before_taxes":
                starting_val = clean_value(item.get("Value", "0"))
                starting_name = "Income Before Taxes"
                break

    ebita = starting_val
    adjustments_out = []
    adj_id = 1

    # GAAP Adjustments: add back non-operating reconciliation items
    for item in gaap_items:
        if item.get("Operating", "Yes") == "No":
            val = clean_value(item.get("Value", "0"))
            if val != 0:
                ebita += val
                adjustments_out.append(
                    f"| {adj_id} | {item.get('Line Name')} | {val} | GAAP Reconciliation |"
                )
                adj_id += 1

    # IS Non-Operating additions: remove non-operating items above Operating Income
    found_op_inc = False
    for item in is_items:
        if item.get("Standardized Name") in ("operating_income", "income_before_taxes"):
            found_op_inc = True
        if (
            not found_op_inc
            and item.get("Operating", "Yes") == "No"
            and item.get("Calculated", "Yes") == "No"
        ):
            val = clean_value(item.get("Value", "0"))
            if val != 0:
                ebita += -val
                adjustments_out.append(
                    f"| {adj_id} | {item.get('Line Name')} | {-val} | Income Statement |"
                )
                adj_id += 1

    ebita_margin = (ebita / revenue) * 100 if revenue else 0

    # Build output
    date_iso = datetime.now().isoformat()[:10]
    out = "\n\n---\n\n## EBITA\n\n| Field | Value |\n|-------|-------|\n"
    out += f"| Starting Point | {starting_name} |\n"
    out += f"| Starting Value | {starting_val} |\n| EBITA | {ebita} |\n"
    out += (
        f"| EBITA Margin | {ebita_margin:.2f}% |\n| Calculation Date | {date_iso} |\n\n"
    )

    if adjustments_out:
        out += "### Adjustments\n\n| # | Line Name | Value | Source |\n|---|-----------|-------|--------|\n"
        out += "\n".join(adjustments_out) + "\n"

    return out, ebita, ebita_margin


# ---------------------------------------------------------------------------
# Step 2: Invested Capital
# ---------------------------------------------------------------------------


def calculate_invested_capital(content, is_items):
    """Calculate Invested Capital from Balance Sheet data."""
    bs_content = _section_content(content, "## Balance Sheet")
    bs_items = parse_markdown_table(bs_content, "### Line Items")

    revenue = _get_revenue(is_items)
    _, multiplier = _get_time_period(content)
    ann_rev = revenue * multiplier

    oca_items, ocl_items, onca_items, oncl_items = [], [], [], []

    for item in bs_items:
        val = clean_value(item.get("Value", "0"))
        # Skip calculated or non-operating items
        if (
            item.get("Calculated", "No") == "Yes"
            or item.get("Operating", "Yes") == "No"
        ):
            continue

        cat = item.get("Category", "").lower()
        line_name = item.get("Line Name", "")

        if cat == "current_assets":
            oca_items.append((line_name, val))
        elif cat == "current_liabilities":
            ocl_items.append((line_name, val))
        elif cat == "noncurrent_assets":
            onca_items.append((line_name, val))
        elif cat == "noncurrent_liabilities":
            oncl_items.append((line_name, val))

    oca = sum(x[1] for x in oca_items)
    ocl = sum(x[1] for x in ocl_items)
    nwc = oca - ocl

    onca = sum(x[1] for x in onca_items)
    oncl = sum(x[1] for x in oncl_items)
    nltoa = onca - oncl

    ic = nwc + nltoa
    turnover = (ann_rev / ic) if ic != 0 else 0

    date_iso = datetime.now().isoformat()[:10]
    out = "\n\n---\n\n## Invested Capital\n\n| Field | Value |\n|-------|-------|\n"
    out += f"| Net Working Capital | {nwc} |\n"
    out += f"| Net Long-Term Operating Assets | {nltoa} |\n"
    out += f"| Invested Capital | {ic} |\n"
    out += f"| Capital Turnover | {turnover:.2f}x |\n"
    out += f"| Calculation Date | {date_iso} |\n\n"

    def render_breakdown(
        title, title_val, name_assets, arr_assets, name_liab, arr_liab
    ):
        res = f"### {title} Breakdown\n\n| Component | Items | Total |\n|-----------|-------|-------|\n"
        res += (
            f"| {name_assets} | "
            + ", ".join([x[0] for x in arr_assets])
            + f" | {sum([x[1] for x in arr_assets])} |\n"
        )
        res += (
            f"| {name_liab} | "
            + ", ".join([x[0] for x in arr_liab])
            + f" | {sum([x[1] for x in arr_liab])} |\n"
        )
        res += f"| **{title}** | | **{title_val}** |\n\n"
        return res

    out += render_breakdown(
        "Net Working Capital",
        nwc,
        "Operating Current Assets",
        oca_items,
        "Operating Current Liabilities",
        ocl_items,
    )
    out += render_breakdown(
        "Net Long-Term Operating Assets",
        nltoa,
        "Operating Noncurrent Assets",
        onca_items,
        "Operating Noncurrent Liabilities",
        oncl_items,
    )

    return out, nwc, nltoa, ic, turnover


# ---------------------------------------------------------------------------
# Step 3: Tax Rates (depends on EBITA)
# ---------------------------------------------------------------------------


def calculate_tax(content, is_items, ebita):
    """Calculate Effective and Adjusted Tax Rates."""
    # Get EBITA adjustments written in Step 1
    ebita_adjs = parse_markdown_table(content, "### Adjustments")

    income_before_taxes = 0
    income_tax_expense = 0
    net_income = 0
    found_tax = False

    for item in is_items:
        std_name = item.get("Standardized Name", "").lower()
        if std_name == "income_before_taxes":
            income_before_taxes = clean_value(item.get("Value", "0"))
        elif std_name == "income_tax_provision":
            income_tax_expense = clean_value(item.get("Value", "0"))
            found_tax = True
        elif std_name == "net_income":
            net_income = clean_value(item.get("Value", "0"))

    # Effective Tax Rate
    if found_tax and income_before_taxes != 0:
        effective_rate = -(income_tax_expense / income_before_taxes)
    elif income_before_taxes != 0:
        effective_rate = (income_before_taxes - net_income) / income_before_taxes
    else:
        effective_rate = 0.21  # Default 21%

    # Adjusted Tax Rate
    total_tax_adj = 0
    adj_out = []

    for item in ebita_adjs:
        name = item.get("Line Name", "").lower()
        val = clean_value(item.get("Value", "0"))
        source = item.get("Source", "Non-GAAP")

        marginal_rate = 0.25
        if "impairment" in name or "amortization" in name or "equity" in name:
            marginal_rate = 0.0

        tax_effect = val * marginal_rate
        total_tax_adj += tax_effect
        rate_str = f"{int(marginal_rate * 100)}%"
        adj_out.append(
            f"| {len(adj_out) + 1} | {item.get('Line Name')} | {val} | {tax_effect:.2f} | {source} | {rate_str} |"
        )

    adjusted_tax = income_tax_expense + total_tax_adj
    adjusted_rate = -(adjusted_tax / ebita) if ebita != 0 else 0

    date_iso = datetime.now().isoformat()[:10]
    out = "\n\n---\n\n## Tax Rates\n\n| Field | Value |\n|-------|-------|\n"
    out += f"| Income Before Taxes | {income_before_taxes} |\n"
    out += f"| Income Tax Expense | {income_tax_expense} |\n"
    out += f"| Net Income | {net_income} |\n"
    out += f"| Effective Tax Rate | {effective_rate * 100:.2f}% |\n"
    out += f"| Adjusted Tax Rate | {adjusted_rate * 100:.2f}% |\n"
    out += f"| Calculation Date | {date_iso} |\n\n"

    out += "### Adjusted Tax Rate Breakdown\n\n| # | Line Name | Value | Tax Effect | Source | Marginal Rate |\n|---|-----------|-------|------------|--------|---------------|\n"
    if adj_out:
        out += "\n".join(adj_out) + "\n"
    out += f"| | **Reported Tax** | **{income_tax_expense}** | | | |\n"
    out += f"| | **Total Tax Adjustment** | | **{total_tax_adj:.2f}** | | |\n"
    out += f"| | **Adjusted Tax** | **{adjusted_tax:.2f}** | | | |\n"

    return out, effective_rate, adjusted_rate


# ---------------------------------------------------------------------------
# Step 4: Summary Table (depends on all prior)
# ---------------------------------------------------------------------------


def calculate_summary(
    content,
    is_items,
    ebita,
    ebita_margin,
    effective_rate,
    adjusted_rate,
    nwc,
    nltoa,
    ic,
    turnover,
):
    """Compile all calculated metrics into a final summary table."""
    shares_table = parse_kv_table(content, "## Shares Outstanding")
    growth_table = parse_kv_table(content, "## Organic Growth")
    _, multiplier = _get_time_period(content)

    revenue = _get_revenue(is_items)
    interest_expense = 0
    for item in is_items:
        std_name = item.get("Standardized Name", "").lower()
        if std_name in ("interest_expense", "interest_expense_net"):
            interest_expense = abs(clean_value(item.get("Value", "0")))

    # Tax choice
    chosen_tax_rate = adjusted_rate if adjusted_rate != 0 else effective_rate
    tax_label = "Adjusted Tax Rate" if adjusted_rate != 0 else "Effective Tax Rate"

    # Shares
    basic_shares = clean_value(shares_table.get("Basic Shares Outstanding", "0"))
    diluted_shares = clean_value(shares_table.get("Diluted Shares Outstanding", "0"))

    # Growth
    simple_growth = clean_value(growth_table.get("Simple Growth (%)", "0"))
    organic_growth = clean_value(growth_table.get("Final Growth (%)", "0"))

    # NOPAT & ROIC
    nopat = ebita * (1 - chosen_tax_rate)
    annualized_nopat = nopat * multiplier
    roic = (annualized_nopat / ic) if ic != 0 else 0
    roic_pct = roic * 100

    out = "\n\n---\n\n## Financial Summary\n\n| Metric | Value | Notes |\n|--------|-------|-------|\n"
    out += f"| **Revenue** | {revenue} | |\n"
    out += f"| **EBITA** | {ebita} | |\n"
    out += f"| **EBITA Margin** | {ebita_margin:.2f}% | |\n"
    out += f"| **Effective Tax Rate** | {effective_rate * 100:.2f}% | |\n"
    out += f"| **Adjusted Tax Rate** | {adjusted_rate * 100:.2f}% | |\n"
    out += f"| **NOPAT** | {nopat:.2f} | Using {tax_label} |\n"
    out += f"| **Net Working Capital** | {nwc} | |\n"
    out += f"| **Net Long-Term Operating Assets** | {nltoa} | |\n"
    out += f"| **Invested Capital** | {ic} | |\n"
    out += f"| **Capital Turnover** | {turnover:.2f}x | Annualized |\n"
    out += f"| **ROIC** | {roic_pct:.2f}% | Annualized |\n"
    out += f"| **Interest Expense** | {interest_expense} | |\n"
    out += f"| **Basic Shares Outstanding** | {basic_shares} | |\n"
    out += f"| **Diluted Shares Outstanding** | {diluted_shares} | |\n"
    out += f"| **Simple Revenue Growth** | {simple_growth:.2f}% | YoY |\n"
    out += f"| **Organic Revenue Growth** | {organic_growth:.2f}% | Constant currency |\n\n"

    out += "### Calculation Notes\n\n"
    out += "- Computed NOPAT automatically using EBITA x (1 - applicable tax rate)\n"
    out += f"- Annualization multiplier applied to NOPAT for ROIC calculation: {multiplier}x\n"

    return out


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_all(md_path):
    """Execute all financial calculations in dependency order."""
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Idempotency: Remove existing calculation sections if they exist
    original_content = content
    for section in [
        "## EBITA",
        "## Invested Capital",
        "## Tax Rates",
        "## Financial Summary",
    ]:
        if section in content:
            # Strip everything from the section header to the next --- or end of file
            parts = content.split(f"\n\n---\n\n{section}")
            if len(parts) > 1:
                content = parts[0]
            else:
                # If separator format differs, try simple split
                parts = content.split(section)
                content = parts[0]

    if content != original_content:
        # Trim multiple --- if any
        content = re.sub(r"(\n\s*---\s*)+\n*$", "\n\n---\n", content.strip())
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("  [0/4] Existing calculation sections removed for fresh run")

    # Parse Income Statement once
    is_content = _section_content(content, "## Income Statement")
    is_items = parse_markdown_table(is_content, "### Line Items")

    # Step 1: EBITA (independent)
    ebita_out, ebita, ebita_margin = calculate_ebita(content, is_items)
    print(f"  [1/4] EBITA: {ebita}")

    # Step 2: Invested Capital (independent)
    ic_out, nwc, nltoa, ic, turnover = calculate_invested_capital(content, is_items)
    print(f"  [2/4] Invested Capital: {ic}")

    # Append Steps 1 & 2 so Step 3 can read EBITA adjustments from the file
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(ebita_out)
        f.write(ic_out)

    # Re-read content with EBITA/IC sections appended
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Step 3: Tax Rates (depends on EBITA adjustments in file)
    tax_out, effective_rate, adjusted_rate = calculate_tax(content, is_items, ebita)
    print(
        f"  [3/4] Effective Tax Rate: {effective_rate * 100:.2f}%, Adjusted: {adjusted_rate * 100:.2f}%"
    )

    # Step 4: Summary Table (depends on all prior)
    summary_out = calculate_summary(
        content,
        is_items,
        ebita,
        ebita_margin,
        effective_rate,
        adjusted_rate,
        nwc,
        nltoa,
        ic,
        turnover,
    )
    print("  [4/4] Summary Table compiled")

    # Append Steps 3 & 4
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(tax_out)
        f.write(summary_out)

    print(f"Financial calculations complete for {md_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python calculate.py <markdown_file>")
        sys.exit(1)
    run_all(sys.argv[1])
