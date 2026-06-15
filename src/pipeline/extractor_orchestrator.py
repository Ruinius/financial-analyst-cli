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
from src.pipeline.queue import JobQueue

logger = logging.getLogger(__name__)


class AuditLinkage(BaseModel):
    source_file: str
    chunk_id: int
    exact_snippet: str


class LineItem(BaseModel):
    line_name: str
    value: float
    operating: bool = True
    calculated: bool = False  # is this a sub-total of total number?
    category: str = "current_asset"  # this can strictly be current_asset, noncurrent_asset, current_liabilities, noncurrent_liabilities, equity, title_header.
    audit: AuditLinkage


class FinancialStatementsExtraction(BaseModel):
    line_items: List[LineItem]


class QualitativeAssessment(BaseModel):
    economic_moat: str = "Narrow"
    economic_moat_rationale: str = ""
    margin_outlook: str = "Stable"
    margin_magnitude: str = "0 pp"
    margin_rationale: str = ""
    growth_outlook: str = "Stable"
    growth_magnitude: str = "0 pp"
    growth_rationale: str = ""


class TranscriptExtraction(BaseModel):
    tone: str
    inconsistency: str
    summary: str


class GeneralSummary(BaseModel):
    summary: str


def get_chunk_by_id(content: str, chunk_id: int) -> str:
    """Extract chunk content between comments."""
    if chunk_id == 0:
        # Extract everything before the first chunk start comment
        start_idx = content.find("<!-- CHUNK_START:")
        if start_idx != -1:
            return content[:start_idx].strip()
        return content.strip()

    start_marker = f"<!-- CHUNK_START: {chunk_id} -->"
    end_marker = f"<!-- CHUNK_END: {chunk_id} -->"

    start_idx = content.find(start_marker)
    if start_idx == -1:
        return ""
    start_idx += len(start_marker)

    end_idx = content.find(end_marker, start_idx)
    if end_idx == -1:
        return ""

    return content[start_idx:end_idx].strip()


def clean_val(val: str) -> float:
    """Clean string number to float."""
    if not val:
        return 0.0
    val_str = str(val).strip()
    if val_str == "N/A" or val_str == "--" or not val_str:
        return 0.0
    cleaned = val_str.replace(",", "").replace("$", "").strip()
    is_negative = False
    if cleaned.startswith("("):
        is_negative = True
        cleaned = cleaned.strip("()")

    if "%" in cleaned:
        pct_match = re.search(r"(-?\d+\.?\d*)", cleaned)
        if pct_match:
            try:
                num = float(pct_match.group(1))
                if is_negative:
                    num = -num
                return num / 100.0
            except ValueError:
                pass

    match = re.search(r"(-?\d+\.?\d*)", cleaned)
    if match:
        try:
            num = float(match.group(1))
            if is_negative:
                num = -num
            return num
        except ValueError:
            return 0.0
    return 0.0


