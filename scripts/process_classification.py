import argparse
import json
import os
import shutil
import sys
from datetime import datetime

# Adjust sys.path to import market_data from the same scripts/ folder
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.dirname(__file__))
from market_data import validate_ticker

def main():
    parser = argparse.ArgumentParser(description="Process document classification and orchestration.")
    parser.add_argument("--filename", required=True)
    parser.add_argument("--company_name", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--document_type", required=True)
    parser.add_argument("--document_date", required=True)
    parser.add_argument("--time_period", required=True)
    parser.add_argument("--period_end_date", required=True)
    parser.add_argument("--confidence", required=True)
    
    args = parser.parse_args()
    
    resources_file = os.path.join(os.path.dirname(__file__), 'document_types.json')
    
    with open(resources_file, 'r', encoding='utf-8') as f:
        doc_rules = json.load(f)
        
    # 1. Validation and Ticker
    val_result = validate_ticker(args.ticker)
    if not val_result["valid"]:
        print(f"Error: Ticker {args.ticker} is invalid according to Yahoo Finance. {val_result.get('error')}", file=sys.stderr)
        sys.exit(1)
        
    final_company = val_result["company_name"]
    final_ticker = val_result["ticker"]
    
    # 2. Document type and abbreviation
    doc_types = doc_rules.get("document_types", {})
    if args.document_type not in doc_types:
        print(f"Error: Unknown document type {args.document_type}. Valid types: {list(doc_types.keys())}", file=sys.stderr)
        sys.exit(1)
    abbrev = doc_types[args.document_type]["abbreviation"]
    
    final_time_period = args.time_period
    # 3. Post-Process Rules
    if args.document_type == "earnings_announcement" and final_time_period.startswith("FY"):
        final_time_period = final_time_period.replace("FY", "Q4")
    elif args.document_type == "annual_filing" and final_time_period.startswith("Q4"):
        final_time_period = final_time_period.replace("Q4", "FY")
        
    # 4. Construct Paths
    input_path = os.path.join(base_dir, 'input_data', args.filename)
    if not os.path.exists(input_path):
        # We might have already moved it if restarting, check processing_data
        processing_path_orig = os.path.join(base_dir, 'processing_data', args.filename)
        if not os.path.exists(processing_path_orig):
            print(f"Error: Could not find {args.filename} in input_data/", file=sys.stderr)
            sys.exit(1)
        input_path = processing_path_orig

    date_str = args.document_date.replace("-", "")
    new_base = f"{final_ticker}_{abbrev}_{date_str}_temp"
    
    out_pdf = os.path.join(base_dir, 'processing_data', f"{new_base}.pdf")
    out_md = os.path.join(base_dir, 'processing_data', f"{new_base}.md")
    
    # 5. Move / Rename PDF
    shutil.copy2(input_path, out_pdf)
    if input_path != out_pdf:
        try:
            os.remove(input_path)
        except OSError:
            pass # Maybe it was never there or already deleted
            
    # 6. Write Markdown
    md_content = f"""# Document Classification

| Field               | Value               |
| ------------------- | ------------------- |
| Company Name        | {final_company}     |
| Ticker              | {final_ticker}      |
| Document Type       | {args.document_type} |
| Document Date       | {args.document_date} |
| Time Period         | {final_time_period} |
| Period End Date     | {args.period_end_date} |
| Confidence          | {args.confidence}   |
| Original Filename   | {args.filename}     |
| Classification Date | {datetime.now().strftime("%Y-%m-%d")} |

---

<!-- Sections below will be populated by subsequent skills -->
"""
    with open(out_md, 'w', encoding='utf-8') as f:
        f.write(md_content)
        
    print(f"Successfully processed {args.filename} into {new_base}.pdf/.md")

if __name__ == "__main__":
    main()
