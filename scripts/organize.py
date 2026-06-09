"""
Document Organization Script (Phase 4)

Deterministic Python script that:
  1. Reads the processed markdown to extract classification + financial summary
  2. Harmonizes units across sections (automated conversion)
  3. Creates/updates the company metadata file
  4. Moves files from processing_data/ → output_data/TICKER/ (removing _temp suffix)
  5. Cleans up the original PDF from input_data/

Usage:
    python skills/document_organization/scripts/organize.py <markdown_file>

Example:
    python skills/document_organization/scripts/organize.py processing_data/ADBE_EA_20250312_temp.md
"""

import sys
import os
import re
import shutil
import glob
from datetime import datetime

sys.path.append(os.path.dirname(__file__))
from markdown_parser import parse_markdown_table, parse_kv_table, clean_value

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UNIT_FACTORS = {
    "ones":             1,
    "thousands":        1_000,
    "ten_thousands":    10_000,
    "millions":         1_000_000,
    "hundred_millions": 100_000_000,
    "billions":         1_000_000_000,
}

# Aliases for fuzzy matching
UNIT_ALIASES = {
    "万":               "ten_thousands",
    "億":               "hundred_millions",
    "thousand":         "thousands",
    "million":          "millions",
    "billion":          "billions",
}


# ---------------------------------------------------------------------------
# Unit Helpers
# ---------------------------------------------------------------------------

def normalize_unit_name(raw_unit: str) -> str:
    """Map a raw unit string to our canonical unit key."""
    raw = raw_unit.strip().lower()
    if raw in UNIT_FACTORS:
        return raw
    if raw in UNIT_ALIASES:
        return UNIT_ALIASES[raw]
    # Try partial match
    for alias, canonical in UNIT_ALIASES.items():
        if alias in raw:
            return canonical
    return raw  # return as-is; caller can check validity


