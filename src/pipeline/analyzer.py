import csv
import re
from pathlib import Path
from typing import Dict, List, Any

from src.core.config import load_config
import src.utils.formatting as formatting


class Analyzer:
    def __init__(self):
        self.settings = load_config()

    def run_analysis(self) -> None:
        """Scan extracted files and compile longitudinal trends and views."""
        if not self.settings.active_workspace_path:
            raise ValueError(
                "No active workspace is selected. Use 'fa use <ticker>' first."
            )

        workspace = Path(self.settings.active_workspace_path)
        extracted_dir = workspace / "4_extracted_data"
        parsed_dir = workspace / "2_parsed_data"

        # 1. Read parsed_data.csv to get metadata for all documents
        csv_path = parsed_dir / "parsed_data.csv"
        if not csv_path.exists():
            formatting.print_warning("No parsed_data.csv found. Run ingestion first.")
            return

        doc_metadata = {}
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                new_file = row.get("new_filename")
                if new_file:
                    doc_metadata[new_file] = row

        # 2. Read extracted_data.csv to find which files have been extracted
        extracted_csv = extracted_dir / "extracted_data.csv"
        if not extracted_csv.exists():
            formatting.print_warning(
                "No extracted_data.csv found. Run extraction first."
            )
            return

        extracted_files = []
        with open(extracted_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                source_file = row.get("source_file")
                if source_file and source_file in doc_metadata:
                    extracted_files.append(source_file)

        # Sort extracted files by document_date chronologically
        def get_doc_date(fname):
            meta = doc_metadata[fname]
            return meta.get("document_date", "0000-00-00")

        extracted_files.sort(key=get_doc_date)

        # Storage for structured data
        analyst_views_entries = []
        news_entries = []
        transcript_entries = []
        quarterly_financials = []
        annual_financials = []

        for src_file in extracted_files:
            meta = doc_metadata[src_file]
            doc_type = meta.get("document_type")
            doc_date = meta.get("document_date", "")
            fiscal_quarter = meta.get("fiscal_quarter", "N/A")

            # Extract year from document_date
            year = "YYYY"
            if len(doc_date) >= 4:
                year = doc_date[:4]

            # Construct extracted report filename
            src_path = Path(src_file)
            extracted_filename = f"{src_path.stem}_extracted.md"
            extracted_path = extracted_dir / extracted_filename

            if not extracted_path.exists():
                continue

            with open(extracted_path, "r", encoding="utf-8") as f:
                content = f.read()

            # A. Parse qualitative data for news / transcripts / analyst reports
            chunk_summaries = self.parse_chunk_summaries(content)

            if doc_type == "analyst_report":
                view_entry = self.parse_analyst_report_fields(content)
                view_entry["date"] = doc_date
                view_entry["document"] = extracted_filename
                analyst_views_entries.append(view_entry)

            elif doc_type in ["press_release", "news_article", "other"]:
                news_entries.append(
                    {
                        "date": doc_date,
                        "document": extracted_filename,
                        "summary": chunk_summaries,
                    }
                )

            elif doc_type == "transcript":
                transcript_entries.append(
                    {
                        "date": doc_date,
                        "document": extracted_filename,
                        "summary": chunk_summaries,
                    }
                )

            # B. Parse quantitative financial data
            if doc_type in [
                "quarterly_filing",
                "annual_filing",
                "earnings_announcement",
            ]:
                fin_metrics = self.parse_financial_summary(content)
                if not fin_metrics:
                    continue

                fin_metrics["date"] = doc_date
                fin_metrics["document"] = extracted_filename

                if doc_type == "annual_filing" or fiscal_quarter == "FY":
                    fin_metrics["period"] = year
                    annual_financials.append(fin_metrics)
                else:
                    fin_metrics["period"] = f"{year}-{fiscal_quarter}"
                    quarterly_financials.append(fin_metrics)

        # 3. Deduce Q4 financials if Q1-Q3 and Annual are present
        self.deduce_q4_financials(quarterly_financials, annual_financials)

        # 4. Generate & Save output files in 5_historical_analysis/
        analysis_dir = workspace / "5_historical_analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        self.write_analyst_views(
            analysis_dir / "analyst_views.md", analyst_views_entries
        )
        self.write_news_trend(analysis_dir / "news_trend.md", news_entries)
        self.write_transcript_trend(
            analysis_dir / "transcript_trend.md", transcript_entries
        )
        self.write_financials(
            analysis_dir / "financials_quarter.md",
            quarterly_financials,
            is_quarterly=True,
        )
        self.write_financials(
            analysis_dir / "financials_annual.md", annual_financials, is_quarterly=False
        )

    def parse_chunk_summaries(self, content: str) -> str:
        """Extract summaries from the Chunk Summaries section."""
        match = re.search(
            r"## Chunk Summaries\s*\n(.*?)(?:\n---|\n##|$)", content, re.DOTALL
        )
        if match:
            return match.group(1).strip()
        return "No chunk summaries found."

    def parse_analyst_report_fields(self, content: str) -> Dict[str, str]:
        """Parse economic moat, margin outlook, and growth outlook sections."""
        moat = "None"
        moat_rationale = ""
        margin_outlook = "Stable"
        margin_mag = "0 pp"
        margin_rationale = ""
        growth_outlook = "Stable"
        growth_mag = "0 pp"
        growth_rationale = ""

        # Moat
        moat_match = re.search(
            r"### Economic Moat\s*\n\s*Rating:\s*\*\*(.*?)\*\*", content, re.IGNORECASE
        )
        if moat_match:
            moat = moat_match.group(1).strip()
        moat_rat_match = re.search(
            r"### Economic Moat\s*\n\s*Rating:\s*\*\*.*?\*\*\s*\n\s*Rationale:\s*(.*?)(?:\n\n|\n##|\n###|$)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if moat_rat_match:
            moat_rationale = moat_rat_match.group(1).strip()

        # Margin Outlook
        margin_match = re.search(
            r"### EBITA Margin Outlook\s*\n\s*Outlook:\s*\*\*(.*?)\*\*",
            content,
            re.IGNORECASE,
        )
        if margin_match:
            margin_outlook = margin_match.group(1).strip()
        margin_mag_match = re.search(
            r"### EBITA Margin Outlook\s*\n\s*Outlook:\s*\*\*.*?\*\*\s*\n\s*Magnitude:\s*\*\*(.*?)\*\*",
            content,
            re.IGNORECASE,
        )
        if margin_mag_match:
            margin_mag = margin_mag_match.group(1).strip()
        margin_rat_match = re.search(
            r"### EBITA Margin Outlook\s*\n.*?Rationale:\s*(.*?)(?:\n\n|\n##|\n###|$)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if margin_rat_match:
            margin_rationale = margin_rat_match.group(1).strip()

        # Growth Outlook
        growth_match = re.search(
            r"### Organic Growth Outlook\s*\n\s*Outlook:\s*\*\*(.*?)\*\*",
            content,
            re.IGNORECASE,
        )
        if growth_match:
            growth_outlook = growth_match.group(1).strip()
        growth_mag_match = re.search(
            r"### Organic Growth Outlook\s*\n\s*Outlook:\s*\*\*.*?\*\*\s*\n\s*Magnitude:\s*\*\*(.*?)\*\*",
            content,
            re.IGNORECASE,
        )
        if growth_mag_match:
            growth_mag = growth_mag_match.group(1).strip()
        growth_rat_match = re.search(
            r"### Organic Growth Outlook\s*\n.*?Rationale:\s*(.*?)(?:\n\n|\n##|\n###|$)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if growth_rat_match:
            growth_rationale = growth_rat_match.group(1).strip()

        return {
            "moat": moat,
            "moat_rationale": moat_rationale,
            "margin_outlook": margin_outlook,
            "margin_mag": margin_mag,
            "margin_rationale": margin_rationale,
            "growth_outlook": growth_outlook,
            "growth_mag": growth_mag,
            "growth_rationale": growth_rationale,
        }

    def parse_financial_summary(self, content: str) -> Dict[str, str]:
        """Parse values from the Financial Summary markdown table."""
        metrics = {}
        match = re.search(
            r"## Financial Summary\s*\n(.*?)(?:\n---|\n##|$)", content, re.DOTALL
        )
        if match:
            table_text = match.group(1)
            for line in table_text.split("\n"):
                if "|" in line and "---" not in line and "Metric" not in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 3:
                        metric_name = parts[1].replace("**", "").strip()
                        metric_val = parts[2].replace("**", "").strip()
                        metrics[metric_name] = metric_val
        return metrics

    def deduce_q4_financials(
        self, quarterly: List[Dict[str, Any]], annual: List[Dict[str, Any]]
    ) -> None:
        """Deduce missing Q4 data from Annual figures (Annual minus Q1-Q3)."""
        # Group quarters by year
        quarters_by_year = {}
        for q in quarterly:
            period = q.get("period", "")
            if "-" in period:
                yr, qtr = period.split("-")
                quarters_by_year.setdefault(yr, {})[qtr] = q

        for ann in annual:
            yr = ann.get("period", "")
            if not yr or yr == "YYYY":
                continue

            qtrs = quarters_by_year.get(yr, {})
            # Check if we have Q1, Q2, and Q3, but NOT Q4
            if "Q1" in qtrs and "Q2" in qtrs and "Q3" in qtrs and "Q4" not in qtrs:
                try:
                    q1, q2, q3 = qtrs["Q1"], qtrs["Q2"], qtrs["Q3"]

                    def get_float(d, key):
                        val_str = d.get(key, "0")
                        cleaned = (
                            val_str.replace(",", "")
                            .replace("%", "")
                            .replace("$", "")
                            .replace("x", "")
                            .strip()
                        )
                        try:
                            return float(cleaned)
                        except ValueError:
                            return 0.0

                    # Calculate Q4 values by subtraction
                    q4_rev = (
                        get_float(ann, "Revenue")
                        - get_float(q1, "Revenue")
                        - get_float(q2, "Revenue")
                        - get_float(q3, "Revenue")
                    )
                    q4_ebita = (
                        get_float(ann, "EBITA")
                        - get_float(q1, "EBITA")
                        - get_float(q2, "EBITA")
                        - get_float(q3, "EBITA")
                    )
                    q4_nopat = (
                        get_float(ann, "NOPAT")
                        - get_float(q1, "NOPAT")
                        - get_float(q2, "NOPAT")
                        - get_float(q3, "NOPAT")
                    )

                    # Point-in-time metrics copy from Annual
                    q4_ic = get_float(ann, "Invested Capital")
                    q4_basic = get_float(ann, "Basic Shares Outstanding")
                    q4_diluted = get_float(ann, "Diluted Shares Outstanding")

                    # Derived rates
                    q4_margin = (q4_ebita / q4_rev * 100.0) if q4_rev > 0 else 0.0
                    q4_turnover = (q4_rev * 4.0 / q4_ic) if q4_ic != 0.0 else 0.0
                    q4_roic = (q4_nopat * 4.0 / q4_ic * 100.0) if q4_ic != 0.0 else 0.0

                    q4_entry = {
                        "period": f"{yr}-Q4",
                        "date": ann.get("date", ""),
                        "document": f"Deducted from {ann.get('document', 'Annual Filing')}",
                        "Revenue": f"{q4_rev:,.2f}",
                        "EBITA": f"{q4_ebita:,.2f}",
                        "EBITA Margin": f"{q4_margin:.2f}%",
                        "NOPAT": f"{q4_nopat:,.2f}",
                        "Invested Capital": f"{q4_ic:,.2f}",
                        "Capital Turnover": f"{q4_turnover:.2f}x",
                        "ROIC": f"{q4_roic:.2f}%",
                        "Basic Shares Outstanding": f"{q4_basic:,.0f}",
                        "Diluted Shares Outstanding": f"{q4_diluted:,.0f}",
                        "Simple Revenue Growth": "0.00%",
                        "Organic Revenue Growth": "0.00%",
                        "Adjusted Tax Rate": ann.get("Adjusted Tax Rate", "0.00%"),
                    }
                    quarterly.append(q4_entry)
                    formatting.print_success(
                        f"Deduced Q4 financials for FY {yr} successfully."
                    )
                except Exception as e:
                    formatting.print_warning(
                        f"Failed to deduce Q4 financials for FY {yr}: {e}"
                    )

    def write_analyst_views(self, path: Path, entries: List[Dict[str, str]]) -> None:
        lines = [
            "# Analyst Views History\n",
            "| Date | Document | Economic Moat | Moat Rationale | Margin Outlook | Margin Magnitude | Margin Rationale | Growth Outlook | Growth Magnitude | Growth Rationale |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for e in entries:
            lines.append(
                f"| {e['date']} | [{e['document']}](../4_extracted_data/{e['document']}) | "
                f"{e['moat']} | {e['moat_rationale']} | {e['margin_outlook']} | {e['margin_mag']} | {e['margin_rationale']} | "
                f"{e['growth_outlook']} | {e['growth_mag']} | {e['growth_rationale']} |"
            )
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def write_news_trend(self, path: Path, entries: List[Dict[str, str]]) -> None:
        lines = [
            "# News and Press Trends\n",
            "| Date | Document | Summary |",
            "|---|---|---|",
        ]
        for e in entries:
            summary_clean = e["summary"].replace("\n", " ")
            lines.append(
                f"| {e['date']} | [{e['document']}](../4_extracted_data/{e['document']}) | {summary_clean} |"
            )
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def write_transcript_trend(self, path: Path, entries: List[Dict[str, str]]) -> None:
        lines = [
            "# Conference Call Transcript Trends\n",
            "| Date | Document | Key Themes & Summaries |",
            "|---|---|---|",
        ]
        for e in entries:
            summary_clean = e["summary"].replace("\n", " ")
            lines.append(
                f"| {e['date']} | [{e['document']}](../4_extracted_data/{e['document']}) | {summary_clean} |"
            )
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def write_financials(
        self, path: Path, entries: List[Dict[str, str]], is_quarterly: bool
    ) -> None:
        # Sort quarterly/annual entries chronologically
        entries.sort(key=lambda x: x.get("period", ""))

        lines = [
            f"# Historical Financials - {'Quarterly' if is_quarterly else 'Annual'}\n",
            "| Time Period | Period End | Revenue | EBITA | EBITA Margin | Adj Tax Rate | NOPAT | Invested Capital | Capital Turnover | ROIC | Organic Growth | Source Document |",
            "|-------------|-----------|---------|-------|--------------|-------------|-------|-----------------|------------------|------|----------------|-----------------|",
        ]
        for e in entries:
            source_doc = e["document"]
            doc_link = (
                f"[{source_doc}](../4_extracted_data/{source_doc})"
                if "Deducted" not in source_doc
                else source_doc
            )
            lines.append(
                f"| {e.get('period', '')} | {e.get('date', '')} | {e.get('Revenue', '0.0')} | {e.get('EBITA', '0.0')} | "
                f"{e.get('EBITA Margin', '0.0%')} | {e.get('Adjusted Tax Rate', '0.0%')} | {e.get('NOPAT', '0.0')} | "
                f"{e.get('Invested Capital', '0.0')} | {e.get('Capital Turnover', '0.0x')} | {e.get('ROIC', '0.0%')} | "
                f"{e.get('Organic Revenue Growth', '0.0%')} | {doc_link} |"
            )
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
