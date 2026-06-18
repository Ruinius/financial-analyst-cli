import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

from src.core.config import load_config
from src.services.llm_client import LLMClient
from src.pipeline.curator_agent import strip_markdown_code_blocks

logger = logging.getLogger(__name__)


class IndexerAgent:
    def __init__(self, settings=None):
        self.settings = settings or load_config()
        self.llm = LLMClient()

    def run_indexing(self, ticker: str) -> None:
        """
        Scan 4_extracted_data, 5_historical_analysis, and 6_financial_model.
        Generate a folder index markdown file [TICKER]_folder_index.md in the workspace root.
        """
        # Handle MagicMocks or invalid ticker symbols in testing environments
        if not ticker or not isinstance(ticker, str) or "MagicMock" in str(ticker):
            ticker = "MOCK"

        if not self.settings.active_workspace_path:
            logger.warning("No active workspace path set. Skipping indexing.")
            return

        workspace = Path(self.settings.active_workspace_path)
        index_path = workspace / f"{ticker}_folder_index.md"

        folders = ["4_extracted_data", "5_historical_analysis", "6_financial_model"]
        catalog_data = {}

        for folder in folders:
            folder_path = workspace / folder
            catalog_data[folder] = []
            if not folder_path.exists():
                continue

            # Scan files (excluding README.md, hidden files, and temp files)
            for item in folder_path.iterdir():
                if (
                    item.is_file()
                    and item.name.lower() != "readme.md"
                    and not item.name.startswith(".")
                ):
                    file_info = self._get_file_info(item, folder)
                    catalog_data[folder].append(file_info)

            # Sort files by name/date descending
            catalog_data[folder].sort(key=lambda x: x["name"], reverse=True)

        # Build prompt listing files
        prompt_list = []
        for folder, files in catalog_data.items():
            prompt_list.append(f"### Folder: {folder}")
            if not files:
                prompt_list.append("- No files present.")
            for f in files:
                prompt_list.append(
                    f"- File: `{f['relative_path']}`\n"
                    f"  Size: {f['size_kb']:.1f} KB, Modified: {f['modified_date']}\n"
                    f"  First 300 chars: \"{f['preview']}\""
                )
        files_details_str = "\n".join(prompt_list)

        system_prompt = (
            "You are Sir Pennyworth's Folder Indexer Agent. "
            f"Your task is to generate the entire updated folder index markdown file for the active ticker ({ticker}). "
            "This file must be named '[TICKER]_folder_index.md' and keeps track of all files in 4_extracted_data, 5_historical_analysis, and 6_financial_model. "
            "Return the entire updated markdown file. Do not wrap in markdown code blocks. "
            "Ensure all files have working relative markdown links (e.g. '[filename](4_extracted_data/filename)'). "
            "For each file, display its relative path link, size, modified date, and a concise description of its purpose/contents "
            "(e.g. what company, period, metrics, moat, or DCF valuation it contains). "
            "Provide a premium, highly structured, clean layout that makes it easy for other AI agents to lookup relevant files."
        )

        prompt = f"""
Ticker: {ticker}
Current Workspace Files to Index:
\"\"\"
{files_details_str}
\"\"\"

Please generate the complete markdown content for '{ticker}_folder_index.md'. Do not wrap in markdown code blocks.
"""

        try:
            # Generate via LLM
            updated_index = self.llm.generate(prompt, system_prompt=system_prompt)
            cleaned_index = strip_markdown_code_blocks(updated_index)
            # Ensure it's not empty/invalid
            if cleaned_index and len(cleaned_index.strip()) > 50:
                index_path.write_text(cleaned_index, encoding="utf-8")
                logger.info(f"Successfully generated LLM index at {index_path}")
                return
        except Exception as e:
            logger.error(
                f"Failed to generate folder index via LLM: {e}. Falling back to programmatic index."
            )

        # Fallback to Programmatic Indexing
        self._write_programmatic_index(index_path, ticker, catalog_data)

    def _get_file_info(self, file_path: Path, folder: str) -> Dict[str, Any]:
        stat = file_path.stat()
        size_kb = stat.st_size / 1024.0
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d")

        # Read first few lines/chars to get a preview/title
        preview = ""
        title = ""
        doc_type = ""
        fiscal_period = ""

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(1000)
                # Clean preview for prompt
                preview_clean = (
                    content[:300].replace("\n", " ").replace('"', '\\"').strip()
                )
                preview = f"{preview_clean}..."

                # Extract first markdown heading
                heading_match = re.search(r"^#\s+(.*)$", content, re.MULTILINE)
                if heading_match:
                    title = heading_match.group(1).strip()

                # Extract some common financial metadata keys
                doc_type_match = re.search(
                    r"\|\s*Document Type\s*\|\s*([^|]+?)\s*\|", content
                )
                if doc_type_match:
                    doc_type = doc_type_match.group(1).strip()

                fq_match = re.search(
                    r"\|\s*Fiscal Quarter\s*\|\s*([^|]+?)\s*\|", content
                )
                fy_match = re.search(r"\|\s*Fiscal Year\s*\|\s*([^|]+?)\s*\|", content)
                if fq_match and fy_match:
                    fiscal_period = (
                        f"{fy_match.group(1).strip()}-{fq_match.group(1).strip()}"
                    )
        except Exception:
            preview = "[Could not read preview]"

        return {
            "name": file_path.name,
            "relative_path": f"{folder}/{file_path.name}",
            "size_kb": size_kb,
            "modified_date": mtime,
            "preview": preview,
            "title": title or file_path.stem.replace("_", " ").title(),
            "doc_type": doc_type,
            "fiscal_period": fiscal_period,
        }

    def _write_programmatic_index(
        self,
        index_path: Path,
        ticker: str,
        catalog_data: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        """Fallback to programmatic generation of index in case LLM is unavailable."""
        lines = []
        lines.append(f"# Folder Index: {ticker}\n")
        lines.append(
            "This index is maintained automatically by the Indexer Agent. "
            "It catalogs all files across key data and model folders to help other agents find relevant data.\n"
        )

        folder_descriptions = {
            "4_extracted_data": "Chunk-by-chunk extraction summaries, statements, and audit linkage records.",
            "5_historical_analysis": "Longitudinal quarterly and annual metrics, synthesized analyst views, and qualitative trend reports.",
            "6_financial_model": "Readable markdown outputs detailing DCF projections and intrinsic value calculations.",
        }

        for folder, files in catalog_data.items():
            desc = folder_descriptions.get(folder, "")
            lines.append(f"## {folder}")
            if desc:
                lines.append(f"*{desc}*\n")

            if not files:
                lines.append("- No files present in this folder.\n")
                continue

            for f in files:
                # Compile a descriptive details string
                details = []
                if f["doc_type"]:
                    details.append(f"Type: {f['doc_type']}")
                if f["fiscal_period"]:
                    details.append(f"Period: {f['fiscal_period']}")

                detail_str = f" ({', '.join(details)})" if details else ""
                lines.append(
                    f"- **[{f['name']}]({f['relative_path']})**{detail_str}\n"
                    f"  - Size: {f['size_kb']:.1f} KB | Modified: {f['modified_date']}\n"
                    f"  - Summary: {f['title']}\n"
                )
            lines.append("")

        index_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(
            f"Successfully generated fallback programmatic index at {index_path}"
        )
