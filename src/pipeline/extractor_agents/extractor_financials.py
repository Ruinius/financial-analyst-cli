from src.utils.tools import extract_json_from_text
import re
import json
import logging
from pathlib import Path
import src.utils.math as pipeline_math


# Import specialized agents to run or expose them
from src.pipeline.extractor_agents.extractor_financials_agents.income_statement_agent import (
    run_income_statement_agent,
)
from src.pipeline.extractor_agents.extractor_financials_agents.balance_sheet_agent import (
    run_balance_sheet_agent,
)
from src.pipeline.extractor_agents.extractor_financials_agents.interpretation_agent import (
    run_interpretation_agent,
)
from src.pipeline.extractor_agents.extractor_financials_agents.diluted_shares_agent import (
    run_diluted_shares_agent,
)
from src.pipeline.extractor_agents.extractor_financials_agents.organic_growth_agent import (
    run_organic_growth_agent,
)
from src.pipeline.extractor_agents.extractor_financials_agents.ebita_agent import (
    run_ebita_agent,
)
from src.pipeline.extractor_agents.extractor_financials_agents.tax_agent import (
    run_tax_agent,
)

logger = logging.getLogger(__name__)


def parse_markdown_to_line_items(
    file_path: Path,
    target_statement_path: Path,
    extractor,
    category_default: str,
) -> list:
    from src.pipeline.extractor_orchestrator import LineItem, AuditLinkage, clean_val

    if not target_statement_path.exists():
        return []

    content = target_statement_path.read_text(encoding="utf-8")

    dict_guidance = ""
    if category_default == "income_statement":
        is_dict = extractor.get_dictionary("income_statement")
        if is_dict:
            dict_guidance = f"\n\nUse the following Income Statement Dictionary as a guide for classifications and expense/revenue sign mapping:\n{is_dict}\n"

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. "
        "Extract all financial statement line items from the provided markdown statement. "
        "For every line item, record the exact_snippet (exact text match from the markdown statement) for audit trial. "
        "Ensure you extract standard items: revenue, operating income, cash_and_equivalents, debt, etc."
    )
    if category_default == "income_statement":
        sys_prompt += (
            "\n\nStandardize positive/negative signs for the Income Statement:\n"
            "- Any number that subtracts from the revenue is an expense, cost, or loss, and MUST be expressed as a negative number.\n"
            "- Any number that effectively increases profit (e.g. revenue, interest income, tax benefits, gains) MUST be expressed as a positive number.\n"
            "- If an item is an expense but listed as a positive number in the source markdown, you MUST convert it to a negative number.\n"
            "- Be careful with ambiguous items like 'Net Interest Income' or 'Other Income/Expense Net'. Check their context: if they represent a net expense or loss, express them as negative. If they represent net income or gain, express them as positive."
        )

    prompt = f"""
Markdown statement content:
\"\"\"
{content}
\"\"\"
{dict_guidance}
Extract all financial statement line items (Line Name, Value, Category (current_assets | current_liabilities | noncurrent_assets | noncurrent_liabilities | income_statement | other), exact_snippet).
Return a valid JSON object matching this structure:
{{
  "line_items": [
     {{
       "line_name": "Cash and cash equivalents",
       "value": "12,345",
       "category": "{category_default}",
       "exact_snippet": "Cash and cash equivalents $ 12,345"
     }}
  ]
}}
"""
    extracted_items = []
    try:
        resp = extractor.llm.generate(
            prompt, system_prompt=sys_prompt, stream_thinking=True
        )
        json_str = extract_json_from_text(resp)
        if json_str:
            data = json.loads(json_str)
            for item in data.get("line_items", []):
                val_float = clean_val(str(item.get("value", "0")))
                if val_float == 0.0 and str(item.get("value")) not in ["0", "0.0"]:
                    continue
                line_item = LineItem(
                    line_name=item.get("line_name"),
                    value=val_float,
                    category=item.get("category", "other"),
                    audit=AuditLinkage(
                        source_file=file_path.name,
                        chunk_id=0,  # Consolidated from agent-derived markdown
                        exact_snippet=item.get("exact_snippet", ""),
                    ),
                )
                extracted_items.append(line_item)
    except Exception as e:
        logger.error(
            f"Failed to parse line items from markdown statement {target_statement_path.name}: {e}"
        )

    return extracted_items


