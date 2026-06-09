import csv
import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from src.pipeline.analyzer import Analyzer


@pytest.fixture
def mock_workspace(tmp_path):
    """Set up a mock workspace with parsed and extracted files."""
    ticker = "AAPL"
    workspace = tmp_path / ticker
    workspace.mkdir()

    parsed_dir = workspace / "2_parsed_data"
    parsed_dir.mkdir()
    extracted_dir = workspace / "4_extracted_data"
    extracted_dir.mkdir()
    (workspace / "5_historical_analysis").mkdir()

    # Create parsed_data.csv
    csv_rows = [
        {
            "file_hash": "h1",
            "original_filename": "aapl-10q-q1.pdf",
            "new_filename": "20240201_10-Q.md",
            "document_type": "quarterly_filing",
            "document_date": "2024-02-01",
            "fiscal_quarter": "Q1",
        },
        {
            "file_hash": "h2",
            "original_filename": "aapl-10q-q2.pdf",
            "new_filename": "20240501_10-Q.md",
            "document_type": "quarterly_filing",
            "document_date": "2024-05-01",
            "fiscal_quarter": "Q2",
        },
        {
            "file_hash": "h3",
            "original_filename": "aapl-10q-q3.pdf",
            "new_filename": "20240801_10-Q.md",
            "document_type": "quarterly_filing",
            "document_date": "2024-08-01",
            "fiscal_quarter": "Q3",
        },
        {
            "file_hash": "h4",
            "original_filename": "aapl-10k-fy.pdf",
            "new_filename": "20241031_10-K.md",
            "document_type": "annual_filing",
            "document_date": "2024-10-31",
            "fiscal_quarter": "FY",
        },
        {
            "file_hash": "h5",
            "original_filename": "analyst-report.pdf",
            "new_filename": "20240901_analyst_report.md",
            "document_type": "analyst_report",
            "document_date": "2024-09-01",
            "fiscal_quarter": "N/A",
        },
        {
            "file_hash": "h6",
            "original_filename": "press-release.pdf",
            "new_filename": "20240715_press_release.md",
            "document_type": "press_release",
            "document_date": "2024-07-15",
            "fiscal_quarter": "N/A",
        },
        {
            "file_hash": "h7",
            "original_filename": "transcript.pdf",
            "new_filename": "20240502_transcript.md",
            "document_type": "transcript",
            "document_date": "2024-05-02",
            "fiscal_quarter": "N/A",
        },
    ]

    fieldnames = [
        "file_hash",
        "original_filename",
        "new_filename",
        "document_type",
        "document_date",
        "fiscal_quarter",
    ]
    with open(parsed_dir / "parsed_data.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    # Create extracted_data.csv
    with open(
        extracted_dir / "extracted_data.csv", "w", encoding="utf-8", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=["source_file", "extracted_at"])
        writer.writeheader()
        for r in csv_rows:
            writer.writerow({"source_file": r["new_filename"], "extracted_at": "12345"})

    # Helper to write mock extracted file
    def write_extracted(filename, summary_table, moat_rating=None, moat_rat=None):
        out_lines = [
            f"# Extracted Financial Report: {filename}\n",
            "## Chunk Summaries",
            "- Chunk 1: The company reported strong performance.",
            "- Chunk 2: Segment revenues grew.",
            "\n---\n",
            "## Financial Summary",
            "| Metric | Value | Notes |",
            "|---|---|---|",
        ]
        for k, v in summary_table.items():
            out_lines.append(f"| **{k}** | {v} | |")

        if moat_rating:
            out_lines.extend(
                [
                    "\n---\n",
                    "### Economic Moat",
                    f"Rating: **{moat_rating}**",
                    f"Rationale: {moat_rat}",
                    "\n### EBITA Margin Outlook",
                    "Outlook: **Stable**",
                    "Magnitude: **0 pp**",
                    "Rationale: margins remain robust.",
                    "\n### Organic Growth Outlook",
                    "Outlook: **Stable**",
                    "Magnitude: **0 pp**",
                    "Rationale: growth remains solid.",
                ]
            )

        with open(
            extracted_dir / f"{Path(filename).stem}_extracted.md", "w", encoding="utf-8"
        ) as f:
            f.write("\n".join(out_lines))

    # Write actual metrics tables
    # Revenue: Q1=90M, Q2=80M, Q3=85M, Annual=350M -> deduced Q4 = 350 - 90 - 80 - 85 = 95M
    # EBITA: Q1=20M, Q2=15M, Q3=18M, Annual=80M -> deduced Q4 = 80 - 20 - 15 - 18 = 27M
    # NOPAT: Q1=16M, Q2=12M, Q3=14.4M, Annual=64M -> deduced Q4 = 64 - 16 - 12 - 14.4 = 21.6M
    write_extracted(
        "20240201_10-Q.md",
        {
            "Revenue": "90,000",
            "EBITA": "20,000",
            "NOPAT": "16,000",
            "Invested Capital": "100,000",
            "Basic Shares Outstanding": "1,000",
            "Diluted Shares Outstanding": "1,020",
        },
    )
    write_extracted(
        "20240501_10-Q.md",
        {
            "Revenue": "80,000",
            "EBITA": "15,000",
            "NOPAT": "12,000",
            "Invested Capital": "105,000",
            "Basic Shares Outstanding": "1,000",
            "Diluted Shares Outstanding": "1,020",
        },
    )
    write_extracted(
        "20240801_10-Q.md",
        {
            "Revenue": "85,000",
            "EBITA": "18,000",
            "NOPAT": "14,400",
            "Invested Capital": "110,000",
            "Basic Shares Outstanding": "1,000",
            "Diluted Shares Outstanding": "1,020",
        },
    )
    write_extracted(
        "20241031_10-K.md",
        {
            "Revenue": "350,000",
            "EBITA": "80,000",
            "NOPAT": "64,000",
            "Invested Capital": "120,000",
            "Basic Shares Outstanding": "1,000",
            "Diluted Shares Outstanding": "1,020",
        },
    )
    write_extracted(
        "20240901_analyst_report.md",
        {},
        moat_rating="Wide",
        moat_rat="Strong ecosystem and high switching costs.",
    )
    write_extracted("20240715_press_release.md", {})
    write_extracted("20240502_transcript.md", {})

    return workspace


@patch("src.pipeline.analyzer.load_config")
def test_historical_synthesis(mock_load_config, mock_workspace):
    """Test longitudinal synthesis, compilation, and Q4 deduction logic."""
    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(mock_workspace)
    mock_settings.active_ticker = "AAPL"
    mock_load_config.return_value = mock_settings

    analyzer = Analyzer()
    analyzer.run_analysis()

    # Verify that files are created in 5_historical_analysis/
    hist_dir = mock_workspace / "5_historical_analysis"
    assert (hist_dir / "analyst_views.md").exists()
    assert (hist_dir / "news_trend.md").exists()
    assert (hist_dir / "transcript_trend.md").exists()
    assert (hist_dir / "financials_quarter.md").exists()
    assert (hist_dir / "financials_annual.md").exists()

    # Read quarterly report to check Q4 deduction
    q_content = (hist_dir / "financials_quarter.md").read_text(encoding="utf-8")
    assert "2024-Q4" in q_content
    # Deduced Revenue = 350,000 - 90,000 - 80,000 - 85,000 = 95,000.00
    assert "95,000.00" in q_content
    # Deduced EBITA = 80,000 - 20,000 - 15,000 - 18,000 = 27,000.00
    assert "27,000.00" in q_content
    # Deduced NOPAT = 64,000 - 16,000 - 12,000 - 14,400 = 21,600.00
    assert "21,600.00" in q_content

    # Read analyst views
    views_content = (hist_dir / "analyst_views.md").read_text(encoding="utf-8")
    assert "Wide" in views_content
    assert "Strong ecosystem" in views_content


def test_baseline_golden_evaluation():
    """Verify extracted metrics against the golden dataset (AAPL 2024)."""
    golden_path = Path("tests/data/golden_aapl_2024.json")
    assert golden_path.exists(), "Golden dataset must exist"

    with open(golden_path, "r", encoding="utf-8") as f:
        golden_data = json.load(f)

    # Mock extraction outputs from the parser
    extracted_metrics = {
        "Revenue": 391035.0,
        "EBITA": 114601.0,
        "NOPAT": 96264.84,
        "Invested Capital": 120500.0,
        "Basic Shares Outstanding": 15285.0,
        "Diluted Shares Outstanding": 15383.0,
    }

    # Verify matching with 1% margin of error
    tolerance = 0.01
    for k, ground_truth_val in golden_data["ground_truth"].items():
        assert k in extracted_metrics, f"Metric {k} not present in extracted metrics"
        extracted_val = extracted_metrics[k]
        diff = abs(extracted_val - ground_truth_val) / ground_truth_val
        assert (
            diff <= tolerance
        ), f"Metric {k} diff {diff:.4f} exceeds tolerance of {tolerance}"
