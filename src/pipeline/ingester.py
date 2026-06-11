import csv
import datetime
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple
from bs4 import BeautifulSoup, NavigableString

from src.core.config import load_config
from src.services.llm_client import LLMClient
from src.pipeline.queue import JobQueue

logger = logging.getLogger(__name__)


def compute_sha256(file_path: Path) -> str:
    """Compute the SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def html_to_markdown(html_content: str) -> str:
    """Convert HTML content to alignment-preserving markdown, focusing on table structure."""
    soup = BeautifulSoup(html_content, "html.parser")

    # Strip script, style, head, and meta tags
    for tag in soup(["script", "style", "head", "meta"]):
        tag.decompose()

    def convert_element(element) -> str:
        if isinstance(element, NavigableString):
            return element.text

        tag_name = element.name
        if not tag_name:
            return ""

        # Headings
        if tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            level = int(tag_name[1])
            content = "".join(
                convert_element(child) for child in element.children
            ).strip()
            return f"\n\n{'#' * level} {content}\n\n"

        # Paragraphs / Blocks
        if tag_name in ["p", "div"]:
            content = "".join(
                convert_element(child) for child in element.children
            ).strip()
            return f"\n\n{content}\n\n"

        # Line Breaks
        if tag_name == "br":
            return "\n"

        # Emphasis
        if tag_name in ["b", "strong"]:
            content = "".join(convert_element(child) for child in element.children)
            return f"**{content}**"
        if tag_name in ["i", "em"]:
            content = "".join(convert_element(child) for child in element.children)
            return f"*{content}*"

        # Tables
        if tag_name == "table":
            rows = element.find_all("tr")
            if not rows:
                return ""

            markdown_rows = []
            max_cols = 0

            # First pass: parse cell strings and track max columns
            for r in rows:
                cells = r.find_all(["td", "th"])
                cell_texts = []
                for c in cells:
                    # Strip inner newlines and excessive whitespace for table alignment
                    txt = " ".join(c.get_text().split())
                    cell_texts.append(txt)
                if len(cell_texts) > max_cols:
                    max_cols = len(cell_texts)
                markdown_rows.append(cell_texts)

            if max_cols == 0:
                return ""

            # Ensure all rows have equal columns
            for r_idx in range(len(markdown_rows)):
                while len(markdown_rows[r_idx]) < max_cols:
                    markdown_rows[r_idx].append("")

            # Build table markdown
            table_lines = []
            # Header Row
            header_row = markdown_rows[0]
            table_lines.append("| " + " | ".join(header_row) + " |")
            # Separator Row
            table_lines.append("| " + " | ".join(["---"] * max_cols) + " |")
            # Data Rows
            for data_row in markdown_rows[1:]:
                table_lines.append("| " + " | ".join(data_row) + " |")

            return "\n\n" + "\n".join(table_lines) + "\n\n"

        # Fallback recursive extraction
        return "".join(convert_element(child) for child in element.children)

    raw_markdown = convert_element(soup)
    # Clean up double spacing and blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", raw_markdown)
    return cleaned.strip()


def chunk_text(text: str, max_chars: int = 5000) -> List[str]:
    """Split text into chunks of at most max_chars, trying to split on newlines."""
    chunks = []
    current_chunk = []
    current_len = 0
    lines = text.split("\n")

    for line in lines:
        if len(line) > max_chars:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0
            for i in range(0, len(line), max_chars):
                chunks.append(line[i : i + max_chars])
        else:
            if current_len + len(line) + (1 if current_chunk else 0) > max_chars:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = len(line)
            else:
                current_chunk.append(line)
                current_len += len(line) + (1 if len(current_chunk) > 1 else 0)

    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks


class Ingester:
    def __init__(self):
        self.settings = load_config()
        self.llm = LLMClient()

    def get_parsed_registry_path(self) -> Path:
        workspace = Path(self.settings.active_workspace_path)
        csv_path = workspace / "2_parsed_data" / "parsed_data.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        return csv_path

    def load_parsed_registry(self) -> Dict[str, Dict[str, str]]:
        csv_path = self.get_parsed_registry_path()
        registry = {}
        if csv_path.exists():
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "file_hash" in row:
                        if "period_end_date" not in row:
                            row["period_end_date"] = "N/A"
                        registry[row["file_hash"]] = row
        return registry

    def save_parsed_registry(self, registry: Dict[str, Dict[str, str]]) -> None:
        csv_path = self.get_parsed_registry_path()
        fieldnames = [
            "file_hash",
            "original_filename",
            "new_filename",
            "document_type",
            "document_date",
            "fiscal_quarter",
            "period_end_date",
        ]
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in registry.values():
                clean_row = {fn: row.get(fn, "N/A") for fn in fieldnames}
                clean_row["file_hash"] = row.get("file_hash", "")
                writer.writerow(clean_row)

    def identify_metadata(
        self, first_chunk: str, original_filename: str
    ) -> Tuple[str, str, str, str]:
        """Use LLM to identify document_date, document_type, fiscal_quarter, and period_end_date."""
        # Load document types spec
        doc_types_path = Path("scripts/document_types.json")
        doc_types_str = ""
        if doc_types_path.exists():
            with open(doc_types_path, "r", encoding="utf-8") as f:
                doc_types_str = f.read()

        context_path = (
            Path(self.settings.active_workspace_path)
            / "6_company_context"
            / "ingest_context.md"
        )
        context_str = ""
        if context_path.exists():
            with open(context_path, "r", encoding="utf-8") as f:
                context_str = f.read()

        system_prompt = (
            "You are Sir Pennyworth, a sophisticated, precise financial analyst. "
            "Your task is to identify key metadata of a company report from its text. "
            "You MUST return ONLY a JSON object with the keys:\n"
            "- 'document_date' (YYYY-MM-DD): The date the document was filed, published, or released.\n"
            "- 'period_end_date' (YYYY-MM-DD or 'N/A'): The actual end date of the fiscal period covered by the report. "
            "For annual/quarterly reports or earnings releases, this is the date the quarter or year ended. If not specified or not applicable, return 'N/A'.\n"
            "- 'document_type' (must match one of the keys in document_types.json).\n"
            "- 'fiscal_quarter' (Q1, Q2, Q3, Q4, FY, or N/A)."
        )

        prompt = f"""
