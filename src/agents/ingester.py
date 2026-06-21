from src.utils.markdown_helper import extract_json_from_text
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
from src.services.llm_client import get_llm_client
from src.services.queue import JobQueue

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
    # ⚡ Bolt Optimization: Cache len(line) and use .clear() to reduce list allocation overhead
    chunks = []
    current_chunk = []
    current_len = 0
    lines = text.split("\n")

    for line in lines:
        line_len = len(line)
        if line_len > max_chars:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk.clear()
                current_len = 0
            for i in range(0, line_len, max_chars):
                chunks.append(line[i : i + max_chars])
        else:
            add_len = line_len + (1 if current_chunk else 0)
            if current_len + add_len > max_chars:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = line_len
            else:
                current_chunk.append(line)
                current_len += add_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks


class Ingester:
    def __init__(self):
        self.settings = load_config()
        self.llm = get_llm_client()

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
                        if (
                            "fiscal_year" not in row
                            or not row["fiscal_year"]
                            or row["fiscal_year"] == "N/A"
                        ):
                            doc_date = row.get("document_date", "")
                            row["fiscal_year"] = (
                                doc_date[:4] if len(doc_date) >= 4 else "N/A"
                            )
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
            "fiscal_year",
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
    ) -> Tuple[str, str, str, str, str]:
        """Use LLM to identify document_date, document_type, fiscal_quarter, fiscal_year, and period_end_date."""
        # Load document types spec
        doc_types_path = (
            Path(__file__).parent.parent / "resources" / "document_types.json"
        )
        doc_types_str = ""
        if doc_types_path.exists():
            with open(doc_types_path, "r", encoding="utf-8") as f:
                doc_types_str = f.read()

        ticker = self.settings.active_ticker or "UNK"
        context_path = (
            Path(self.settings.active_workspace_path) / f"{ticker}_extract_learning.md"
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
            "- 'fiscal_quarter' (Q1, Q2, Q3, Q4, FY, or N/A).\n"
            "- 'fiscal_year' (YYYY or N/A): The fiscal year the report corresponds to."
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
  "fiscal_quarter": "Q1 | Q2 | Q3 | Q4 | FY | N/A",
  "fiscal_year": "YYYY or N/A"
}}
"""
        response_text_first = self.llm.generate(prompt, system_prompt=system_prompt)

        # Parse document types keys for validation
        doc_types_keys = []
        if doc_types_path.exists():
            try:
                with open(doc_types_path, "r", encoding="utf-8") as f:
                    doc_types_data = json.load(f)
                    doc_types_keys = list(
                        doc_types_data.get("document_types", {}).keys()
                    )
            except Exception:
                pass
        if not doc_types_keys:
            doc_types_keys = [
                "earnings_announcement",
                "quarterly_filing",
                "annual_filing",
                "press_release",
                "analyst_report",
                "news_article",
                "transcript",
                "other",
            ]

        # Extract and parse response directly from first turn
        json_str = extract_json_from_text(response_text_first)
        if json_str:
            try:
                meta = json.loads(json_str)
                doc_type = meta.get("document_type", "other")
                if doc_type not in doc_types_keys:
                    doc_type = "other"
                return (
                    meta.get("document_date", "YYYY-MM-DD"),
                    doc_type,
                    meta.get("fiscal_quarter", "N/A"),
                    meta.get("fiscal_year", "N/A"),
                    meta.get("period_end_date", "N/A"),
                )
            except Exception:
                pass

        return ("YYYY-MM-DD", "other", "N/A", "N/A", "N/A")

    def heal_ingest_context(self, registry: Dict[str, Dict[str, str]] = None) -> None:
        """Scan the parsed registry and update learning and wiki files using the Curator Agent."""
        ticker = self.settings.active_ticker or "UNK"
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

        # Compile list of files in registry for Wiki Sources
        file_logs = []
        file_logs.append("### Registry Files:")
        for r in registry.values():
            file_logs.append(
                f"- [{r.get('new_filename')}]: Original '{r.get('original_filename')}', type '{r.get('document_type')}', date '{r.get('document_date')}', period end '{r.get('period_end_date')}'"
            )

        agent_logs = "\n".join(lines) + "\n\n" + "\n".join(file_logs)

        # Trigger Curator Agent
        from src.agents.curator_agent import CuratorAgent

        curator = CuratorAgent(self.settings)
        curator.curate(ticker, "ingest", agent_logs)

    def create_or_update_ingest_context(
        self,
        ticker: str,
        doc_type: str,
        doc_date: str,
        fiscal_quarter: str,
        period_end_date: str = "N/A",
        registry: Dict[str, Dict[str, str]] = None,
    ) -> None:
        """Call heal_ingest_context to curate via CuratorAgent."""
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
        doc_date, doc_type, fiscal_quarter, fiscal_year, period_end_date = (
            self.identify_metadata(first_chunk_text, raw_path.name)
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
            chunk_lines.append(f"| Fiscal Year | {fiscal_year} |")
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
            "fiscal_year": fiscal_year,
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

        # Run the Quality Check Agent for self-healing of csv and markdowns
        self.run_quality_check_agent()
        self.heal_markdown_files()

        # Final healing check to ensure all mappings are validated and sorted correctly
        registry = self.load_parsed_registry()
        self.heal_ingest_context(registry)

    def run_self_healing(self) -> None:
        """Run only the self-healing and quality check agent on existing parsed data."""
        import src.utils.formatting as formatting

        formatting.print_info(
            "Starting metadata self-healing and Quality Check Agent..."
        )
        self.run_quality_check_agent()
        self.heal_markdown_files()
        registry = self.load_parsed_registry()
        self.heal_ingest_context(registry)

    def overwrite_csv_rows(self, updates: List[Dict[str, str]]) -> None:
        """Overwrite fiscal_quarter and fiscal_year in parsed_data.csv for given file hashes."""
        registry = self.load_parsed_registry()
        updated = False
        import src.utils.formatting as formatting

        for update in updates:
            fh = update.get("file_hash")
            new_fn = update.get("new_filename")
            fq = update.get("fiscal_quarter")
            fy = update.get("fiscal_year")

            # Try to resolve hash by new_filename if file_hash not found/matching
            target_hash = None
            if fh and fh in registry:
                target_hash = fh
            elif new_fn:
                for k, v in registry.items():
                    if v.get("new_filename") == new_fn:
                        target_hash = k
                        break

            if target_hash:
                row = registry[target_hash]
                if fq is not None and row.get("fiscal_quarter") != fq:
                    formatting.print_info(
                        f"Correcting quarter: {row.get('new_filename')} -> {fq}"
                    )
                    row["fiscal_quarter"] = fq
                    updated = True
                if fy is not None and row.get("fiscal_year") != fy:
                    formatting.print_info(
                        f"Correcting year: {row.get('new_filename')} -> {fy}"
                    )
                    row["fiscal_year"] = fy
                    updated = True
        if updated:
            self.save_parsed_registry(registry)
            formatting.print_success("Successfully updated parsed_data.csv.")

    def heal_markdown_files(self) -> None:
        """Update markdown files metadata in 2_parsed_data to match the CSV registry as source of truth."""
        registry = self.load_parsed_registry()
        workspace = Path(self.settings.active_workspace_path)
        parsed_dir = workspace / "2_parsed_data"
        import src.utils.formatting as formatting

        for reg_row in registry.values():
            filename = reg_row.get("new_filename")
            if not filename:
                continue

            file_path = parsed_dir / filename
            if not file_path.exists():
                continue

            fq = reg_row.get("fiscal_quarter", "N/A")
            fy = reg_row.get("fiscal_year", "N/A")

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Check and replace
                quarter_pattern = r"(\|\s*Fiscal Quarter\s*\|\s*)([^|]*?)(\s*\|)"
                year_pattern = r"(\|\s*Fiscal Year\s*\|\s*)([^|]*?)(\s*\|)"

                has_year = re.search(year_pattern, content)
                has_quarter = re.search(quarter_pattern, content)

                if not has_quarter:
                    continue

                if has_year:
                    new_content = re.sub(quarter_pattern, rf"\g<1>{fq}\g<3>", content)
                    new_content = re.sub(year_pattern, rf"\g<1>{fy}\g<3>", new_content)
                else:
                    replacement = rf"\g<1>{fq}\g<3>\n| Fiscal Year | {fy} |"
                    new_content = re.sub(quarter_pattern, replacement, content)

                if new_content != content:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    formatting.print_success(
                        f"Self-healed metadata header in {filename}."
                    )
            except Exception as e:
                formatting.print_warning(
                    f"Failed to self-heal markdown header for {filename}: {e}"
                )

    def run_quality_check_agent(self) -> None:
        """Invoke Quality Check Agent to identify, validate and overwrite CSV rows."""
        import src.utils.formatting as formatting

        ticker = self.settings.active_ticker or "UNK"
        workspace = Path(self.settings.active_workspace_path)
        extract_learning_path = workspace / f"{ticker}_extract_learning.md"

        context_str = ""
        if extract_learning_path.exists():
            try:
                with open(extract_learning_path, "r", encoding="utf-8") as f:
                    context_str = f.read()
            except Exception:
                pass

        registry = self.load_parsed_registry()
        if not registry:
            formatting.print_info("No registry entries found to quality check.")
            return

        rows_list = []
        for r in registry.values():
            rows_list.append(
                f"file_hash: {r.get('file_hash')}, original_filename: {r.get('original_filename')}, "
                f"new_filename: {r.get('new_filename')}, document_type: {r.get('document_type')}, "
                f"document_date: {r.get('document_date')}, fiscal_quarter: {r.get('fiscal_quarter')}, "
                f"fiscal_year: {r.get('fiscal_year')}, period_end_date: {r.get('period_end_date')}"
            )
        registry_str = "\n".join(rows_list)

        system_prompt = (
            "You are Sir Pennyworth's Quality Check Agent. Your task is to verify and correct the "
            "'fiscal_quarter' and 'fiscal_year' columns in the company parsed registry.\n"
            "You will be given the 'extract_learning.md' content (which contains the active ticker's "
            "fiscal schedule mappings, lessons, and metadata logic) and the list of current rows "
            "from 'parsed_data.csv'.\n"
            "Analyze the 'original_filename', 'new_filename', 'document_date', 'period_end_date', "
            "and the 'extract_learning.md' mappings. Determine if the current 'fiscal_quarter' "
            "and 'fiscal_year' values are correct.\n"
            "You MUST output ONLY a valid JSON object of updates to correct any misaligned quarters or years. "
            "If all entries are correct, return an empty updates list. Do not correct entries that do not need correction.\n"
            "Format of response:\n"
            "{\n"
            '  "updates": [\n'
            "    {\n"
            '      "file_hash": "<file_hash_of_the_row>",\n'
            '      "fiscal_quarter": "<corrected_quarter (Q1|Q2|Q3|Q4|FY|N/A)>",\n'
            '      "fiscal_year": "<corrected_year (YYYY|N/A)>"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        prompt = f"""
Active Ingestion Context (extract_learning.md):
\"\"\"
{context_str}
\"\"\"

Current Parsed CSV Rows (parsed_data.csv):
\"\"\"
{registry_str}
\"\"\"

Please identify any incorrect fiscal_quarter or fiscal_year values and return updates in valid JSON.
"""
        logger.info("Triggering Quality Check Agent...")
        try:
            response = self.llm.generate(prompt, system_prompt=system_prompt)
            json_str = extract_json_from_text(response)
            if json_str:
                data = json.loads(json_str)
                updates = data.get("updates", [])
                if updates:
                    formatting.print_info(
                        f"Quality Check Agent identified {len(updates)} metadata correction(s)."
                    )
                    self.overwrite_csv_rows(updates)
                else:
                    formatting.print_info(
                        "Quality Check Agent found no metadata errors."
                    )
            else:
                formatting.print_warning(
                    "Quality Check Agent response was not valid JSON."
                )
        except Exception as e:
            formatting.print_error(f"Quality Check Agent execution failed: {e}")
