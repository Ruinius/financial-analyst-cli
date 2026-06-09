import os
import re
import csv
import json
import logging
from pathlib import Path
from typing import List
from pydantic import BaseModel

from src.core.config import load_config
from src.services.llm_client import LLMClient
from src.services.web_search import search_investopedia
from src.pipeline.queue import JobQueue
import src.rust_core as rust_core

logger = logging.getLogger(__name__)


class AuditLinkage(BaseModel):
    source_file: str
    chunk_id: int
    exact_snippet: str


class LineItem(BaseModel):
    line_name: str
    value: float
    operating: bool = True
    calculated: bool = False
    category: str = "current_assets"  # current_assets, current_liabilities, noncurrent_assets, noncurrent_liabilities, income_statement, other
    standardized_name: str = ""
    audit: AuditLinkage


class ExtractionResult(BaseModel):
    document_date: str
    document_type: str
    fiscal_quarter: str
    line_items: List[LineItem] = []
    economic_moat: str = "Narrow"
    economic_moat_rationale: str = ""
    margin_outlook: str = "Stable"
    margin_magnitude: str = "0 pp"
    margin_rationale: str = ""
    growth_outlook: str = "Stable"
    growth_magnitude: str = "0 pp"
    growth_rationale: str = ""
    basic_shares: float = 0.0
    diluted_shares: float = 0.0
    simple_growth: float = 0.0
    organic_growth: float = 0.0


def get_chunk_by_id(content: str, chunk_id: int) -> str:
    """Extract chunk content between comments."""
    pattern = (
        rf"<!-- CHUNK_START: {chunk_id} -->\s*(.*?)\s*<!-- CHUNK_END: {chunk_id} -->"
    )
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else ""


def clean_val(val: str) -> float:
    """Clean string number to float."""
    if not val or val.strip() == "N/A" or val.strip() == "--":
        return 0.0
    cleaned = val.replace(",", "").replace("$", "").strip()
    if cleaned.startswith("("):
        cleaned = "-" + cleaned.strip("()")
    try:
        if "%" in cleaned:
            return float(cleaned.replace("%", "")) / 100.0
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