Original Filename: {original_filename}
Document Types Specification:
{doc_types_str}

Active Ingestion Context:
{context_str}

First Chunk of Document:
\"\"\"
{first_chunk[:4000]}
\"\"\"

Please return a valid JSON object matching this structure:
{{
  "document_date": "YYYY-MM-DD",
  "period_end_date": "YYYY-MM-DD or N/A",
  "document_type": "quarterly_filing | annual_filing | earnings_announcement | press_release | analyst_report | news_article | transcript | other",
  "fiscal_quarter": "Q1 | Q2 | Q3 | Q4 | FY | N/A"
}}
"""
        response_text = self.llm.generate(prompt, system_prompt=system_prompt)

        # Extract JSON block
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                meta = json.loads(json_match.group(0))
                return (
                    meta.get("document_date", "YYYY-MM-DD"),
                    meta.get("document_type", "other"),
                    meta.get("fiscal_quarter", "N/A"),
                    meta.get("period_end_date", "N/A"),
                )
            except Exception:
                pass

        return ("YYYY-MM-DD", "other", "N/A", "N/A")

    def heal_ingest_context(self, registry: Dict[str, Dict[str, str]] = None) -> None:
        """Scan the parsed registry and update 6_company_context/ingest_context.md with correct fiscal mappings."""
        ticker = self.settings.active_ticker or "UNK"
        context_dir = Path(self.settings.active_workspace_path) / "6_company_context"
        context_dir.mkdir(parents=True, exist_ok=True)
        context_file = context_dir / "ingest_context.md"

        if registry is None:
            registry = self.load_parsed_registry()
        if not registry:
            return

        quarter_months = {}
        quarter_sources = {}

        for row in registry.values():
            doc_type = row.get("document_type", "")
            doc_date = row.get("document_date", "")
            fiscal_quarter = row.get("fiscal_quarter", "")
            period_end = row.get("period_end_date", "N/A")

            if fiscal_quarter == "N/A" or not fiscal_quarter:
                continue

            date_obj = None
            if doc_date and doc_date != "YYYY-MM-DD":
                try:
                    date_obj = datetime.datetime.strptime(doc_date, "%Y-%m-%d")
                except ValueError:
                    pass

            period_end_obj = None
            source_info = ""
            if period_end and period_end != "N/A" and period_end != "YYYY-MM-DD":
                try:
                    period_end_obj = datetime.datetime.strptime(period_end, "%Y-%m-%d")
                    source_info = f"extracted period end date {period_end}"
                except ValueError:
                    pass

            if not period_end_obj and date_obj:
                if doc_type in [
                    "quarterly_filing",
                    "annual_filing",
                    "earnings_announcement",
                ]:
                    period_end_obj = date_obj - datetime.timedelta(days=45)
                    source_info = (
                        f"estimated from document date {doc_date} minus 45 days"
                    )
                else:
                    period_end_obj = date_obj
                    source_info = f"extracted from document date {doc_date}"

            if period_end_obj:
                m = period_end_obj.month
                quarter_months.setdefault(fiscal_quarter, []).append(m)
                quarter_sources.setdefault(fiscal_quarter, {}).setdefault(m, []).append(
                    source_info
                )

        final_quarter_mappings = {}
        for q, months in quarter_months.items():
            if not months:
                continue
            from collections import Counter

            most_common_month, count = Counter(months).most_common(1)[0]
            sources = quarter_sources[q][most_common_month]
            unique_sources = list(set(sources))
            source_desc = "; ".join(unique_sources)
            final_quarter_mappings[q] = (most_common_month, source_desc)

        fye_month = None
        fye_desc = "Determined by Annual Filing dates."
        if "FY" in final_quarter_mappings:
            fye_month, fye_desc_src = final_quarter_mappings["FY"]
            fye_desc = (
                f"Month {fye_month} (determined from FY mappings: {fye_desc_src})"
            )
        elif "Q4" in final_quarter_mappings:
            fye_month, fye_desc_src = final_quarter_mappings["Q4"]
            fye_desc = (
                f"Month {fye_month} (determined from Q4 mappings: {fye_desc_src})"
            )

        lines = []
        lines.append(f"# Ingestion Context: {ticker}\n")
        lines.append(
            "This file contains automatically detected company configuration parameters.\n"
        )
        lines.append("## Fiscal Schedule Mappings")
        lines.append(f"- **Fiscal Year End**: {fye_desc}")
        lines.append("- **Quarterly Mappings**:")

        quarter_order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}
        sorted_quarters = sorted(
            final_quarter_mappings.keys(), key=lambda x: quarter_order.get(x, 10)
        )

        for q in sorted_quarters:
            m, src = final_quarter_mappings[q]
            lines.append(f"  - {q}: Ends around Month {m} ({src})")

        content = "\n".join(lines) + "\n"

        with open(context_file, "w", encoding="utf-8") as f:
            f.write(content)

    def create_or_update_ingest_context(
        self,
        ticker: str,
        doc_type: str,
        doc_date: str,
        fiscal_quarter: str,
        period_end_date: str = "N/A",
        registry: Dict[str, Dict[str, str]] = None,
    ) -> None:
        """Heal 6_company_context/ingest_context.md with correct mappings."""
        self.heal_ingest_context(registry)

    def ingest_single_file(
        self, raw_path: Path, registry: Dict[str, Dict[str, str]]
    ) -> None:
        """Process a single file: hash, parse, chunk, LLM identify, rename, archive, and log."""
        file_hash = compute_sha256(raw_path)
        import src.utils.formatting as formatting

        if file_hash in registry:
            logger.info(f"Skipping duplicate file: {raw_path.name}")
            formatting.print_info(f"Skipped duplicate file: {raw_path.name}")
            return

        logger.info(f"Ingesting file: {raw_path.name}")
        formatting.print_info(f"Ingesting file: {raw_path.name}...")

        # Read file and convert to markdown
        suffix = raw_path.suffix.lower()
        if suffix in [".html", ".htm"]:
            with open(raw_path, "r", encoding="utf-8", errors="ignore") as f:
                raw_content = f.read()
            markdown_body = html_to_markdown(raw_content)
        elif suffix == ".pdf":
            import fitz

            doc = fitz.open(str(raw_path))
            pages_text = []
            for page in doc:
                # Extract text sorting blocks by coordinates to preserve table layout and columns
                pages_text.append(page.get_text("text", sort=True))
            doc.close()
            markdown_body = "\n\n--- PAGE BREAK ---\n\n".join(pages_text)
        else:
            with open(raw_path, "r", encoding="utf-8", errors="ignore") as f:
                markdown_body = (
                    f.read()
                )  # Treat txt or other files as raw markdown/text

        # Create chunks
        chunks = chunk_text(markdown_body)

        # Identify metadata using the first chunk
        first_chunk_text = chunks[0] if chunks else ""
        doc_date, doc_type, fiscal_quarter, period_end_date = self.identify_metadata(
            first_chunk_text, raw_path.name
        )

        # Standardize date format YYYYMMDD
        clean_date = doc_date.replace("-", "").replace("/", "")
        if not re.match(r"^\d{8}$", clean_date):
            clean_date = datetime.date.today().strftime("%Y%m%d")

        # Build new filename
        new_basename = f"{clean_date}_{doc_type}"

        # Compile body with chunk comments, tracking their exact positions in the final file
        offsets = [(0, 0) for _ in chunks]
        full_output = ""
        for _ in range(3):
            chunk_lines = []
            chunk_lines.append("# Document Metadata & Chunk Inventory (chunk_id=0)\n")
            chunk_lines.append("| Metadata Key | Value |")
            chunk_lines.append("| --- | --- |")
            chunk_lines.append(f"| Original Filename | {raw_path.name} |")
            chunk_lines.append(f"| Document Date | {doc_date} |")
            chunk_lines.append(f"| Document Type | {doc_type} |")
            chunk_lines.append(f"| Fiscal Quarter | {fiscal_quarter} |")
            chunk_lines.append(f"| File Hash | {file_hash} |\n")

            chunk_lines.append("## Chunk Index Table")
            chunk_lines.append(
                "| Chunk ID | Character Range | Numbers Frequency | Symbols Frequency |"
            )
            chunk_lines.append("| --- | --- | --- | --- |")

            for idx, chunk in enumerate(chunks, 1):
                num_freq = len(re.findall(r"\d", chunk))
                sym_freq = len(
                    re.findall(r"[!@#$%^&*()_+\-=\[\]{}|;':\",./<>?]", chunk)
                )
                start_c, end_c = offsets[idx - 1]
                chunk_lines.append(
                    f"| {idx} | char {start_c} to {end_c} | {num_freq} | {sym_freq} |"
                )

            header_part = "\n".join(chunk_lines) + "\n"
            current_output = header_part
            new_offsets = []

            for idx, chunk in enumerate(chunks, 1):
                if idx > 1:
                    current_output += "\n"
                prefix = f"\n---\n<!-- CHUNK_START: {idx} -->\n"
                current_output += prefix
                start_pos = len(current_output)
                current_output += chunk
                end_pos = len(current_output)
                suffix = f"\n<!-- CHUNK_END: {idx} -->\n---"
                current_output += suffix

                new_offsets.append((start_pos, end_pos))

            offsets = new_offsets
            full_output = current_output

        # Write output markdown
        parsed_dir = Path(self.settings.active_workspace_path) / "2_parsed_data"
        parsed_dir.mkdir(parents=True, exist_ok=True)
        out_markdown_path = parsed_dir / f"{new_basename}.md"

        with open(out_markdown_path, "w", encoding="utf-8") as f:
            f.write(full_output)

        # Move raw file to archive
        archive_dir = Path(self.settings.active_workspace_path) / "3_archived_data"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_raw_path = archive_dir / f"{new_basename}{raw_path.suffix}"

        raw_path.rename(archive_raw_path)

        # Update registry
        registry[file_hash] = {
            "file_hash": file_hash,
            "original_filename": raw_path.name,
            "new_filename": out_markdown_path.name,
            "document_type": doc_type,
            "document_date": doc_date,
            "fiscal_quarter": fiscal_quarter,
            "period_end_date": period_end_date,
        }

        # Update self-healing ingest context
        self.create_or_update_ingest_context(
            self.settings.active_ticker or "UNK",
            doc_type,
            doc_date,
            fiscal_quarter,
            period_end_date,
            registry,
        )
        formatting.print_success(
            f"Ingested {raw_path.name} -> {out_markdown_path.name}"
        )

    def run_ingestion(self, limit: int = None) -> None:
        """Scan 1_ingest_data/ and run jobs sequentially via the sequential JobQueue."""
        if not self.settings.active_workspace_path:
            raise ValueError(
                "No active workspace is selected. Use 'fa use <ticker>' first."
            )

        ingest_dir = Path(self.settings.active_workspace_path) / "1_ingest_data"
        if not ingest_dir.exists():
            logger.warning(f"Ingestion directory {ingest_dir} does not exist.")
            return

        raw_files = [
            p
            for p in ingest_dir.iterdir()
            if p.is_file()
            and p.name.lower() != "readme.md"
            and not p.name.startswith(".")
        ]
        if not raw_files:
            logger.info("No raw files found to ingest.")
            return

        import src.utils.formatting as formatting

        if limit is not None:
            skipped_limit_files = raw_files[limit:]
            raw_files = raw_files[:limit]
            for f in skipped_limit_files:
                formatting.print_info(f"Skipped due to limit: {f.name}")

        registry = self.load_parsed_registry()

        # Build JobQueue
        queue = JobQueue(retries=2, initial_delay=1.0)
        for raw_file in raw_files:
            queue.add_job(self.ingest_single_file, raw_file, registry)

        # Execute all jobs
        queue.run()

        # Save updated registry
        self.save_parsed_registry(registry)

        # Final healing check to ensure all mappings are validated and sorted correctly
        self.heal_ingest_context(registry)
