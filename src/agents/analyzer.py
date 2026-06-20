import csv
import logging
import re
from pathlib import Path
from typing import Dict, List, Any

from src.core.config import load_config
import src.utils.formatting as formatting

logger = logging.getLogger(__name__)


class Analyzer:
    def __init__(self):
        self.settings = load_config()

    def run_analysis(self, limit: int = None) -> None:
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
        seen_source_files = set()
        with open(extracted_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                source_file = row.get("source_file")
                if source_file and source_file in doc_metadata:
                    if source_file not in seen_source_files:
                        extracted_files.append(source_file)
                        seen_source_files.add(source_file)

        # Sort extracted files by document_date chronologically
        def get_doc_date(fname):
            meta = doc_metadata[fname]
            return meta.get("document_date", "0000-00-00")

        extracted_files.sort(key=get_doc_date)

        if limit is not None:
            skipped_files = extracted_files[limit:]
            extracted_files = extracted_files[:limit]
            for f in skipped_files:
                formatting.print_info(f"Skipped due to limit: {f}")

        import typer
        from collections import Counter
        from src.agents.extractor_orchestrator import Extractor

        re_run_files = set()

        while True:
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

                # Extract year from fiscal_year or document_date fallback
                year = meta.get("fiscal_year", "N/A")
                if not year or year == "N/A" or year == "YYYY":
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
                    if not self._is_duplicate_entry(view_entry, analyst_views_entries):
                        analyst_views_entries.append(view_entry)

                elif doc_type in ["press_release", "news_article", "other"]:
                    news_entry = {
                        "date": doc_date,
                        "document": extracted_filename,
                        "summary": chunk_summaries,
                    }
                    if not self._is_duplicate_entry(news_entry, news_entries):
                        news_entries.append(news_entry)

                elif doc_type == "transcript":
                    transcript_entry = {
                        "date": doc_date,
                        "document": extracted_filename,
                        "summary": chunk_summaries,
                    }
                    if not self._is_duplicate_entry(
                        transcript_entry, transcript_entries
                    ):
                        transcript_entries.append(transcript_entry)

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
                    fin_metrics["src_file"] = src_file

                    # Extract currency and unit from content
                    currency = "USD"
                    unit = "Millions"
                    curr_match = re.search(
                        r"\*\*Currency\*\*:\s*([A-Za-z]{3})", content
                    )
                    if curr_match:
                        currency = curr_match.group(1).upper()
                    else:
                        curr_match_loose = re.search(
                            r"Currency:\s*([A-Za-z]{3})", content
                        )
                        if curr_match_loose:
                            currency = curr_match_loose.group(1).upper()

                    unit_match = re.search(r"\*\*Unit\*\*:\s*([A-Za-z0-9\s]+)", content)
                    if unit_match:
                        unit = unit_match.group(1).strip()
                    else:
                        unit_match_loose = re.search(
                            r"Unit:\s*([A-Za-z0-9\s]+)", content
                        )
                        if unit_match_loose:
                            unit = unit_match_loose.group(1).strip()

                    fin_metrics["currency"] = currency
                    fin_metrics["unit"] = unit

                    if doc_type == "annual_filing" or fiscal_quarter == "FY":
                        fin_metrics["period"] = year
                        if not self._is_duplicate_entry(fin_metrics, annual_financials):
                            annual_financials.append(fin_metrics)
                    else:
                        fin_metrics["period"] = f"{year}-{fiscal_quarter}"
                        if not self._is_duplicate_entry(
                            fin_metrics, quarterly_financials
                        ):
                            quarterly_financials.append(fin_metrics)

            # 3. Deduce Q4 financials if Q1-Q3 and Annual are present
            self.deduce_q4_financials(quarterly_financials, annual_financials)

            # 4. Check for currency/unit inconsistencies
            all_actuals = [
                e for e in quarterly_financials if "Deducted" not in e["document"]
            ] + annual_financials
            inconsistency_resolved = False

            if all_actuals:
                currencies = [e.get("currency", "USD") for e in all_actuals]
                units = [e.get("unit", "Millions") for e in all_actuals]

                expected_currency = Counter(currencies).most_common(1)[0][0]
                expected_unit = Counter(units).most_common(1)[0][0]

                inconsistent_quarters = []
                for q in quarterly_financials:
                    if "Deducted" in q["document"]:
                        continue
                    curr = q.get("currency", "USD")
                    unit = q.get("unit", "Millions")
                    if curr != expected_currency or unit != expected_unit:
                        inconsistent_quarters.append(q)

                if inconsistent_quarters:
                    formatting.print_warning(
                        "Currency or unit inconsistency detected among reports!"
                    )
                    for q in inconsistent_quarters:
                        if q["src_file"] in re_run_files:
                            continue
                        formatting.print_warning(
                            f"  - Quarter {q['period']}: Currency is '{q.get('currency')}' (expected '{expected_currency}'), "
                            f"Unit is '{q.get('unit')}' (expected '{expected_unit}')."
                        )
                        prompt_msg = f"Would you like to re-run extraction for quarter {q['period']} ({q['src_file']})?"
                        if typer.confirm(prompt_msg, default=True):
                            parsed_file_path = parsed_dir / q["src_file"]
                            formatting.print_info(
                                f"Re-running extraction for {q['src_file']}..."
                            )
                            extractor_inst = Extractor()
                            extractor_inst.run_extraction(
                                files_to_process=[parsed_file_path]
                            )
                            re_run_files.add(q["src_file"])
                            inconsistency_resolved = True
                            break

                    if inconsistency_resolved:
                        continue

            break

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

        # Trigger Curator Agent with historical analysis files content
        ticker = self.settings.active_ticker or "UNK"
        analysis_files_content = []
        for filename in [
            "analyst_views.md",
            "news_trend.md",
            "transcript_trend.md",
            "financials_quarter.md",
            "financials_annual.md",
        ]:
            file_path = analysis_dir / filename
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    analysis_files_content.append(
                        f"--- File: {filename} ---\n{content}\n"
                    )
                except Exception as e:
                    formatting.print_warning(
                        f"Could not read {filename} for curator: {e}"
                    )

        curator_context = "\n".join(analysis_files_content)
        from src.agents.curator_agent import CuratorAgent

        CuratorAgent(self.settings).curate(ticker, "analyze", curator_context)

        # Trigger Indexer Agent to update folder index
        try:
            from src.agents.indexer_agent import IndexerAgent

            IndexerAgent(self.settings).run_indexing(ticker)
        except Exception as e:
            logger.error(f"Failed to run indexer agent after analysis: {e}")

    def parse_chunk_summaries(self, content: str) -> str:
        """Extract summaries from the Chunk Summaries section."""
        # ⚡ Bolt Optimization: Replace O(N) re.DOTALL with fast str.find()
        start_idx = content.find("## Chunk Summaries")
        if start_idx != -1:
            start_idx = content.find("\n", start_idx)
            if start_idx != -1:
                end_idx = len(content)
                for marker in ["\n---", "\n##"]:
                    pos = content.find(marker, start_idx)
                    if pos != -1 and pos < end_idx:
                        end_idx = pos
                return content[start_idx:end_idx].strip()
        return "No chunk summaries found."

    def parse_analyst_report_fields(self, content: str) -> Dict[str, str]:
        """Parse economic moat, margin outlook, and growth outlook sections."""
        analyst_company = "Unknown"
        moat = "None"
        moat_rationale = ""
        margin_outlook = "Stable"
        margin_mag = "0 pp"
        margin_rationale = ""
        growth_outlook = "Stable"
        growth_mag = "0 pp"
        growth_rationale = ""

        # Analyst Company
        company_match = re.search(
            r"Analyst Company:\s*\*\*(.*?)\*\*", content, re.IGNORECASE
        )
        if company_match:
            analyst_company = company_match.group(1).strip()

        # ⚡ Bolt Optimization: Replace O(N) evaluation over large blocks using `str.find`
        content_lower = content.lower()

        def _extract_rationale(text_lower, original_text, header_lower):
            header_idx = text_lower.find(header_lower)
            if header_idx == -1:
                return ""

            rat_idx = text_lower.find("rationale:", header_idx)
            if rat_idx == -1:
                return ""

            # Ensure the rationale belongs to this section
            # Check if a new header starts before rationale
            next_header1 = text_lower.find("\n###", header_idx + len(header_lower))
            if next_header1 != -1 and next_header1 < rat_idx:
                return ""
            next_header2 = text_lower.find("\n## ", header_idx + len(header_lower))
            if next_header2 != -1 and next_header2 < rat_idx:
                return ""

            start_idx = rat_idx + len("rationale:")
            end_idx = len(original_text)
            for h in ["\n\n", "\n##", "\n###"]:
                pos = text_lower.find(h, start_idx)
                if pos != -1 and pos < end_idx:
                    end_idx = pos
            return original_text[start_idx:end_idx].strip()

        # Moat
        moat_match = re.search(
            r"### Economic Moat\s*\n\s*Rating:\s*\*\*(.*?)\*\*", content, re.IGNORECASE
        )
        if moat_match:
            moat = moat_match.group(1).strip()
        moat_rationale = _extract_rationale(content_lower, content, "### economic moat")

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
        margin_rationale = _extract_rationale(
            content_lower, content, "### ebita margin outlook"
        )

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
        growth_rationale = _extract_rationale(
            content_lower, content, "### organic growth outlook"
        )

        return {
            "analyst_company": analyst_company,
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
        # ⚡ Bolt Optimization: Replace O(N) re.DOTALL with fast str.find()
        start_idx = content.find("## Financial Summary")
        if start_idx != -1:
            start_idx = content.find("\n", start_idx)
            if start_idx != -1:
                end_idx = len(content)
                for marker in ["\n---", "\n##"]:
                    pos = content.find(marker, start_idx)
                    if pos != -1 and pos < end_idx:
                        end_idx = pos

                table_text = content[start_idx:end_idx]
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

        # Sort annual chronologically to ensure prior years are deduced first
        annual_sorted = sorted(annual, key=lambda x: x.get("period", ""))

        for ann in annual_sorted:
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

                    # Calculate growth rates
                    q4_simple_growth = 0.0
                    q4_organic_growth = 0.0

                    prior_yr = str(int(yr) - 1)
                    prior_qtrs = quarters_by_year.get(prior_yr, {})
                    prior_ann = next(
                        (a for a in annual if a.get("period", "") == prior_yr), None
                    )

                    if (
                        prior_ann
                        and "Q1" in prior_qtrs
                        and "Q2" in prior_qtrs
                        and "Q3" in prior_qtrs
                        and "Q4" in prior_qtrs
                    ):
                        r1_prior = get_float(prior_qtrs["Q1"], "Revenue")
                        r2_prior = get_float(prior_qtrs["Q2"], "Revenue")
                        r3_prior = get_float(prior_qtrs["Q3"], "Revenue")
                        ann_revenue_prior = get_float(prior_ann, "Revenue")
                        r4_prior = ann_revenue_prior - r1_prior - r2_prior - r3_prior

                        if r4_prior > 0:
                            q4_simple_growth = (q4_rev - r4_prior) / r4_prior * 100.0

                            ann_org_growth = get_float(ann, "Organic Revenue Growth")
                            q1_org_growth = get_float(q1, "Organic Revenue Growth")
                            q2_org_growth = get_float(q2, "Organic Revenue Growth")
                            q3_org_growth = get_float(q3, "Organic Revenue Growth")

                            ann_org_increase = ann_revenue_prior * (
                                ann_org_growth / 100.0
                            )
                            q1_org_increase = r1_prior * (q1_org_growth / 100.0)
                            q2_org_increase = r2_prior * (q2_org_growth / 100.0)
                            q3_org_increase = r3_prior * (q3_org_growth / 100.0)

                            q4_org_increase = (
                                ann_org_increase
                                - q1_org_increase
                                - q2_org_increase
                                - q3_org_increase
                            )
                            q4_organic_growth = (q4_org_increase / r4_prior) * 100.0
                    else:
                        # Fallback: calculate using current year values if prior year data is not available
                        ann_rev = get_float(ann, "Revenue")
                        r1 = get_float(q1, "Revenue")
                        r2 = get_float(q2, "Revenue")
                        r3 = get_float(q3, "Revenue")

                        if q4_rev > 0:
                            ann_org_growth = get_float(ann, "Organic Revenue Growth")
                            q1_org_growth = get_float(q1, "Organic Revenue Growth")
                            q2_org_growth = get_float(q2, "Organic Revenue Growth")
                            q3_org_growth = get_float(q3, "Organic Revenue Growth")

                            ann_org_increase = ann_rev * (ann_org_growth / 100.0)
                            q1_org_increase = r1 * (q1_org_growth / 100.0)
                            q2_org_increase = r2 * (q2_org_growth / 100.0)
                            q3_org_increase = r3 * (q3_org_growth / 100.0)

                            q4_org_increase = (
                                ann_org_increase
                                - q1_org_increase
                                - q2_org_increase
                                - q3_org_increase
                            )
                            q4_organic_growth = (q4_org_increase / q4_rev) * 100.0

                            ann_simple_growth = get_float(ann, "Simple Revenue Growth")
                            q1_simple_growth = get_float(q1, "Simple Revenue Growth")
                            q2_simple_growth = get_float(q2, "Simple Revenue Growth")
                            q3_simple_growth = get_float(q3, "Simple Revenue Growth")

                            ann_simple_increase = ann_rev * (ann_simple_growth / 100.0)
                            q1_simple_increase = r1 * (q1_simple_growth / 100.0)
                            q2_simple_increase = r2 * (q2_simple_growth / 100.0)
                            q3_simple_increase = r3 * (q3_simple_growth / 100.0)

                            q4_simple_increase = (
                                ann_simple_increase
                                - q1_simple_increase
                                - q2_simple_increase
                                - q3_simple_increase
                            )
                            q4_simple_growth = (q4_simple_increase / q4_rev) * 100.0

                    q4_entry = {
                        "period": f"{yr}-Q4",
                        "date": ann.get("date", ""),
                        "document": f"Deducted from {ann.get('document', 'Annual Filing')}",
                        "currency": ann.get("currency", "USD"),
                        "unit": ann.get("unit", "Millions"),
                        "Revenue": f"{q4_rev:.1f}",
                        "EBITA": f"{q4_ebita:.1f}",
                        "EBITA Margin": f"{q4_margin:.2f}%",
                        "NOPAT": f"{q4_nopat:.2f}",
                        "Invested Capital": f"{q4_ic:.1f}",
                        "Capital Turnover": f"{q4_turnover:.2f}x",
                        "ROIC": f"{q4_roic:.2f}%",
                        "Basic Shares Outstanding": f"{q4_basic:.1f}",
                        "Diluted Shares Outstanding": f"{q4_diluted:.1f}",
                        "Simple Revenue Growth": f"{q4_simple_growth:.2f}%",
                        "Organic Revenue Growth": f"{q4_organic_growth:.2f}%",
                        "Adjusted Tax Rate": ann.get("Adjusted Tax Rate", "0.00%"),
                    }
                    quarterly.append(q4_entry)
                    quarters_by_year.setdefault(yr, {})["Q4"] = q4_entry
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
            "| Date | Document | Analyst Company | Economic Moat | Moat Rationale | Margin Outlook | Margin Magnitude | Margin Rationale | Growth Outlook | Growth Magnitude | Growth Rationale |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for e in entries:
            company = e.get("analyst_company", "Unknown")
            lines.append(
                f"| {e['date']} | [{e['document']}](../4_extracted_data/{e['document']}) | {company} | "
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
        from collections import Counter

        # Sort quarterly/annual entries chronologically
        entries.sort(key=lambda x: x.get("period", ""))

        # Determine the dominant currency and unit across all entries
        if entries:
            currencies = [e.get("currency", "USD") for e in entries]
            units = [e.get("unit", "Millions") for e in entries]
            dominant_currency = Counter(currencies).most_common(1)[0][0]
            dominant_unit = Counter(units).most_common(1)[0][0]
        else:
            dominant_currency = "USD"
            dominant_unit = "Millions"

        lines = [
            f"# Historical Financials - {'Quarterly' if is_quarterly else 'Annual'}\n",
            f"**Currency**: {dominant_currency}",
            f"**Unit**: {dominant_unit}\n",
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

    def _is_duplicate_entry(
        self, entry: dict, existing_list: list, ignore_keys: set = None
    ) -> bool:
        if ignore_keys is None:
            ignore_keys = {"document", "date", "src_file", "currency", "unit"}
        for existing in existing_list:
            keys = (set(entry.keys()) | set(existing.keys())) - ignore_keys
            if all(entry.get(k) == existing.get(k) for k in keys):
                return True
        return False