class Extractor:
    def __init__(self):
        self.settings = load_config()
        self.llm = LLMClient()

    def get_extracted_registry_path(self) -> Path:
        workspace = Path(self.settings.active_workspace_path)
        csv_path = workspace / "4_extracted_data" / "extracted_data.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        return csv_path

    def load_extracted_registry(self) -> List[str]:
        csv_path = self.get_extracted_registry_path()
        registry = []
        if csv_path.exists():
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "source_file" in row:
                        registry.append(row["source_file"])
        return registry

    def save_extracted_registry(self, source_file: str) -> None:
        csv_path = self.get_extracted_registry_path()
        file_exists = csv_path.exists()
        with open(csv_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["source_file", "extracted_at"])
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "source_file": source_file,
                    "extracted_at": json.dumps(
                        os.path.getmtime(
                            Path(self.settings.active_workspace_path)
                            / "2_parsed_data"
                            / source_file
                        )
                    ),
                }
            )

    def run_extraction(self) -> None:
        """Scan 2_parsed_data/ and run extraction on unextracted documents sequentially."""
        if not self.settings.active_workspace_path:
            raise ValueError(
                "No active workspace is selected. Use 'fa use <ticker>' first."
            )

        parsed_dir = Path(self.settings.active_workspace_path) / "2_parsed_data"
        if not parsed_dir.exists():
            logger.warning(f"Parsed directory {parsed_dir} does not exist.")
            return

        parsed_files = [
            p
            for p in parsed_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".md" and p.name != "parsed_data.csv"
        ]
        if not parsed_files:
            logger.info("No parsed files found to extract.")
            return

        extracted_registry = self.load_extracted_registry()

        queue = JobQueue(retries=2, initial_delay=1.0)
        for p_file in parsed_files:
            if p_file.name not in extracted_registry:
                queue.add_job(self.extract_single_file, p_file)

        queue.run()

    def classify_line_item(self, line_name: str, category: str) -> bool:
        """Determine if line item is operating (True) or non-operating (False) using dictionary, context, or search."""
        # Standardize term
        std_name = line_name.lower().replace(" ", "_").replace("/", "_")

        # 1. Local Accounting Dictionary check
        dict_path = Path("src/resources/dictionary") / f"{std_name}.md"
        if dict_path.exists():
            try:
                with open(dict_path, "r", encoding="utf-8") as f:
                    content = f.read()
                # Parse "Operating: Yes" or "Operating: No"
                op_match = re.search(
                    r"-\s*\*\*Operating\*\*:\s*(Yes|No)", content, re.IGNORECASE
                )
                if op_match:
                    return op_match.group(1).lower() == "yes"
            except Exception:
                pass

        # 2. Workspace extract_context.md check
        context_path = (
            Path(self.settings.active_workspace_path)
            / "6_company_context"
            / "extract_context.md"
        )
        if context_path.exists():
            try:
                with open(context_path, "r", encoding="utf-8") as f:
                    content = f.read()
                # Simple regex check for custom classification
                rule_match = re.search(
                    rf"-\s*{line_name}\s*:\s*(operating|non-operating)",
                    content,
                    re.IGNORECASE,
                )
                if rule_match:
                    return rule_match.group(1).lower() == "operating"
            except Exception:
                pass

        # 3. Web Search & LLM Judgment fallback
        web_info = search_investopedia(line_name)

        system_prompt = (
            "You are Sir Pennyworth, a sophisticated, precise financial analyst. "
            "Determine if this line item is OPERATING (related to core business operations) "
            "or NON-OPERATING (financial, investments, debt, taxes, extraordinary items). "
            "Return ONLY 'operating' or 'non-operating'."
        )
        prompt = f"""
Line Item: {line_name}
Category: {category}
Investopedia / Web Context:
{web_info}

Is this line item 'operating' or 'non-operating'? Return ONLY one word.
"""
        try:
            resp = (
                self.llm.generate(prompt, system_prompt=system_prompt).strip().lower()
            )
            return "operating" in resp
        except Exception:
            return True  # Default to operating

    def update_extract_context(self, line_item: LineItem) -> None:
        """Append classification to 6_company_context/extract_context.md."""
        context_dir = Path(self.settings.active_workspace_path) / "6_company_context"
        context_dir.mkdir(parents=True, exist_ok=True)
        context_file = context_dir / "extract_context.md"

        op_str = "operating" if line_item.operating else "non-operating"
        line_rule = f"- {line_item.line_name}: {op_str}\n"

        if not context_file.exists():
            header = f"# Extraction Context: {self.settings.active_ticker or 'UNK'}\n\n## Custom Line Item Classifications\n"
            with open(context_file, "w", encoding="utf-8") as f:
                f.write(header + line_rule)
        else:
            with open(context_file, "r", encoding="utf-8") as f:
                existing = f.read()
            if line_item.line_name not in existing:
                with open(context_file, "a", encoding="utf-8") as f:
                    f.write(line_rule)

    def extract_single_file(self, file_path: Path) -> None:
        logger.info(f"Extracting financials from: {file_path.name}")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Read chunk_id=0
        chunk_0 = get_chunk_by_id(content, 0)
        if not chunk_0:
            # Fallback to reading first part of document if chunk_0 is missing
            chunk_0 = content[:4000]

        # Call LLM to select relevant chunks
        system_prompt = (
            "You are Sir Pennyworth, a sophisticated, precise financial analyst. "
            "Inspect the chunk inventory table and select only the chunk IDs (numbers) "
            "that are relevant to Balance Sheets, Income Statements, moat indicators, "
            "revenues, share counts, or press release growth outlooks."
        )
        prompt = f"""
Here is the Chunk Inventory metadata:
\"\"\"
{chunk_0[:4000]}
\"\"\"

Identify the chunk IDs (e.g. [1, 2, 3]) that contain balance sheets, income statements, financial statements, moat indicators, revenue, organic growth, share counts.
Return ONLY a valid JSON list of integers.
"""
        chunk_ids = [1]  # Default fallback
        try:
            resp = self.llm.generate(prompt, system_prompt=system_prompt)
            match = re.search(r"\[\s*\d+.*\]", resp)
            if match:
                chunk_ids = json.loads(match.group(0))
        except Exception as e:
            logger.warning(
                f"Failed to identify relevant chunks: {e}. Fallback to first 3 chunks."
            )
            chunk_ids = [1, 2, 3]

        # Extract data from chunks
        summaries = []
        extracted_line_items = []
        economic_moat = "Narrow"
        moat_rationale = ""
        margin_outlook = "Stable"
        margin_mag = "0 pp"
        margin_rationale = ""
        growth_outlook = "Stable"
        growth_mag = "0 pp"
        growth_rationale = ""
        basic_shares = 0.0
        diluted_shares = 0.0
        simple_growth = 0.0
        organic_growth = 0.0

        for chunk_id in chunk_ids:
            chunk_body = get_chunk_by_id(content, chunk_id)
            if not chunk_body:
                continue

            # Summarize chunk
            summary_sys = "You are Sir Pennyworth. Summarize the following financial chunk in 1-2 concise, precise sentences."
            summary_prompt = f"Summarize Chunk {chunk_id}:\n\n{chunk_body[:3000]}"
            try:
                summary_text = self.llm.generate(
                    summary_prompt, system_prompt=summary_sys
                ).strip()
                summaries.append(f"- **Chunk {chunk_id}**: {summary_text}")
            except Exception:
                summaries.append(f"- **Chunk {chunk_id}**: Parsed and processed.")

            # Extract line items and qualitative metrics
            extract_sys = (
                "You are Sir Pennyworth, a senior financial analyst. "
                "Extract all financial line items (including balance sheet, income statement, "
                "shares outstanding, organic growth, economic moat, margin outlook) from the chunk. "
                "For every line item, record the exact_snippet (exact text match from the chunk) for audit trial. "
                "Ensure you extract standard items: revenue, operating income, cash_and_equivalents, debt, etc."
            )
            extract_prompt = f"""
Chunk {chunk_id} Content:
\"\"\"
{chunk_body}
\"\"\"

Extract all financial statement line items (Line Name, Value, Category (current_assets | current_liabilities | noncurrent_assets | noncurrent_liabilities | income_statement | other), exact_snippet).
Also extract economic moat rating (None | Narrow | Wide) and outlook magnitudes (e.g. +2 pp) if discussed.
Return a valid JSON object matching this structure:
{{
  "line_items": [
     {{
       "line_name": "Cash and cash equivalents",
       "value": "12,345",
       "category": "current_assets",
       "exact_snippet": "Cash and cash equivalents $ 12,345"
     }}
  ],
  "economic_moat": "None | Narrow | Wide",
  "economic_moat_rationale": "...",
  "margin_outlook": "Decreasing | Stable | Increasing",
  "margin_magnitude": "+0 pp",
  "margin_rationale": "...",
  "growth_outlook": "Decelerating | Stable | Accelerating",
  "growth_magnitude": "+0 pp",
  "growth_rationale": "...",
  "basic_shares": "diluted or basic share counts as a string or number",
  "diluted_shares": "diluted share count as string or number",
  "simple_growth": "revenue growth percent as string",
  "organic_growth": "constant currency growth percent as string"
}}
"""
            try:
                ex_resp = self.llm.generate(extract_prompt, system_prompt=extract_sys)
                json_match = re.search(r"\{.*\}", ex_resp, re.DOTALL)
                if json_match:
                    ex_data = json.loads(json_match.group(0))

                    # Process line items
                    for item in ex_data.get("line_items", []):
                        val_float = clean_val(str(item.get("value", "0")))
                        if val_float == 0.0 and str(item.get("value")) not in [
                            "0",
                            "0.0",
                        ]:
                            continue

                        line_item = LineItem(
                            line_name=item.get("line_name"),
                            value=val_float,
                            category=item.get("category", "other"),
                            audit=AuditLinkage(
                                source_file=file_path.name,
                                chunk_id=chunk_id,
                                exact_snippet=item.get("exact_snippet", ""),
                            ),
                        )
                        extracted_line_items.append(line_item)

                    # Update overall metrics if found
                    if ex_data.get("economic_moat") in ["None", "Narrow", "Wide"]:
                        economic_moat = ex_data.get("economic_moat")
                        moat_rationale = ex_data.get("economic_moat_rationale", "")
                    if ex_data.get("margin_outlook") in [
                        "Decreasing",
                        "Stable",
                        "Increasing",
                    ]:
                        margin_outlook = ex_data.get("margin_outlook")
                        margin_mag = ex_data.get("margin_magnitude", "0 pp")
                        margin_rationale = ex_data.get("margin_rationale", "")
                    if ex_data.get("growth_outlook") in [
                        "Decelerating",
                        "Stable",
                        "Accelerating",
                    ]:
                        growth_outlook = ex_data.get("growth_outlook")
                        growth_mag = ex_data.get("growth_magnitude", "0 pp")
                        growth_rationale = ex_data.get("growth_rationale", "")

                    if ex_data.get("basic_shares"):
                        basic_shares = clean_val(str(ex_data.get("basic_shares")))
                    if ex_data.get("diluted_shares"):
                        diluted_shares = clean_val(str(ex_data.get("diluted_shares")))
                    if ex_data.get("simple_growth"):
                        simple_growth = clean_val(str(ex_data.get("simple_growth")))
                    if ex_data.get("organic_growth"):
                        organic_growth = clean_val(str(ex_data.get("organic_growth")))

            except Exception as e:
                logger.error(f"Failed to parse extraction from chunk {chunk_id}: {e}")

        # Classify each line item
        for item in extracted_line_items:
            item.operating = self.classify_line_item(item.line_name, item.category)
            self.update_extract_context(item)

        # Standardize line items to match old legacy engine naming
        # EBITA, Invested Capital calculations
        # Standardized name assignment for calculations
        for item in extracted_line_items:
            name_lower = item.line_name.lower()
            if "revenue" in name_lower or "sales" in name_lower:
                item.standardized_name = "revenue"
            elif (
                "operating_income" in name_lower
                or "operating income" in name_lower
                or "ebit" in name_lower
            ):
                item.standardized_name = "operating_income"
            elif (
                "income before tax" in name_lower or "income_before_taxes" in name_lower
            ):
                item.standardized_name = "income_before_taxes"
            elif (
                "tax provision" in name_lower
                or "income tax provision" in name_lower
                or "tax expense" in name_lower
            ):
                item.standardized_name = "income_tax_provision"
            elif "net income" in name_lower or "net_income" in name_lower:
                item.standardized_name = "net_income"

        # Check time period and multiplier
        time_period = (
            "Q" if "10-Q" in file_path.name or "10Q" in file_path.name else "FY"
        )
        multiplier = 4.0 if time_period == "Q" else 1.0

        # Calculations
        revenue = 0.0
        for item in extracted_line_items:
            if item.standardized_name == "revenue":
                revenue = item.value
                break

        # EBITA
        starting_val = 0.0
        starting_name = "Operating Income"
        for item in extracted_line_items:
            if item.standardized_name == "operating_income":
                starting_val = item.value
                break
        else:
            for item in extracted_line_items:
                if item.standardized_name == "income_before_taxes":
                    starting_val = item.value
                    starting_name = "Income Before Taxes"
                    break

        non_operating_adjustments_sum = 0.0
        for item in extracted_line_items:
            if (
                item.category == "income_statement"
                and not item.operating
                and not item.calculated
            ):
                non_operating_adjustments_sum += -item.value

        ebita, ebita_margin = rust_core.calculate_ebita(
            starting_val, revenue, non_operating_adjustments_sum
        )

        # Invested Capital
        oca = sum(
            item.value
            for item in extracted_line_items
            if item.category == "current_assets" and item.operating
        )
        ocl = sum(
            item.value
            for item in extracted_line_items
            if item.category == "current_liabilities" and item.operating
        )
        onca = sum(
            item.value
            for item in extracted_line_items
            if item.category == "noncurrent_assets" and item.operating
        )
        oncl = sum(
            item.value
            for item in extracted_line_items
            if item.category == "noncurrent_liabilities" and item.operating
        )

        ann_rev = revenue * multiplier
        nwc, nltoa, ic, turnover = rust_core.calculate_invested_capital(
            oca, ocl, onca, oncl, ann_rev
        )

        # Taxes
        income_before_taxes = starting_val
        income_tax_expense = 0.0
        net_income = 0.0
        for item in extracted_line_items:
            if item.standardized_name == "income_before_taxes":
                income_before_taxes = item.value
            elif item.standardized_name == "income_tax_provision":
                income_tax_expense = item.value
            elif item.standardized_name == "net_income":
                net_income = item.value

        total_tax_adj = (
            non_operating_adjustments_sum * 0.25
        )  # Assume standard tax adjustment effect
        effective_rate, adjusted_rate = rust_core.calculate_tax_rates(
            income_before_taxes, income_tax_expense, net_income, total_tax_adj, ebita
        )

        chosen_tax_rate = adjusted_rate if adjusted_rate != 0.0 else effective_rate
        nopat, annualized_nopat, roic = rust_core.calculate_roic(
            ebita, chosen_tax_rate, ic, multiplier
        )

        # Write output file to 4_extracted_data/
        extracted_dir = Path(self.settings.active_workspace_path) / "4_extracted_data"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        out_file_path = extracted_dir / f"{file_path.stem}_extracted.md"

        # Format sections
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
        output_lines.append("\n---\n")

        output_lines.append("## Tax Rates\n")
        output_lines.append("| Field | Value |")
        output_lines.append("|---|---|")
        output_lines.append(f"| Effective Tax Rate | {effective_rate*100:.2f}% |")
        output_lines.append(f"| Adjusted Tax Rate | {adjusted_rate*100:.2f}% |")
        output_lines.append("\n---\n")

        output_lines.append("## Financial Summary\n")
        output_lines.append("| Metric | Value | Notes |")
        output_lines.append("|---|---|---|")
        output_lines.append(f"| **Revenue** | {revenue} | |")
        output_lines.append(f"| **EBITA** | {ebita} | |")
        output_lines.append(f"| **EBITA Margin** | {ebita_margin:.2f}% | |")
        output_lines.append(f"| **NOPAT** | {nopat:.2f} | |")
        output_lines.append(f"| **Invested Capital** | {ic} | |")
        output_lines.append(f"| **Capital Turnover** | {turnover:.2f}x | |")
        output_lines.append(f"| **ROIC** | {roic:.2f}% | |")
        output_lines.append(f"| **Basic Shares Outstanding** | {basic_shares} | |")
        output_lines.append(f"| **Diluted Shares Outstanding** | {diluted_shares} | |")
        output_lines.append(f"| **Simple Revenue Growth** | {simple_growth:.2f}% | |")
        output_lines.append(f"| **Organic Revenue Growth** | {organic_growth:.2f}% | |")
        output_lines.append("\n---\n")

        output_lines.append("### Economic Moat\n")
        output_lines.append(f"Rating: **{economic_moat}**\n")
        output_lines.append(f"Rationale: {moat_rationale}\n")

        output_lines.append("### EBITA Margin Outlook\n")
        output_lines.append(f"Outlook: **{margin_outlook}**\n")
        output_lines.append(f"Magnitude: **{margin_mag}**\n")
        output_lines.append(f"Rationale: {margin_rationale}\n")

        output_lines.append("### Organic Growth Outlook\n")
        output_lines.append(f"Outlook: **{growth_outlook}**\n")
        output_lines.append(f"Magnitude: **{growth_mag}**\n")
        output_lines.append(f"Rationale: {growth_rationale}\n")

        output_lines.append("## Shares Outstanding\n")
        output_lines.append(f"Basic Shares Outstanding: **{basic_shares}**\n")
        output_lines.append(f"Diluted Shares Outstanding: **{diluted_shares}**\n")

        output_lines.append("## Organic Growth\n")
        output_lines.append(f"Simple Growth (%): **{simple_growth}**\n")
        output_lines.append(f"Final Growth (%): **{organic_growth}**\n")

        output_lines.append("\n## Extracted Line Items & Audit Lineage\n")
        output_lines.append(
            "| Line Name | Value | Operating | Category | Source File | Chunk ID | Exact Snippet |"
        )
        output_lines.append("|---|---|---|---|---|---|---|")
        for item in extracted_line_items:
            output_lines.append(
                f"| {item.line_name} | {item.value} | {item.operating} | {item.category} | "
                f"{item.audit.source_file} | {item.audit.chunk_id} | {item.audit.exact_snippet} |"
            )

        with open(out_file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))

        # Save registry
        self.save_extracted_registry(file_path.name)
