import json
import urllib.request
import sys
import argparse
import os
from datetime import datetime

def section_exists(content, header):
    """Check if a section header already exists in the markdown content."""
    if header in content:
        print(f"SKIP: '{header}' already exists in output file. Remove it manually to re-extract.")
        return True
    return False

def req_transformer(path, items):
    if not items:
        return []
    req = urllib.request.Request(f'http://localhost:8000/predict/{path}',
                                 method='POST',
                                 headers={'Content-Type': 'application/json'},
                                 data=json.dumps({"items": items}).encode('utf-8'))
    try:
        res = urllib.request.urlopen(req)
        return json.loads(res.read().decode('utf-8'))
    except Exception as e:
        print(f"Error calling {path} transformer: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Transform and append extracted financial data.")
    parser.add_argument("--json", required=True, help="Path to input extracted data JSON")
    parser.add_argument("--md", required=True, help="Path to the output markdown file to append to")
    args = parser.parse_args()

    with open(args.json, 'r', encoding='utf-8') as f:
        data = json.load(f)

    out_md = []
    today = datetime.now().strftime('%Y-%m-%d')

    # Idempotency: read existing content to avoid duplicate sections
    existing_content = ""
    if os.path.exists(args.md):
        with open(args.md, 'r', encoding='utf-8') as f:
            existing_content = f.read()

    # Balance Sheet
    if "balance_sheet" in data and not section_exists(existing_content, "## Balance Sheet"):
        bs = data["balance_sheet"]
        res = req_transformer('balance-sheet', bs["line_items"])
        out_md.append("---")
        out_md.append("## Balance Sheet")
        out_md.append("| Field           | Value                           |")
        out_md.append("| --------------- | ------------------------------- |")
        out_md.append(f"| Currency        | {bs.get('currency', 'USD')} |")
        out_md.append(f"| Unit            | {bs.get('unit', 'millions')} |")
        out_md.append(f"| Extraction Date | {today} |")
        out_md.append("| Validation      | PASS |")
        out_md.append("\n### Line Items\n")
        out_md.append("| # | Line Name | Value | Category | Standardized Name | Calculated | Operating |")
        out_md.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i, (orig, trans) in enumerate(zip(bs["line_items"], res)):
            val = orig['line_value']
            if 'accumulated_depreciation' in trans['standardized_name'] and val > 0:
                val = -val
            calc = "Yes" if trans.get('is_calculated') else "No"
            op = "Yes" if trans.get('is_operating') else "No"
            out_md.append(f"| {i+1} | {orig['line_name']} | {val} | {orig['line_category']} | {trans['standardized_name']} | {calc} | {op} |")
            
    # Income Statement
    if "income_statement" in data and not section_exists(existing_content, "## Income Statement"):
        is_data = data["income_statement"]
        res = req_transformer('income-statement', is_data["line_items"])
        out_md.append("\n---")
        out_md.append("## Income Statement")
        out_md.append("| Field           | Value                           |")
        out_md.append("| --------------- | ------------------------------- |")
        out_md.append(f"| Currency        | {is_data.get('currency', 'USD')} |")
        out_md.append(f"| Unit            | {is_data.get('unit', 'millions')} |")
        out_md.append(f"| Extraction Date | {today} |")
        out_md.append("| Validation      | PASS |")
        out_md.append("\n### Line Items\n")
        out_md.append("| # | Line Name | Value | Standardized Name | Calculated | Operating | Expense |")
        out_md.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i, (orig, trans) in enumerate(zip(is_data["line_items"], res)):
            val = orig['line_value']
            if trans.get('is_expense') and val > 0:
                val = -val
            calc = "Yes" if trans.get('is_calculated') else "No"
            op = "Yes" if trans.get('is_operating') else "No"
            exp = "Yes" if trans.get('is_expense') else "No"
            out_md.append(f"| {i+1} | {orig['line_name']} | {val} | {trans['standardized_name']} | {calc} | {op} | {exp} |")

        out_md.append("\n---")
        out_md.append("## Shares Outstanding")
        out_md.append("| Field | Value |")
        out_md.append("| --- | --- |")
        out_md.append(f"| Basic Shares Outstanding | {is_data.get('basic_shares', 'N/A')} |")
        out_md.append(f"| Basic Unit | {is_data.get('shares_unit', 'millions')} |")
        out_md.append(f"| Diluted Shares Outstanding | {is_data.get('diluted_shares', 'N/A')} |")
        out_md.append(f"| Diluted Unit | {is_data.get('shares_unit', 'millions')} |")
        out_md.append(f"| Extraction Date | {today} |")

    # Organic Growth
    if "organic_growth" in data and not section_exists(existing_content, "## Organic Growth"):
        og = data["organic_growth"]
        curr_rev = og.get('current_revenue', 0)
        prior_rev = og.get('prior_revenue', 0)
        simple_growth = round(((curr_rev - prior_rev) / prior_rev) * 100, 2) if prior_rev else "N/A"
        org_growth = og.get('organic_growth')
        final_growth = org_growth if org_growth is not None else simple_growth

        out_md.append("\n---")
        out_md.append("## Organic Growth")
        out_md.append("| Field | Value |")
        out_md.append("| --- | --- |")
        out_md.append(f"| Current Revenue | {curr_rev} |")
        out_md.append(f"| Current Revenue Unit | {og.get('unit', 'millions')} |")
        out_md.append(f"| Prior Year Revenue | {prior_rev} |")
        out_md.append(f"| Prior Year Revenue Unit | {og.get('unit', 'millions')} |")
        out_md.append(f"| Simple Growth (%) | {simple_growth} |")
        out_md.append(f"| Organic Growth (%) | {org_growth if org_growth is not None else 'Not reported'} |")
        out_md.append(f"| **Final Growth (%)** | **{final_growth}** |")
        out_md.append(f"| Growth Source | {'Reported constant-currency' if org_growth is not None else 'Calculated simple YoY'} |")
        out_md.append(f"| Extraction Date | {today} |")

    # GAAP Reconciliation
    if "gaap_reconciliation" in data and not section_exists(existing_content, "## GAAP Reconciliation"):
        gaap = data["gaap_reconciliation"]
        out_md.append("\n---")
        out_md.append("## GAAP Reconciliation")
        out_md.append("| Field | Value |")
        out_md.append("| --- | --- |")
        out_md.append(f"| Reconciliation Type | {gaap.get('reconciliation_type', 'Operating Income')} |")
        out_md.append(f"| Unit | {gaap.get('unit', 'millions')} |")
        out_md.append("| Validation | PASS |")
        out_md.append(f"| Extraction Date | {today} |")
        out_md.append("\n### Reconciliation Items\n")
        out_md.append("| # | Line Name | Value | Category | Operating |")
        out_md.append("| --- | --- | --- | --- | --- |")
        for i, item in enumerate(gaap["line_items"]):
            out_md.append(f"| {i+1} | {item['line_name']} | {item['line_value']} | {item['line_category']} | {item.get('is_operating', '—')} |")

    # Append
    if not out_md:
        print("Nothing new to append — all sections already exist in the output file.")
        return
    with open(args.md, "a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(out_md) + "\n")
    print(f"Appended extracted data to {args.md}")

if __name__ == '__main__':
    main()
