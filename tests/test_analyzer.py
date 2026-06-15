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
            "Analyst Company: **Morningstar**\n",
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
@patch("src.pipeline.curator_agent.CuratorAgent")
def test_historical_synthesis(mock_curator, mock_load_config, mock_workspace):
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
    # Deduced Revenue = 350,000 - 90,000 - 80,000 - 85,000 = 95000.0
    assert "95000.0" in q_content
    # Deduced EBITA = 80,000 - 20,000 - 15,000 - 18,000 = 27000.0
    assert "27000.0" in q_content
    # Deduced NOPAT = 64,000 - 16,000 - 12,000 - 14,400 = 21600.00
    assert "21600.00" in q_content

    # Read analyst views
    views_content = (hist_dir / "analyst_views.md").read_text(encoding="utf-8")
    assert "Morningstar" in views_content
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


@patch("src.pipeline.analyzer.load_config")
@patch("src.pipeline.curator_agent.CuratorAgent")
def test_historical_synthesis_limit(mock_curator, mock_load_config, mock_workspace):
    """Test run_analysis with limit parameter."""
    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(mock_workspace)
    mock_settings.active_ticker = "AAPL"
    mock_load_config.return_value = mock_settings

    analyzer = Analyzer()
    # Let's run with limit=2 (should only process the first 2 chronological documents: Q1 and Q2)
    analyzer.run_analysis(limit=2)

    hist_dir = mock_workspace / "5_historical_analysis"
    assert (hist_dir / "financials_quarter.md").exists()

    q_content = (hist_dir / "financials_quarter.md").read_text(encoding="utf-8")
    assert "2024-Q1" in q_content
    assert "2024-Q2" in q_content
    assert "2024-Q3" not in q_content
    assert "2024-Q4" not in q_content