class Extractor:
    def __init__(self):
        self.settings = load_config()
        self.llm = LLMClient()
        self._extract_context_cache = None
        self._dict_cache = {}

    def get_extract_context(self) -> str:
        if self._extract_context_cache is None:
            ticker = self.settings.active_ticker or "UNK"
            context_path = (
                Path(self.settings.active_workspace_path)
                / f"{ticker}_extract_learning.md"
            )
            if context_path.exists():
                try:
                    with open(context_path, "r", encoding="utf-8") as f:
                        self._extract_context_cache = f.read()
                except Exception:
                    self._extract_context_cache = ""
            else:
                self._extract_context_cache = ""
        return self._extract_context_cache

    def get_dictionary(self, name: str) -> str:
        if name not in self._dict_cache:
            dict_path = Path(f"src/resources/dictionary/{name}.md")
            if dict_path.exists():
                try:
                    with open(dict_path, "r", encoding="utf-8") as f:
                        self._dict_cache[name] = f.read()
                except Exception:
                    self._dict_cache[name] = ""
            else:
                self._dict_cache[name] = ""
        return self._dict_cache[name]

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

    def run_extraction(
        self, limit: int = None, files_to_process: List[Path] = None
    ) -> None:
        """Scan 2_parsed_data/ and run extraction sequentially."""
        if not self.settings.active_workspace_path:
            raise ValueError(
                "No active workspace is selected. Use 'fa use <ticker>' first."
            )

        parsed_dir = Path(self.settings.active_workspace_path) / "2_parsed_data"
        if not parsed_dir.exists():
            logger.warning(f"Parsed directory {parsed_dir} does not exist.")
            return

        import src.utils.formatting as formatting

        if files_to_process is not None:
            files_to_run = files_to_process
        else:
            parsed_files = [
                p
                for p in parsed_dir.iterdir()
                if p.is_file()
                and p.suffix.lower() == ".md"
                and p.name.lower() != "readme.md"
                and not p.name.startswith(".")
                and p.name != "parsed_data.csv"
            ]
            if not parsed_files:
                logger.info("No parsed files found to extract.")
                return

            extracted_registry = self.load_extracted_registry()

            # Filter out files that are already extracted first
            files_to_run = [p for p in parsed_files if p.name not in extracted_registry]

            for p_file in parsed_files:
                if p_file.name in extracted_registry:
                    formatting.print_info(f"Skipped already extracted: {p_file.name}")

            if limit is not None:
                skipped_limit_files = files_to_run[limit:]
                files_to_run = files_to_run[:limit]
                for f in skipped_limit_files:
                    formatting.print_info(f"Skipped due to limit: {f.name}")

        if not files_to_run:
            formatting.print_info("No files to extract.")
            return

        queue = JobQueue(retries=2, initial_delay=1.0)
        for p_file in files_to_run:
            queue.add_job(self.extract_single_file, p_file)

        queue.run()

        # Invoke Curator Agent at the end of extraction
        ticker = self.settings.active_ticker or "UNK"
        logs = f"Executed extraction stage. Processed files: {[f.name for f in files_to_run]}"
        from src.pipeline.curator_agent import CuratorAgent

        CuratorAgent(self.settings).curate(ticker, "extract", logs)

    def get_document_metadata(self, file_name: str) -> dict:
        parsed_dir = Path(self.settings.active_workspace_path) / "2_parsed_data"
        csv_path = parsed_dir / "parsed_data.csv"
        if csv_path.exists():
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("new_filename") == file_name:
                        return row
        return {}

    def extract_single_file(self, file_path: Path) -> None:
        logger.info(f"Extracting details from: {file_path.name}")
        import src.utils.formatting as formatting

        formatting.print_info(f"Extracting details from: {file_path.name}...")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Read chunk_id=0
        chunk_0 = get_chunk_by_id(content, 0)
        if not chunk_0:
            # Fallback to reading first part of document if chunk_0 is missing
            chunk_0 = content[:4000]

        # Determine doc_type from metadata table in chunk_0 first (failsafe), or registry csv
        doc_type = "other"
        meta_match = re.search(r"\|\s*Document Type\s*\|\s*([^|]+?)\s*\|", chunk_0)
        if meta_match:
            doc_type = meta_match.group(1).strip()
        else:
            metadata = self.get_document_metadata(file_path.name)
            doc_type = metadata.get("document_type", "other")

        is_financial = doc_type in [
            "quarterly_filing",
            "annual_filing",
            "earnings_announcement",
        ]
        is_analyst = doc_type == "analyst_report"
        is_transcript = doc_type == "transcript"

        # Deterministically select chunk IDs
        chunk_matches = re.findall(r"<!-- CHUNK_START:\s*(\d+)\s*-->", content)
        all_chunk_ids = sorted(list(set(map(int, chunk_matches))))
        if not all_chunk_ids:
            all_chunk_ids = [1]

        success = False

        if is_financial:
            from src.pipeline.extractor_agents.extractor_financials import (
                extract_financials,
            )

            success = extract_financials(
                file_path=file_path,
                content=content,
                chunk_ids=all_chunk_ids,
                extractor=self,
            )
        elif is_analyst:
            from src.pipeline.extractor_agents.extractor_analyst_report import (
                extract_analyst_report,
            )

            success = extract_analyst_report(
                file_path=file_path,
                content=content,
                chunk_ids=all_chunk_ids,
                extractor=self,
            )
        elif is_transcript:
            from src.pipeline.extractor_agents.extractor_transcript import (
                extract_transcript,
            )

            success = extract_transcript(
                file_path=file_path,
                content=content,
                chunk_ids=all_chunk_ids,
                extractor=self,
            )
        else:
            from src.pipeline.extractor_agents.extractor_other import extract_other

            success = extract_other(
                file_path=file_path,
                content=content,
                chunk_ids=all_chunk_ids,
                extractor=self,
            )

        if success:
            self.save_extracted_registry(file_path.name)
