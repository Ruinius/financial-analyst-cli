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
        match = re.split(r"<!-- CHUNK_START:\s*\d+\s*-->", content, maxsplit=1)
        if match:
            return match[0].strip()
        return ""
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
        self._extract_context_cache = None

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

    def run_extraction(self, limit: int = None) -> None:
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
            if p.is_file()
            and p.suffix.lower() == ".md"
            and p.name.lower() != "readme.md"
            and not p.name.startswith(".")
            and p.name != "parsed_data.csv"
        ]
        if not parsed_files:
            logger.info("No parsed files found to extract.")
            return

        import src.utils.formatting as formatting

        extracted_registry = self.load_extracted_registry()

        # Filter out files that are already extracted first
        unextracted_files = [
            p for p in parsed_files if p.name not in extracted_registry
        ]

        for p_file in parsed_files:
            if p_file.name in extracted_registry:
                formatting.print_info(f"Skipped already extracted: {p_file.name}")

        if limit is not None:
            skipped_limit_files = unextracted_files[limit:]
            unextracted_files = unextracted_files[:limit]
            for f in skipped_limit_files:
                formatting.print_info(f"Skipped due to limit: {f.name}")

        queue = JobQueue(retries=2, initial_delay=1.0)
        for p_file in unextracted_files:
            queue.add_job(self.extract_single_file, p_file)

        queue.run()

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

        summaries = []
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
                summaries=summaries,
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
                summaries=summaries,
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
                summaries=summaries,
            )
        else:
            from src.pipeline.extractor_agents.extractor_other import extract_other

            success = extract_other(
                file_path=file_path,
                content=content,
                chunk_ids=all_chunk_ids,
                extractor=self,
                summaries=summaries,
            )

        if success:
            self.save_extracted_registry(file_path.name)