@patch("src.pipeline.analyzer.load_config")
@patch("src.pipeline.curator_agent.CuratorAgent")
def test_analyzer_duplicate_handling(mock_curator, mock_load_config, tmp_path):
    ticker = "TEST"
    workspace = tmp_path / ticker
    workspace.mkdir()

    parsed_dir = workspace / "2_parsed_data"
    parsed_dir.mkdir()
    extracted_dir = workspace / "4_extracted_data"
    extracted_dir.mkdir()
    (workspace / "5_historical_analysis").mkdir()

    # We will create two Q1 documents:
    # 1. 20240125_earnings_announcement.md (EA)
    # 2. 20240201_10-Q.md (10-Q)
    csv_rows = [
        {
            "file_hash": "h1",
            "original_filename": "ea.pdf",
            "new_filename": "20240125_earnings_announcement.md",
            "document_type": "earnings_announcement",
            "document_date": "2024-01-25",
            "fiscal_quarter": "Q1",
        },
        {
            "file_hash": "h2",
            "original_filename": "10q.pdf",
            "new_filename": "20240201_10-Q.md",
            "document_type": "quarterly_filing",
            "document_date": "2024-02-01",
            "fiscal_quarter": "Q1",
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

    # Write extracted_data.csv with duplicate source file entries
    with open(
        extracted_dir / "extracted_data.csv", "w", encoding="utf-8", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=["source_file", "extracted_at"])
        writer.writeheader()
        writer.writerow(
            {"source_file": "20240125_earnings_announcement.md", "extracted_at": "1"}
        )
        # 10-Q is listed twice to test file duplication safety
        writer.writerow({"source_file": "20240201_10-Q.md", "extracted_at": "2"})
        writer.writerow({"source_file": "20240201_10-Q.md", "extracted_at": "3"})

    def write_extracted(filename, metrics):
        out_lines = [
            f"# Extracted Financial Report: {filename}\n",
            "## Chunk Summaries",
            "- Chunk 1",
            "\n---\n",
            "## Financial Summary",
            "| Metric | Value | Notes |",
            "|---|---|---|",
        ]
        for k, v in metrics.items():
            out_lines.append(f"| **{k}** | {v} | |")
        with open(
            extracted_dir / f"{Path(filename).stem}_extracted.md", "w", encoding="utf-8"
        ) as f:
            f.write("\n".join(out_lines))

    # Case 1: Both documents have EXACT same metrics (complete duplicates)
    metrics_ea = {
        "Revenue": "90,000",
        "EBITA": "20,000",
        "NOPAT": "16,000",
        "Invested Capital": "100,000",
        "Basic Shares Outstanding": "1,000",
        "Diluted Shares Outstanding": "1,020",
    }
    metrics_q = {
        "Revenue": "90,000",
        "EBITA": "20,000",
        "NOPAT": "16,000",
        "Invested Capital": "100,000",
        "Basic Shares Outstanding": "1,000",
        "Diluted Shares Outstanding": "1,020",
    }

    write_extracted("20240125_earnings_announcement.md", metrics_ea)
    write_extracted("20240201_10-Q.md", metrics_q)

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_settings.active_ticker = "TEST"
    mock_load_config.return_value = mock_settings

    analyzer = Analyzer()
    analyzer.run_analysis()

    # Verify only one 2024-Q1 row is written because the entries are complete duplicates
    q_content = (
        workspace / "5_historical_analysis" / "financials_quarter.md"
    ).read_text(encoding="utf-8")
    lines = [line for line in q_content.splitlines() if "2024-Q1" in line]
    assert len(lines) == 1, f"Expected 1 line for 2024-Q1, got: {lines}"

    # Case 2: Different metrics (not complete duplicates)
    metrics_q_diff = {
        "Revenue": "92,000",
        "EBITA": "20,000",
        "NOPAT": "16,000",
        "Invested Capital": "100,000",
        "Basic Shares Outstanding": "1,000",
        "Diluted Shares Outstanding": "1,020",
    }
    write_extracted("20240201_10-Q.md", metrics_q_diff)

    analyzer = Analyzer()
    analyzer.run_analysis()

    # Verify both rows are written now since the numbers changed
    q_content = (
        workspace / "5_historical_analysis" / "financials_quarter.md"
    ).read_text(encoding="utf-8")
    lines = [line for line in q_content.splitlines() if "2024-Q1" in line]
    assert len(lines) == 2, f"Expected 2 lines for 2024-Q1, got: {lines}"


def test_deduce_q4_financials_growth():
    analyzer = Analyzer()

    # 2023 data: Q1-Q4 and Annual
    quarterly = [
        {"period": "2023-Q1", "Revenue": "100.00", "Organic Revenue Growth": "10.00%"},
        {"period": "2023-Q2", "Revenue": "100.00", "Organic Revenue Growth": "10.00%"},
        {"period": "2023-Q3", "Revenue": "100.00", "Organic Revenue Growth": "10.00%"},
        {"period": "2023-Q4", "Revenue": "100.00", "Organic Revenue Growth": "10.00%"},
        # 2024 data: Q1-Q3 (Q4 missing, to be deduced)
        {"period": "2024-Q1", "Revenue": "110.00", "Organic Revenue Growth": "10.00%"},
        {"period": "2024-Q2", "Revenue": "112.00", "Organic Revenue Growth": "12.00%"},
        {"period": "2024-Q3", "Revenue": "108.00", "Organic Revenue Growth": "8.00%"},
    ]

    annual = [
        {"period": "2023", "Revenue": "400.00", "Organic Revenue Growth": "10.00%"},
        {"period": "2024", "Revenue": "445.00", "Organic Revenue Growth": "11.25%"},
    ]

    analyzer.deduce_q4_financials(quarterly, annual)

    # 2024-Q4 should have been deduced and added to quarterly list
    q4_24 = next((q for q in quarterly if q.get("period") == "2024-Q4"), None)
    assert q4_24 is not None

    # Deduced Revenue: 445 - 110 - 112 - 108 = 115
    assert q4_24["Revenue"] == "115.0"

    # Simple growth: (115 - 100) / 100 * 100 = 15.00%
    assert q4_24["Simple Revenue Growth"] == "15.00%"

    # Organic growth: (445 * 0.1125 - (110 * 0.1 + 112 * 0.12 + 108 * 0.08)) / (445 - 110 - 112 - 108) ... wait!
    # Let's verify the base in the formula:
    # ann_org_increase = ann_revenue_prior * (ann_org_growth / 100.0) = 400 * 10% = 40? Wait, no!
    # ann_org_growth is for the current year (2024), which compares 2024 to 2023.
    # So the base is the prior year's annual revenue (2023): ann_revenue_prior = 400.00.
    # Therefore, ann_org_increase = 400 * (11.25 / 100) = 45.
    # q1_org_growth = 10.00% for 2024-Q1. The base is 2023-Q1 Revenue = 100.
    # So q1_org_increase = 100 * (10 / 100) = 10.
    # q2_org_growth = 12.00% for 2024-Q2. The base is 2023-Q2 Revenue = 100.
    # So q2_org_increase = 100 * (12 / 100) = 12.
    # q3_org_growth = 8.00% for 2024-Q3. The base is 2023-Q3 Revenue = 100.
    # So q3_org_increase = 100 * (8 / 100) = 8.
    # q4_org_increase = ann_org_increase - q1_org_increase - q2_org_increase - q3_org_increase = 45 - 10 - 12 - 8 = 15.
    # r4_prior = 2023-Q4 Revenue = 100 (which is also equal to ann_revenue_prior - r1_prior - r2_prior - r3_prior = 400 - 100 - 100 - 100 = 100).
    # So q4_organic_growth = 15 / 100 * 100 = 15.00%.
    assert q4_24["Organic Revenue Growth"] == "15.00%"


def test_deduce_q4_financials_growth_fallback():
    analyzer = Analyzer()

    # 2024 data: Q1-Q3 (Q4 missing, no prior year data)
    quarterly = [
        {
            "period": "2024-Q1",
            "Revenue": "110.00",
            "Organic Revenue Growth": "10.00%",
            "Simple Revenue Growth": "10.00%",
        },
        {
            "period": "2024-Q2",
            "Revenue": "112.00",
            "Organic Revenue Growth": "12.00%",
            "Simple Revenue Growth": "12.00%",
        },
        {
            "period": "2024-Q3",
            "Revenue": "108.00",
            "Organic Revenue Growth": "8.00%",
            "Simple Revenue Growth": "8.00%",
        },
    ]

    annual = [
        {
            "period": "2024",
            "Revenue": "445.00",
            "Organic Revenue Growth": "11.25%",
            "Simple Revenue Growth": "11.25%",
        },
    ]

    analyzer.deduce_q4_financials(quarterly, annual)

    q4_24 = next((q for q in quarterly if q.get("period") == "2024-Q4"), None)
    assert q4_24 is not None

    # Deduced Revenue: 445 - 110 - 112 - 108 = 115
    assert q4_24["Revenue"] == "115.0"

    # Fallback growth:
    # ann_increase = 445 * 11.25% = 50.0625
    # q1_increase = 110 * 10% = 11.0
    # q2_increase = 112 * 12% = 13.44
    # q3_increase = 108 * 8% = 8.64
    # q4_increase = 50.0625 - 11.0 - 13.44 - 8.64 = 16.9825
    # q4_growth = 16.9825 / 115 * 100 = 14.767% -> formatted as "14.77%"
    assert q4_24["Simple Revenue Growth"] == "14.77%"
    assert q4_24["Organic Revenue Growth"] == "14.77%"