def extract_financial_statements(
    file_path: Path,
    content: str,
    sorted_chunk_ids: list,
    extractor,
    summaries: list,
    is_quarterly: bool = True,
) -> list:
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    extracted_dir.mkdir(parents=True, exist_ok=True)

    is_path = extracted_dir / f"{file_path.stem}_income_statement.md"
    bs_path = extracted_dir / f"{file_path.stem}_balance_sheet.md"

    # Income Statement Agent
    run_income_statement_agent(
        file_path=file_path,
        content=content,
        sorted_chunk_ids=sorted_chunk_ids,
        extractor=extractor,
        target_output_path=is_path,
        is_quarterly=is_quarterly,
    )

    # Balance Sheet Agent
    run_balance_sheet_agent(
        file_path=file_path,
        content=content,
        sorted_chunk_ids=sorted_chunk_ids,
        extractor=extractor,
        target_output_path=bs_path,
        is_quarterly=is_quarterly,
    )

    # Parse and consolidate line items
    is_items = parse_markdown_to_line_items(
        file_path, is_path, extractor, "income_statement"
    )
    bs_items = parse_markdown_to_line_items(
        file_path, bs_path, extractor, "current_assets"
    )

    # Add summaries update
    summaries.append(
        f"- **Agentic Extraction Completed**: Income Statement generated at `{is_path.name}`, Balance Sheet generated at `{bs_path.name}`."
    )

    return is_items + bs_items