def convert_value(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a numeric value between two units."""
    from_canonical = normalize_unit_name(from_unit)
    to_canonical = normalize_unit_name(to_unit)
    if from_canonical == to_canonical:
        return value
    from_factor = UNIT_FACTORS.get(from_canonical)
    to_factor = UNIT_FACTORS.get(to_canonical)
    if from_factor is None or to_factor is None:
        raise ValueError(f"Unknown unit conversion: '{from_unit}' -> '{to_unit}'")
    # Convert to ones, then to target
    value_in_ones = value * from_factor
    return value_in_ones / to_factor


# ---------------------------------------------------------------------------
# Section Helpers
# ---------------------------------------------------------------------------

def _section_content(content, section_header):
    """Extract the markdown content scoped to a specific ## section."""
    if section_header in content:
        parts = content.split(section_header)
        after_header = parts[1]
        res = re.split(r'\n##\s+', after_header, maxsplit=1)
        return res[0]
    return ""


def _get_section_unit(content, section_name):
    """Get the 'Unit' field from a section's KV header."""
    section_text = _section_content(content, f"## {section_name}")
    if not section_text:
        return None
    match = re.search(r'\|\s*Unit\s*\|\s*(\S+)\s*\|', section_text)
    return match.group(1).strip() if match else None


def _get_prevailing_unit(content):
    """Determine prevailing unit from BS and IS sections."""
    bs_unit = _get_section_unit(content, "Balance Sheet")
    is_unit = _get_section_unit(content, "Income Statement")

    if bs_unit and is_unit:
        if normalize_unit_name(bs_unit) == normalize_unit_name(is_unit):
            return normalize_unit_name(bs_unit)
        # Disagree: take BS as default
        print(f"  [WARN] BS unit ({bs_unit}) differs from IS unit ({is_unit}). Using BS unit.")
        return normalize_unit_name(bs_unit)
    return normalize_unit_name(bs_unit or is_unit or "millions")


# ---------------------------------------------------------------------------
# Step 1: Read classification metadata
# ---------------------------------------------------------------------------

def read_classification(content):
    """Extract classification metadata from the markdown.
    
    Note: The classification section uses a single '# ' header, which the
    shared markdown_parser doesn't handle (it only detects ## and ###).
    We parse it directly with regex here.
    """
    meta = {}
    # Find the classification section (between "# Document Classification" and the next ---)
    cls_match = re.search(r'# Document Classification\s*\n(.*?)(?:\n---|\n#\s)', content, re.DOTALL)
    if cls_match:
        section = cls_match.group(1)
        # Parse KV rows: | Key | Value |
        for row_match in re.finditer(r'\|\s*(.+?)\s*\|\s*(.+?)\s*\|', section):
            key = row_match.group(1).strip()
            val = row_match.group(2).strip()
            if key and val and "---" not in key and "Field" not in key:
                meta[key] = val

    return {
        "ticker":        meta.get("Ticker", ""),
        "company_name":  meta.get("Company Name", ""),
        "document_type": meta.get("Document Type", ""),
        "document_date": meta.get("Document Date", ""),
        "time_period":   meta.get("Time Period", ""),
        "period_end_date": meta.get("Period End Date", ""),
        "currency":      meta.get("Currency", "USD"),
    }


# ---------------------------------------------------------------------------
# Step 2: Harmonize units
# ---------------------------------------------------------------------------

def harmonize_units(content):
    """
    Check units across sections and harmonize Shares Outstanding 
    to the prevailing unit. Returns (updated_content, prevailing_unit, notes).
    """
    prevailing = _get_prevailing_unit(content)
    notes = []

    # Check Shares Outstanding
    shares_section = _section_content(content, "## Shares Outstanding")
    if shares_section:
        basic_unit_match = re.search(r'\|\s*Basic Unit\s*\|\s*(\S+)\s*\|', shares_section)
        diluted_unit_match = re.search(r'\|\s*Diluted Unit\s*\|\s*(\S+)\s*\|', shares_section)

        basic_unit = basic_unit_match.group(1).strip() if basic_unit_match else prevailing
        diluted_unit = diluted_unit_match.group(1).strip() if diluted_unit_match else prevailing

        conversions_needed = False

        if normalize_unit_name(basic_unit) != prevailing:
            # Convert basic shares
            basic_match = re.search(r'\|\s*Basic Shares Outstanding\s*\|\s*(\S+)\s*\|', shares_section)
            if basic_match:
                old_val = clean_value(basic_match.group(1))
                new_val = convert_value(old_val, basic_unit, prevailing)
                note = f"Shares (basic): {old_val} {basic_unit} → {new_val:.1f} {prevailing}"
                notes.append(note)
                print(f"  [UPDATE] {note}")
                # Replace in content
                content = content.replace(
                    f"| Basic Shares Outstanding   | {basic_match.group(1).strip()}",
                    f"| Basic Shares Outstanding   | {new_val:.1f}"
                )
                content = content.replace(
                    f"| Basic Unit                 | {basic_unit}",
                    f"| Basic Unit                 | {prevailing}"
                )
                conversions_needed = True

        if normalize_unit_name(diluted_unit) != prevailing:
            diluted_match = re.search(r'\|\s*Diluted Shares Outstanding\s*\|\s*(\S+)\s*\|', shares_section)
            if diluted_match:
                old_val = clean_value(diluted_match.group(1))
                new_val = convert_value(old_val, diluted_unit, prevailing)
                note = f"Shares (diluted): {old_val} {diluted_unit} → {new_val:.1f} {prevailing}"
                notes.append(note)
                print(f"  [UPDATE] {note}")
                content = content.replace(
                    f"| Diluted Shares Outstanding | {diluted_match.group(1).strip()}",
                    f"| Diluted Shares Outstanding | {new_val:.1f}"
                )
                content = content.replace(
                    f"| Diluted Unit               | {diluted_unit}",
                    f"| Diluted Unit               | {prevailing}"
                )
                conversions_needed = True

        if not conversions_needed:
            print(f"  [OK] All units already match prevailing unit: {prevailing}")

    # Check Organic Growth prior-year revenue unit
    growth_section = _section_content(content, "## Organic Growth")
    if growth_section:
        prior_unit_match = re.search(r'\|\s*Prior Year Revenue Unit\s*\|\s*(\S+)\s*\|', growth_section)
        curr_unit_match = re.search(r'\|\s*Current Revenue Unit\s*\|\s*(\S+)\s*\|', growth_section)
        if prior_unit_match and normalize_unit_name(prior_unit_match.group(1).strip()) != prevailing:
            notes.append(f"⚠️ Prior Year Revenue unit ({prior_unit_match.group(1).strip()}) differs from prevailing ({prevailing})")
        if curr_unit_match and normalize_unit_name(curr_unit_match.group(1).strip()) != prevailing:
            notes.append(f"⚠️ Current Revenue unit ({curr_unit_match.group(1).strip()}) differs from prevailing ({prevailing})")

    # Insert prevailing unit note at top if not already there
    if "| Prevailing Unit |" not in content:
        # Insert after the classification table's ---
        content = content.replace(
            "\n---\n\n## <!-- Sections below",
            f"\n\n| Prevailing Unit | {prevailing} |\n\n---\n\n## <!-- Sections below"
        )

    return content, prevailing, notes


# ---------------------------------------------------------------------------
# Step 3: Read Financial Summary for metadata
# ---------------------------------------------------------------------------

def read_financial_summary(content):
    """Extract key financial metrics from the Financial Summary table."""
    raw_summary = parse_kv_table(content, "## Financial Summary")
    
    # Strip bold markers from keys (e.g., **Revenue** -> Revenue)
    summary = {}
    for k, v in raw_summary.items():
        clean_key = k.replace("**", "").strip()
        summary[clean_key] = v
    
    def safe_clean(key, strip_pct=False):
        """Get a value, handling bold markers and percent signs."""
        val = summary.get(key, "0")
        # Remove bold markers from value too
        val = val.replace("**", "").strip()
        if strip_pct:
            val = val.replace("%", "").strip()
            try:
                return float(val)
            except ValueError:
                return 0.0
        return clean_value(val)

    return {
        "revenue":          safe_clean("Revenue"),
        "ebita":            safe_clean("EBITA"),
        "ebita_margin":     summary.get("EBITA Margin", "0").replace("**", "").strip(),
        "adj_tax_rate":     summary.get("Adjusted Tax Rate", "0").replace("**", "").strip(),
        "nopat":            safe_clean("NOPAT"),
        "invested_capital": safe_clean("Invested Capital"),
        "capital_turnover": summary.get("Capital Turnover", "0").replace("**", "").strip(),
        "roic":             summary.get("ROIC", "0").replace("**", "").strip(),
        "organic_growth":   summary.get("Organic Revenue Growth", "0").replace("**", "").strip(),
    }


# ---------------------------------------------------------------------------
# Step 4: Create / Update metadata
# ---------------------------------------------------------------------------

def _format_number(val):
    """Format a number with comma separators for metadata display."""
    if isinstance(val, str):
        try:
            val = float(val.replace(",", "").replace("%", ""))
        except ValueError:
            return val
    if val == int(val):
        return f"{int(val):,}"
    return f"{val:,.1f}"


def create_metadata(ticker, company_name, currency, unit, cls_meta, fin_summary, today_iso):
    """Create a brand new metadata file content."""
    doc_type_display = cls_meta["document_type"]
    fname = f"{ticker}_{_doctype_abbrev(doc_type_display)}_{cls_meta['document_date'].replace('-', '')}"

    lines = []
    lines.append(f"# {company_name} ({ticker})")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Ticker | {ticker} |")
    lines.append(f"| Company Name | {company_name} |")
    lines.append(f"| Currency | {currency} |")
    lines.append(f"| Unit | {unit} |")
    lines.append(f"| Last Updated | {today_iso} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Processed Documents")
    lines.append("")
    lines.append("| # | File | Document Type | Time Period | Period End Date | Document Date | Processed |")
    lines.append("|---|------|--------------|-------------|-----------------|---------------|-----------|")
    lines.append(f"| 1 | [{fname}.md]({fname}.md) | {doc_type_display} | {cls_meta['time_period']} | {cls_meta['period_end_date']} | {cls_meta['document_date']} | {today_iso} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Financial History")
    lines.append("")
    lines.append("| Time Period | Period End | Revenue | EBITA | EBITA Margin | Adj Tax Rate | NOPAT | Invested Capital | Capital Turnover | ROIC | Organic Growth |")
    lines.append("|-------------|-----------|---------|-------|--------------|-------------|-------|-----------------|------------------|------|----------------|")
    lines.append(f"| {cls_meta['time_period']} | {cls_meta['period_end_date']} | {_format_number(fin_summary['revenue'])} | {_format_number(fin_summary['ebita'])} | {fin_summary['ebita_margin']} | {fin_summary['adj_tax_rate']} | {_format_number(fin_summary['nopat'])} | {_format_number(fin_summary['invested_capital'])} | {fin_summary['capital_turnover']} | {fin_summary['roic']} | {fin_summary['organic_growth']} |")
    lines.append("")

    return "\n".join(lines)


def update_metadata(existing_content, ticker, cls_meta, fin_summary, today_iso):
    """Update an existing metadata file with a new document entry."""
    lines = existing_content.split("\n")

    # Update Last Updated
    for i, line in enumerate(lines):
        if "| Last Updated |" in line:
            lines[i] = f"| Last Updated | {today_iso} |"
            break

    doc_type_display = cls_meta["document_type"]
    fname = f"{ticker}_{_doctype_abbrev(doc_type_display)}_{cls_meta['document_date'].replace('-', '')}"

    # --- Update Processed Documents table ---
    doc_table_start = None
    doc_table_end = None
    doc_rows = []

    for i, line in enumerate(lines):
        if "## Processed Documents" in line:
            doc_table_start = i
        if doc_table_start is not None and i > doc_table_start + 3 and (not line.strip() or line.strip() == "---"):
            doc_table_end = i
            break

    if doc_table_start is not None:
        # Parse existing rows
        for i in range(doc_table_start, doc_table_end or len(lines)):
            if lines[i].startswith("| ") and "---" not in lines[i] and "#" not in lines[i].split("|")[1]:
                doc_rows.append(lines[i])

        # Check for duplicate time_period (re-processing)
        new_row_time = cls_meta["time_period"]
        filtered = []
        for row in doc_rows:
            cols = [c.strip() for c in row.split("|")]
            # cols[4] is Time Period
            if len(cols) > 4 and cols[4] == new_row_time and cls_meta["document_type"] in cols[3]:
                print(f"  [UPDATE] Replacing existing row for {new_row_time}")
                continue
            filtered.append(row)

        # Add new row
        row_num = len(filtered) + 1
        new_doc_row = f"| {row_num} | [{fname}.md]({fname}.md) | {doc_type_display} | {cls_meta['time_period']} | {cls_meta['period_end_date']} | {cls_meta['document_date']} | {today_iso} |"
        filtered.append(new_doc_row)

        # Sort by Period End Date (col index 5)
        def sort_key(row):
            cols = [c.strip() for c in row.split("|")]
            date_str = cols[5] if len(cols) > 5 else ""
            if date_str == "—" or not date_str:
                return "9999-99-99"  # sort analyst reports etc to the end
            return date_str

        filtered.sort(key=sort_key)

        # Re-number
        renumbered = []
        for idx, row in enumerate(filtered, 1):
            cols = [c.strip() for c in row.split("|")]
            cols[1] = f" {idx} "
            renumbered.append("|".join(cols))

        # Rebuild section
        header_lines = []
        for i in range(doc_table_start, len(lines)):
            header_lines.append(lines[i])
            if "|---" in lines[i]:
                break

        rebuild = header_lines + renumbered
        lines = lines[:doc_table_start] + rebuild + lines[doc_table_end:]

    # --- Update Financial History table ---
    fin_table_start = None
    fin_table_end = None
    fin_rows = []

    # Re-scan after content may have shifted
    for i, line in enumerate(lines):
        if "## Financial History" in line:
            fin_table_start = i
        if fin_table_start is not None and i > fin_table_start + 3 and (not line.strip() or line.strip() == "---"):
            fin_table_end = i
            break

    if fin_table_start is not None:
        for i in range(fin_table_start, fin_table_end or len(lines)):
            if lines[i].startswith("| ") and "---" not in lines[i] and "Time Period" not in lines[i]:
                fin_rows.append(lines[i])

        # Check for duplicate time_period
        new_tp = cls_meta["time_period"]
        filtered_fin = []
        for row in fin_rows:
            cols = [c.strip() for c in row.split("|")]
            if len(cols) > 1 and cols[1] == new_tp:
                print(f"  [UPDATE] Replacing existing financial history for {new_tp}")
                continue
            filtered_fin.append(row)

        new_fin_row = f"| {cls_meta['time_period']} | {cls_meta['period_end_date']} | {_format_number(fin_summary['revenue'])} | {_format_number(fin_summary['ebita'])} | {fin_summary['ebita_margin']} | {fin_summary['adj_tax_rate']} | {_format_number(fin_summary['nopat'])} | {_format_number(fin_summary['invested_capital'])} | {fin_summary['capital_turnover']} | {fin_summary['roic']} | {fin_summary['organic_growth']} |"
        filtered_fin.append(new_fin_row)

        # Sort by Period End (col index 2)
        def fin_sort_key(row):
            cols = [c.strip() for c in row.split("|")]
            return cols[2] if len(cols) > 2 else ""

        filtered_fin.sort(key=fin_sort_key)

        header_lines = []
        for i in range(fin_table_start, len(lines)):
            header_lines.append(lines[i])
            if "|---" in lines[i]:
                break

        rebuild = header_lines + filtered_fin
        lines = lines[:fin_table_start] + rebuild + (lines[fin_table_end:] if fin_table_end else [])

    return "\n".join(lines)


def _doctype_abbrev(doc_type):
    """Map document_type to filename abbreviation."""
    mapping = {
        "earnings_announcement": "EA",
        "quarterly_filing":     "10Q",
        "annual_filing":        "10K",
        "analyst_report":       "AR",
        "transcript":           "TR",
        "press_release":        "PR",
    }
    return mapping.get(doc_type, "DOC")


# ---------------------------------------------------------------------------
# Step 5: File operations (move + cleanup)
# ---------------------------------------------------------------------------

def move_files(md_path, ticker, project_root):
    """
    Move .md and .pdf from processing_data/ to output_data/TICKER/,
    removing the _temp suffix. Also delete matching source PDF from input_data/.
    """
    processing_dir = os.path.join(project_root, "processing_data")
    output_dir = os.path.join(project_root, "output_data", ticker)
    input_dir = os.path.join(project_root, "input_data")

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    md_basename = os.path.basename(md_path)
    pdf_basename = md_basename.replace(".md", ".pdf")

    # Remove _temp suffix for destination
    final_md = md_basename.replace("_temp", "")
    final_pdf = pdf_basename.replace("_temp", "")

    src_md = os.path.join(processing_dir, md_basename)
    src_pdf = os.path.join(processing_dir, pdf_basename)
    dst_md = os.path.join(output_dir, final_md)
    dst_pdf = os.path.join(output_dir, final_pdf)

    moved = []

    # Move markdown
    if os.path.exists(src_md):
        shutil.move(src_md, dst_md)
        moved.append(f"  [FILE] {md_basename} -> output_data/{ticker}/{final_md}")
    else:
        print(f"  [WARN] Source markdown not found: {src_md}")

    # Move PDF
    if os.path.exists(src_pdf):
        shutil.move(src_pdf, dst_pdf)
        moved.append(f"  [FILE] {pdf_basename} -> output_data/{ticker}/{final_pdf}")
    else:
        print(f"  [WARN] Source PDF not found: {src_pdf}")

    # Cleanup: delete matching PDF from input_data/
    input_pdf_pattern = os.path.join(input_dir, f"{final_pdf.replace('.pdf', '')}*")
    input_matches = glob.glob(input_pdf_pattern)
    # Also check for the original filename from classification
    original_pattern = os.path.join(input_dir, f"{final_pdf}")
    if os.path.exists(original_pattern):
        input_matches.append(original_pattern)

    cleaned = set()
    for match in input_matches:
        if os.path.exists(match) and match not in cleaned:
            os.remove(match)
            cleaned.add(match)
            moved.append(f"  [DELETE] Cleaned up input_data/{os.path.basename(match)}")

    if not cleaned:
        print(f"  [INFO] No matching files found in input_data/ to clean up")

    return moved


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify(ticker, md_basename, project_root):
    """Verify files were moved correctly."""
    output_dir = os.path.join(project_root, "output_data", ticker)
    processing_dir = os.path.join(project_root, "processing_data")

    final_md = md_basename.replace("_temp", "")
    final_pdf = md_basename.replace("_temp", "").replace(".md", ".pdf")

    checks = []

    # Check destination exists
    dst_md = os.path.join(output_dir, final_md)
    dst_pdf = os.path.join(output_dir, final_pdf)
    meta = os.path.join(output_dir, f"{ticker}_metadata.md")

    checks.append(("Destination MD", os.path.exists(dst_md)))
    checks.append(("Destination PDF", os.path.exists(dst_pdf)))
    checks.append(("Metadata file", os.path.exists(meta)))

    # Check source removed
    src_md = os.path.join(processing_dir, md_basename)
    src_pdf = os.path.join(processing_dir, md_basename.replace(".md", ".pdf"))
    checks.append(("Source MD removed", not os.path.exists(src_md)))
    checks.append(("Source PDF removed", not os.path.exists(src_pdf)))

    all_pass = all(v for _, v in checks)
    for name, status in checks:
        icon = "[OK]" if status else "[FAIL]"
        print(f"  {icon} {name}")

    return all_pass


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run(md_path):
    """Execute the full document organization pipeline."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    today_iso = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"  Document Organization — {os.path.basename(md_path)}")
    print(f"{'='*60}\n")

    # Read source document
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Step 1: Read classification
    cls_meta = read_classification(content)
    ticker = cls_meta["ticker"]
    company_name = cls_meta["company_name"]
    currency = cls_meta["currency"]
    print(f"  [1/5] Classification: {ticker} | {cls_meta['time_period']} | {cls_meta['document_type']}")

    # Step 2: Harmonize units
    content, prevailing_unit, unit_notes = harmonize_units(content)
    print(f"  [2/5] Unit harmonization complete (prevailing: {prevailing_unit})")

    # Write harmonized content back
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Step 3: Read financial summary
    fin_summary = read_financial_summary(content)
    print(f"  [3/5] Financial summary: Rev={_format_number(fin_summary['revenue'])}, "
          f"EBITA={_format_number(fin_summary['ebita'])}, "
          f"Growth={fin_summary['organic_growth']}")

    # Step 4: Create/update metadata
    output_dir = os.path.join(project_root, "output_data", ticker)
    os.makedirs(output_dir, exist_ok=True)
    meta_path = os.path.join(output_dir, f"{ticker}_metadata.md")

    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            existing_meta = f.read()
        updated_meta = update_metadata(existing_meta, ticker, cls_meta, fin_summary, today_iso)
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(updated_meta)
        print(f"  [4/5] Metadata updated: {meta_path}")
    else:
        new_meta = create_metadata(ticker, company_name, currency, prevailing_unit, cls_meta, fin_summary, today_iso)
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(new_meta)
        print(f"  [4/5] Metadata created: {meta_path}")

    # Step 5: Move files + cleanup input_data
    file_ops = move_files(md_path, ticker, project_root)
    for op in file_ops:
        print(op)
    print(f"  [5/5] File operations complete")

    # Verification
    print(f"\n  --- Verification ---")
    md_basename = os.path.basename(md_path)
    all_pass = verify(ticker, md_basename, project_root)

    # Final report
    final_name = md_basename.replace("_temp", "")
    print(f"\n{'='*60}")
    if all_pass:
        print(f"  [OK] Document organized:")
        print(f"     {final_name} -> output_data/{ticker}/")
        doc_count = sum(1 for f in os.listdir(output_dir) if f.endswith(".md") and "metadata" not in f)
        print(f"     Metadata updated: {doc_count} document(s) for {ticker}")
        if unit_notes:
            for note in unit_notes:
                print(f"     Unit: {note}")
        else:
            print(f"     Unit harmonization: No conversions needed")
    else:
        print(f"  [FAIL] Organization completed with errors — check output above")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python organize.py <markdown_file>")
        print("Example: python skills/document_organization/scripts/organize.py processing_data/ADBE_EA_20250312_temp.md")
        sys.exit(1)
    run(sys.argv[1])
