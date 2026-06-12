import re
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
from src.pipeline.extractor_agents.extractor_financials_agents.ebita_tax_agent import (
    run_ebita_and_tax_agent,
)
from src.pipeline.extractor_agents.extractor_financials_agents.agent_runner import (
    parse_markdown_to_line_items,
)

logger = logging.getLogger(__name__)


def extract_financial_statements(
    file_path: Path,
    content: str,
    sorted_chunk_ids: list,
    extractor,
    summaries: list,
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
    )

    # Balance Sheet Agent
    run_balance_sheet_agent(
        file_path=file_path,
        content=content,
        sorted_chunk_ids=sorted_chunk_ids,
        extractor=extractor,
        target_output_path=bs_path,
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
    extractor,
    summaries: list,
    income_statement_content: str = "",
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
    revenue = 0.0
    for item in extracted_line_items:
        n = item.line_name.lower()
        if "revenue" in n or "sales" in n:
            revenue = item.value
            break

    # EBITA & Taxes via Agent
    op_inc, inc_bt, rep_tax, ebita, adj_taxes, ebita_adjustments, tax_adjustments = (
        run_ebita_and_tax_agent(
            content,
            extracted_line_items,
            extractor,
            income_statement_content=income_statement_content,
        )
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
    income_before_taxes = inc_bt
    income_tax_expense = rep_tax

    # Compute effective rate using standard formula
    effective_rate = (
        -(income_tax_expense / income_before_taxes)
        if income_before_taxes != 0.0
        else 0.21
    )
    adjusted_rate = -(adj_taxes / ebita) if ebita != 0.0 else 0.0

    chosen_tax_rate = adjusted_rate if adjusted_rate != 0.0 else effective_rate
    nopat, annualized_nopat, roic = pipeline_math.calculate_roic(
        ebita, chosen_tax_rate, ic, multiplier
    )

    # Format output
    output_lines = []
    output_lines.append(f"# Extracted Financial Report: {file_path.name}\n")
    output_lines.append("## Chunk Summaries\n")
    output_lines.extend(summaries)
    output_lines.append("\n---\n")

    output_lines.append("## EBITA\n")
    output_lines.append("| Field | Value |")
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
    output_lines.append("| Field | Value |")
    output_lines.append("|---|---|")
    output_lines.append(f"| Net Working Capital | {nwc} |")
    output_lines.append(f"| Net Long-Term Operating Assets | {nltoa} |")
    output_lines.append(f"| Invested Capital | {ic} |")
    output_lines.append(f"| Capital Turnover | {turnover:.2f}x |")

    output_lines.append("\n### Invested Capital Components Breakdown\n")
    output_lines.append("#### Operating Current Assets (OCA)\n")
    output_lines.append("| Line Item | Value |")
    output_lines.append("|---|---|")
    for item in oca_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total OCA** | **{oca}** |")

    output_lines.append("\n#### Operating Current Liabilities (OCL)\n")
    output_lines.append("| Line Item | Value |")
    output_lines.append("|---|---|")
    for item in ocl_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total OCL** | **{ocl}** |")

    output_lines.append(
        f"\n**Net Working Capital (NWC) = OCA - OCL = {oca} - {ocl} = {nwc}**\n"
    )

    output_lines.append("#### Operating Non-Current Assets (ONCA)\n")
    output_lines.append("| Line Item | Value |")
    output_lines.append("|---|---|")
    for item in onca_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total ONCA** | **{onca}** |")

    output_lines.append("\n#### Operating Non-Current Liabilities (ONCL)\n")
    output_lines.append("| Line Item | Value |")
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
        output_lines.append("| Line Item | Value |")
        output_lines.append("|---|---|")
        for item in non_operating_assets:
            output_lines.append(f"| {item.line_name} | {item.value} |")
    else:
        output_lines.append("None detected\n")

    output_lines.append("\n#### Non-Operating Liabilities\n")
    if non_operating_liabilities:
        output_lines.append("| Line Item | Value |")
        output_lines.append("|---|---|")
        for item in non_operating_liabilities:
            output_lines.append(f"| {item.line_name} | {item.value} |")
    else:
        output_lines.append("None detected\n")

    output_lines.append("\n---\n")
    output_lines.append("## Tax Rates\n")
    output_lines.append("| Component | Value | Description |")
    output_lines.append("|---|---|---|")
    output_lines.append(
        f"| Income Before Taxes | {income_before_taxes} | Starting Point for Effective Tax Rate |"
    )
    output_lines.append(f"| Reported Tax Provision | {income_tax_expense} | |")
    output_lines.append(
        f"| **Effective Tax Rate** | **{effective_rate * 100:.2f}%** | -(Reported Tax Provision / Income Before Taxes) |"
    )
    output_lines.append(f"| EBITA | {ebita} | Starting Point for Adjusted Tax Rate |")
    output_lines.append(f"| Reported Tax Provision | {income_tax_expense} | |")
    for adj in tax_adjustments:
        name = adj.get("name", "Adjustment")
        val = adj.get("value", 0.0)
        sign = "+" if val >= 0 else ""
        output_lines.append(f"| {name} | {sign}{val} | |")
    output_lines.append(f"| **Adjusted Taxes** | **{adj_taxes}** | |")
    output_lines.append(
        f"| **Adjusted Tax Rate** | **{adjusted_rate * 100:.2f}%** | -(Adjusted Taxes / EBITA) |"
    )
    output_lines.append("\n---\n")

    output_lines.append("## Financial Summary\n")
    output_lines.append("| Metric | Value | Notes |")
    output_lines.append("|---|---|---|")
    output_lines.append(f"| **Revenue** | {revenue} | |")
    output_lines.append(f"| **EBITA** | {ebita} | |")
    output_lines.append(f"| **EBITA Margin** | {ebita_margin:.2f}% | |")
    output_lines.append(f"| **Adjusted Taxes** | **{adj_taxes}** | |")
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


def extract_financials(
    file_path: Path,
    content: str,
    chunk_ids: list,
    extractor,
    summaries: list,
) -> bool:
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

    # Phase 1: Extract complete balance sheet and income statement
    extracted_line_items = extract_financial_statements(
        file_path=file_path,
        content=content,
        sorted_chunk_ids=sorted_chunk_ids,
        extractor=extractor,
        summaries=summaries,
    )

    # Phase 2: Financial Statement Interpretation Agent
    extracted_line_items = run_interpretation_agent(
        extracted_line_items=extracted_line_items,
        file_path=file_path,
        extractor=extractor,
    )

    # Read the extracted income statement content if available
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    is_path = extracted_dir / f"{file_path.stem}_income_statement.md"
    income_statement_content = ""
    if is_path.exists():
        income_statement_content = is_path.read_text(encoding="utf-8")

    # Find revenue to supply to organic growth agent
    revenue = 0.0
    for item in extracted_line_items:
        n = item.line_name.lower()
        if "revenue" in n or "sales" in n:
            revenue = item.value
            break

    # Phase 3: Diluted Shares and Organic Growth Agents
    basic_shares, diluted_shares = run_diluted_shares_agent(
        content, extractor, income_statement_content=income_statement_content
    )
    simple_growth, organic_growth = run_organic_growth_agent(
        content, revenue, extractor, income_statement_content=income_statement_content
    )

    # Phase 4: Deterministic calculations
    success = calculate_deterministic_metrics(
        file_path=file_path,
        content=content,
        extracted_line_items=extracted_line_items,
        basic_shares=basic_shares,
        diluted_shares=diluted_shares,
        simple_growth=simple_growth,
        organic_growth=organic_growth,
        extractor=extractor,
        summaries=summaries,
        income_statement_content=income_statement_content,
    )

    return success