def calculate_deterministic_metrics(
    file_path: Path,
    content: str,
    extracted_line_items: list,
    basic_shares: float,
    diluted_shares: float,
    simple_growth: float,
    organic_growth: float,
    op_inc: float,
    inc_bt: float,
    rep_tax: float,
    ebita: float,
    adj_taxes: float,
    ebita_adjustments: list,
    tax_adjustments: list,
    extractor,
    summaries: list,
    revenue: float = 0.0,
    currency: str = "USD",
    unit: str = "Millions",
) -> bool:
    # Check time period and multiplier
    metadata = extractor.get_document_metadata(file_path.name)
    doc_type = metadata.get("document_type", "")
    if not doc_type:
        from src.pipeline.extractor_orchestrator import get_chunk_by_id

        chunk_0 = get_chunk_by_id(content, 0) or content[:4000]
        meta_match = re.search(r"\|\s*Document Type\s*\|\s*([^|]+?)\s*\|", chunk_0)
        if meta_match:
            doc_type = meta_match.group(1).strip()

    is_quarterly = (
        "10-Q" in file_path.name
        or "10Q" in file_path.name
        or "earnings_announcement" in file_path.name
        or doc_type == "quarterly_filing"
        or doc_type == "earnings_announcement"
    )
    time_period = "Q" if is_quarterly else "FY"
    multiplier = 4.0 if time_period == "Q" else 1.0

    # Calculations
    if revenue <= 0.0:
        raise ValueError(
            "Revenue must be greater than 0.0 and extracted correctly by the agent."
        )

    ebita_margin = (ebita / revenue) * 100.0 if revenue > 0.0 else 0.0

    starting_val = op_inc
    starting_name = "Operating Income"

    # Invested Capital
    oca_items = [
        item
        for item in extracted_line_items
        if item.category == "current_assets" and item.operating
    ]
    ocl_items = [
        item
        for item in extracted_line_items
        if item.category == "current_liabilities" and item.operating
    ]
    onca_items = [
        item
        for item in extracted_line_items
        if item.category == "noncurrent_assets" and item.operating
    ]
    oncl_items = [
        item
        for item in extracted_line_items
        if item.category == "noncurrent_liabilities" and item.operating
    ]

    non_operating_assets = [
        item
        for item in extracted_line_items
        if item.category
        in ("current_assets", "current_asset", "noncurrent_assets", "noncurrent_asset")
        and not item.operating
        and not item.calculated
    ]
    non_operating_liabilities = [
        item
        for item in extracted_line_items
        if item.category
        in (
            "current_liabilities",
            "current_liability",
            "noncurrent_liabilities",
            "noncurrent_liability",
        )
        and not item.operating
        and not item.calculated
    ]

    oca = sum(item.value for item in oca_items)
    ocl = sum(item.value for item in ocl_items)
    onca = sum(item.value for item in onca_items)
    oncl = sum(item.value for item in oncl_items)

    ann_rev = revenue * multiplier
    nwc, nltoa, ic, turnover = pipeline_math.calculate_invested_capital(
        oca, ocl, onca, oncl, ann_rev
    )

    # Taxes
    total_tax_adj = adj_taxes - rep_tax

    effective_rate, adjusted_rate = pipeline_math.calculate_tax_rates(
        inc_bt, rep_tax, total_tax_adj, ebita
    )

    chosen_tax_rate = adjusted_rate if adjusted_rate != 0.0 else effective_rate

    nopat, annualized_nopat, roic = pipeline_math.calculate_roic(
        ebita, chosen_tax_rate, ic, multiplier
    )

    # Format output
    output_lines = []
    output_lines.append(f"# Extracted Financial Report: {file_path.name}\n")
    output_lines.append(f"**Currency**: {currency}\n")
    output_lines.append(f"**Unit**: {unit}\n\n")
    output_lines.append("## Chunk Summaries\n")
    output_lines.extend(summaries)
    output_lines.append("\n---\n")

    output_lines.append("## EBITA\n")
    output_lines.append(f"| Field | Value (in {unit}) |")
    output_lines.append("|---|---|")
    output_lines.append(f"| Starting Point | {starting_name} |")
    output_lines.append(f"| Starting Value | {starting_val} |")
    for adj in ebita_adjustments:
        name = adj.get("name", "Adjustment")
        val = adj.get("value", 0.0)
        sign = "+" if val >= 0 else ""
        output_lines.append(f"| {name} | {sign}{val} |")
    output_lines.append(f"| EBITA | {ebita} |")
    output_lines.append(f"| EBITA Margin | {ebita_margin:.2f}% |")
    output_lines.append("\n---\n")

    output_lines.append("## Invested Capital\n")
    output_lines.append(f"| Field | Value (in {unit}) |")
    output_lines.append("|---|---|")
    output_lines.append(f"| Net Working Capital | {nwc} |")
    output_lines.append(f"| Net Long-Term Operating Assets | {nltoa} |")
    output_lines.append(f"| Invested Capital | {ic} |")
    output_lines.append(f"| Capital Turnover | {turnover:.2f}x |")

    output_lines.append("\n### Invested Capital Components Breakdown\n")
    output_lines.append("#### Operating Current Assets (OCA)\n")
    output_lines.append(f"| Line Item | Value (in {unit}) |")
    output_lines.append("|---|---|")
    for item in oca_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total OCA** | **{oca}** |")

    output_lines.append("\n#### Operating Current Liabilities (OCL)\n")
    output_lines.append(f"| Line Item | Value (in {unit}) |")
    output_lines.append("|---|---|")
    for item in ocl_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total OCL** | **{ocl}** |")

    output_lines.append(
        f"\n**Net Working Capital (NWC) = OCA - OCL = {oca} - {ocl} = {nwc}**\n"
    )

    output_lines.append("#### Operating Non-Current Assets (ONCA)\n")
    output_lines.append(f"| Line Item | Value (in {unit}) |")
    output_lines.append("|---|---|")
    for item in onca_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total ONCA** | **{onca}** |")

    output_lines.append("\n#### Operating Non-Current Liabilities (ONCL)\n")
    output_lines.append(f"| Line Item | Value (in {unit}) |")
    output_lines.append("|---|---|")
    for item in oncl_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total ONCL** | **{oncl}** |")

    output_lines.append(
        f"\n**Net Long-Term Operating Assets (NLTOA) = ONCA - ONCL = {onca} - {oncl} = {nltoa}**"
    )
    output_lines.append(
        f"\n**Invested Capital = NWC + NLTOA = {nwc} + {nltoa} = {ic}**"
    )
    output_lines.append("\n---\n")

    output_lines.append("#### Non-Operating Assets\n")
    if non_operating_assets:
        output_lines.append(f"| Line Item | Value (in {unit}) |")
        output_lines.append("|---|---|")
        for item in non_operating_assets:
            output_lines.append(f"| {item.line_name} | {item.value} |")
    else:
        output_lines.append("None detected\n")

    output_lines.append("\n#### Non-Operating Liabilities\n")
    if non_operating_liabilities:
        output_lines.append(f"| Line Item | Value (in {unit}) |")
        output_lines.append("|---|---|")
        for item in non_operating_liabilities:
            output_lines.append(f"| {item.line_name} | {item.value} |")
    else:
        output_lines.append("None detected\n")

    output_lines.append("\n---\n")
    output_lines.append("## Tax Rates\n")
    output_lines.append(f"| Component | Value (in {unit}) | Description |")
    output_lines.append("|---|---|---|")
    output_lines.append(
        f"| Income Before Taxes | {inc_bt} | Starting Point for Effective Tax Rate |"
    )
    output_lines.append(f"| Reported Tax Provision | {rep_tax} | |")
    output_lines.append(
        f"| **Effective Tax Rate** | **{effective_rate * 100:.2f}%** | (Reported Tax Provision / Income Before Taxes) |"
    )
    for adj in tax_adjustments:
        name = adj.get("name", "Adjustment")
        val = adj.get("value", 0.0)
        sign = "+" if val >= 0 else ""
        output_lines.append(f"| {name} | {sign}{val} | |")
    output_lines.append(f"| **Adjusted Taxes** | **{adj_taxes}** | |")
    output_lines.append(
        f"| **Adjusted Tax Rate** | **{adjusted_rate * 100:.2f}%** | (Adjusted Taxes / EBITA) |"
    )
    output_lines.append("\n---\n")

    output_lines.append("## Financial Summary\n")
    output_lines.append(f"| Metric | Value (in {unit}) | Notes |")
    output_lines.append("|---|---|---|")
    output_lines.append(f"| **Revenue** | {revenue} | |")
    output_lines.append(f"| **EBITA** | {ebita} | |")
    output_lines.append(f"| **EBITA Margin** | {ebita_margin:.2f}% | |")
    output_lines.append(f"| **Adjusted Tax Rate** | **{adjusted_rate * 100:.2f}%** | |")
    output_lines.append(f"| **NOPAT** | {nopat:.2f} | |")
    output_lines.append(f"| **Invested Capital** | {ic} | |")
    output_lines.append(f"| **Capital Turnover** | {turnover:.2f}x | |")
    output_lines.append(f"| **ROIC** | {roic:.2f}% | |")
    output_lines.append(f"| **Basic Shares Outstanding** | {basic_shares} | |")
    output_lines.append(f"| **Diluted Shares Outstanding** | {diluted_shares} | |")
    output_lines.append(f"| **Simple Revenue Growth** | {simple_growth * 100:.2f}% | |")
    output_lines.append(
        f"| **Organic Revenue Growth** | {organic_growth * 100:.2f}% | |"
    )

    # Write output file to 4_extracted_data/
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    out_file_path = extracted_dir / f"{file_path.stem}_extracted.md"

    with open(out_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    import src.utils.formatting as formatting

    formatting.print_success(f"Extracted: {file_path.name} -> {out_file_path.name}")
    return True


def detect_metadata_from_markdown(file_path: Path) -> tuple[str, str]:
    currency = "USD"
    unit = "Millions"
    if not file_path.exists():
        return currency, unit
    try:
        text = file_path.read_text(encoding="utf-8")
        curr_match = re.search(r"\*\*Currency\*\*:\s*([A-Za-z]{3})", text)
        if curr_match:
            currency = curr_match.group(1).upper()
        else:
            curr_match_loose = re.search(r"Currency:\s*([A-Za-z]{3})", text)
            if curr_match_loose:
                currency = curr_match_loose.group(1).upper()

        unit_match = re.search(r"\*\*Unit\*\*:\s*([A-Za-z0-9\s]+)", text)
        if unit_match:
            unit = unit_match.group(1).strip()
        else:
            unit_match_loose = re.search(r"Unit:\s*([A-Za-z0-9\s]+)", text)
            if unit_match_loose:
                unit = unit_match_loose.group(1).strip()
    except Exception:
        pass
    return currency, unit


def extract_financials(
    file_path: Path,
    content: str,
    chunk_ids: list,
    extractor,
) -> bool:
    summaries = []
    from src.pipeline.extractor_orchestrator import get_chunk_by_id

    # 1. Rank order the chunks by number frequency
    chunk_frequencies = []
    for cid in chunk_ids:
        body = get_chunk_by_id(content, cid)
        if body:
            num_digits = sum(1 for c in body if c.isdigit())
            frequency = num_digits
        else:
            frequency = 0
        chunk_frequencies.append((cid, frequency))
    chunk_frequencies.sort(key=lambda x: x[1], reverse=True)
    sorted_chunk_ids = [x[0] for x in chunk_frequencies]

    # Determine if filing is quarterly or annual
    metadata = extractor.get_document_metadata(file_path.name)
    doc_type = metadata.get("document_type", "")
    if not doc_type:
        chunk_0 = get_chunk_by_id(content, 0) or content[:4000]
        meta_match = re.search(r"\|\s*Document Type\s*\|\s*([^|]+?)\s*\|", chunk_0)
        if meta_match:
            doc_type = meta_match.group(1).strip()

    is_quarterly = (
        "10-Q" in file_path.name
        or "10Q" in file_path.name
        or "earnings_announcement" in file_path.name
        or doc_type == "quarterly_filing"
        or doc_type == "earnings_announcement"
    )

    # Phase 1: Extract complete balance sheet and income statement
    extracted_line_items = extract_financial_statements(
        file_path=file_path,
        content=content,
        sorted_chunk_ids=sorted_chunk_ids,
        extractor=extractor,
        summaries=summaries,
        is_quarterly=is_quarterly,
    )

    # Phase 2: Financial Statement Interpretation Agent
    extracted_line_items = run_interpretation_agent(
        extracted_line_items=extracted_line_items,
        file_path=file_path,
        extractor=extractor,
        is_quarterly=is_quarterly,
    )

    # Read the extracted income statement content if available
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    is_path = extracted_dir / f"{file_path.stem}_income_statement.md"
    income_statement_content = ""
    if is_path.exists():
        income_statement_content = is_path.read_text(encoding="utf-8")

    # Phase 3: Diluted Shares, Organic Growth, EBITA, and Adjusted Tax Agents
    basic_shares, diluted_shares = run_diluted_shares_agent(
        content,
        extractor,
        income_statement_content=income_statement_content,
        is_quarterly=is_quarterly,
    )

    simple_growth, organic_growth, revenue = run_organic_growth_agent(
        content,
        extractor,
        income_statement_content=income_statement_content,
        is_quarterly=is_quarterly,
    )
    op_inc, ebita, ebita_adjustments = run_ebita_agent(
        content,
        extractor,
        income_statement_content=income_statement_content,
        is_quarterly=is_quarterly,
    )

    inc_bt, rep_tax, adj_taxes, tax_adjustments = run_tax_agent(
        content,
        extractor,
        operating_income=op_inc,
        operating_ebita=ebita,
        ebita_adjustments=ebita_adjustments,
        income_statement_content=income_statement_content,
        is_quarterly=is_quarterly,
    )

    # Phase 4: Deterministic calculations
    bs_path = extracted_dir / f"{file_path.stem}_balance_sheet.md"
    detected_currency, detected_unit = detect_metadata_from_markdown(is_path)
    if detected_currency == "USD" and bs_path.exists():
        bs_curr, bs_unit = detect_metadata_from_markdown(bs_path)
        if bs_curr != "USD":
            detected_currency = bs_curr
            detected_unit = bs_unit

    success = calculate_deterministic_metrics(
        file_path=file_path,
        content=content,
        extracted_line_items=extracted_line_items,
        basic_shares=basic_shares,
        diluted_shares=diluted_shares,
        simple_growth=simple_growth,
        organic_growth=organic_growth,
        op_inc=op_inc,
        inc_bt=inc_bt,
        rep_tax=rep_tax,
        ebita=ebita,
        adj_taxes=adj_taxes,
        ebita_adjustments=ebita_adjustments,
        tax_adjustments=tax_adjustments,
        extractor=extractor,
        summaries=summaries,
        revenue=revenue,
        currency=detected_currency,
        unit=detected_unit,
    )

    return success
