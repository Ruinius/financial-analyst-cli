import csv
import json
from pathlib import Path
from unittest.mock import patch
import pytest

from src.core.config import Settings
from src.pipeline.ingester import (
    compute_sha256,
    html_to_markdown,
    chunk_text,
    Ingester,
)
from src.pipeline.queue import JobQueue


@pytest.fixture
def mock_settings(tmp_path):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "1_ingest_data").mkdir()
    (workspace / "2_parsed_data").mkdir()
    (workspace / "3_archived_data").mkdir()

    settings = Settings(
        full_name="Test User",
        email="test@example.com",
        project_name="TestProject",
        primary_llm_api_key="sk-testkey",
        base_workspace_dir=str(tmp_path),
        active_ticker="AAPL",
        active_workspace_path=str(workspace),
    )
    return settings


def test_compute_sha256(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world", encoding="utf-8")
    h = compute_sha256(f)
    assert len(h) == 64
    # Constant hashing
    assert h == compute_sha256(f)


def test_html_to_markdown():
    html = """
    <html>
      <body>
        <h1>Title</h1>
        <p>This is a paragraph.</p>
        <table>
          <tr><th>Col1</th><th>Col2</th></tr>
          <tr><td>Val1</td><td>Val2</td></tr>
        </table>
      </body>
    </html>
    """
    md = html_to_markdown(html)
    assert "# Title" in md
    assert "This is a paragraph." in md
    assert "| Col1 | Col2 |" in md
    assert "| --- | --- |" in md
    assert "| Val1 | Val2 |" in md


def test_chunk_text():
    text = "a\n" * 3000
    chunks = chunk_text(text, max_chars=1000)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1000


@patch("src.services.llm_client.load_config")
@patch("src.pipeline.ingester.load_config")
@patch("src.services.llm_client.LLMClient.generate")
def test_ingestion_flow(
    mock_llm, mock_load_config, mock_llm_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings
    mock_llm_load_config.return_value = mock_settings

    # Mock LLM returning metadata JSON
    mock_llm.return_value = json.dumps(
        {
            "document_date": "2023-09-30",
            "document_type": "annual_filing",
            "fiscal_quarter": "FY",
        }
    )

    workspace = Path(mock_settings.active_workspace_path)
    raw_file = workspace / "1_ingest_data" / "filing.htm"
    raw_file.write_text(
        "<h1>Annual Report</h1><p>Financial details...</p>", encoding="utf-8"
    )

    ingester = Ingester()
    ingester.run_ingestion()

    # Verify document is parsed, renamed, and archived
    parsed_file = workspace / "2_parsed_data" / "20230930_annual_filing.md"
    assert parsed_file.exists()

    archived_file = workspace / "3_archived_data" / "20230930_annual_filing.htm"
    assert archived_file.exists()
    assert not raw_file.exists()

    # Verify parsed_data.csv is updated
    registry_path = workspace / "2_parsed_data" / "parsed_data.csv"
    assert registry_path.exists()
    with open(registry_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["new_filename"] == "20230930_annual_filing.md"
        assert rows[0]["document_type"] == "annual_filing"
        assert rows[0]["fiscal_quarter"] == "FY"


def test_job_queue():
    queue = JobQueue(retries=1, initial_delay=0.1)
    calls = []

    def dummy_job(arg1):
        calls.append(arg1)
        return arg1 * 2

    queue.add_job(dummy_job, 5)
    queue.add_job(dummy_job, 10)
    results = queue.run()

    assert calls == [5, 10]
    assert results == [10, 20]


@patch("src.services.llm_client.load_config")
@patch("src.pipeline.ingester.load_config")
@patch("src.services.llm_client.LLMClient.generate")
def test_ingestion_limit(
    mock_llm, mock_load_config, mock_llm_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings
    mock_llm_load_config.return_value = mock_settings

    mock_llm.side_effect = [
        json.dumps(
            {
                "document_date": f"2023-09-2{i}",
                "document_type": "annual_filing",
                "fiscal_quarter": "FY",
            }
        )
        for i in range(3)
    ]

    workspace = Path(mock_settings.active_workspace_path)
    # Write 3 files
    for i in range(3):
        raw_file = workspace / "1_ingest_data" / f"filing_{i}.htm"
        raw_file.write_text(f"<h1>Report {i}</h1>", encoding="utf-8")

    ingester = Ingester()
    # Process only 2 files
    ingester.run_ingestion(limit=2)

    # Verify that exactly 2 parsed files were created
    parsed_files = list((workspace / "2_parsed_data").glob("*.md"))
    assert len(parsed_files) == 2
