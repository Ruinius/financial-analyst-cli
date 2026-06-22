import csv
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from src.core.config import Settings
from src.agents.orchestrator_pipelines.ingest import (
    compute_sha256,
    html_to_markdown,
    chunk_text,
    Ingester,
)
from src.services.queue import JobQueue


@pytest.fixture(autouse=True)
def mock_curator_agent():
    with patch("src.agents.curator_agent.CuratorAgent.curate") as mock_curate:
        yield mock_curate


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
@patch("src.agents.orchestrator_pipelines.ingest.load_config")
@patch("src.agents.orchestrator_pipelines.ingest.get_llm_client")
def test_ingestion_flow(
    mock_get_llm, mock_load_config, mock_llm_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings
    mock_llm_load_config.return_value = mock_settings

    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm

    workspace = Path(mock_settings.active_workspace_path)
    raw_file = workspace / "1_ingest_data" / "filing.htm"
    raw_file.write_text(
        "<h1>Annual Report</h1><p>Financial details...</p>", encoding="utf-8"
    )

    ingester = Ingester()
    ingester.run_ingestion()

    # Verify document is parsed, named after stem, and archived
    parsed_file = workspace / "2_parsed_data" / "filing.md"
    assert parsed_file.exists()

    archived_file = workspace / "3_archived_data" / "filing.htm"
    assert archived_file.exists()
    assert not raw_file.exists()

    # Verify parsed_data.csv is updated with default N/A metadata
    registry_path = workspace / "2_parsed_data" / "parsed_data.csv"
    assert registry_path.exists()
    with open(registry_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["new_filename"] == "filing.md"
        assert rows[0]["document_type"] == "N/A"
        assert rows[0]["fiscal_quarter"] == "N/A"
        assert rows[0]["fiscal_year"] == "N/A"


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
@patch("src.agents.orchestrator_pipelines.ingest.load_config")
@patch("src.agents.orchestrator_pipelines.ingest.get_llm_client")
def test_ingestion_limit(
    mock_get_llm, mock_load_config, mock_llm_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings
    mock_llm_load_config.return_value = mock_settings

    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm

    workspace = Path(mock_settings.active_workspace_path)
    for i in range(3):
        raw_file = workspace / "1_ingest_data" / f"filing_{i}.htm"
        raw_file.write_text(f"<h1>Report {i}</h1>", encoding="utf-8")

    ingester = Ingester()
    ingester.run_ingestion(limit=2)

    # Verify that exactly 2 parsed files were created
    parsed_files = list((workspace / "2_parsed_data").glob("*.md"))
    assert len(parsed_files) == 2


@patch("src.services.llm_client.load_config")
@patch("src.agents.orchestrator_pipelines.ingest.load_config")
@patch("src.agents.orchestrator_pipelines.ingest.get_llm_client")
def test_ingestion_ignores_readme_and_hidden(
    mock_get_llm, mock_load_config, mock_llm_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings
    mock_llm_load_config.return_value = mock_settings

    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm

    workspace = Path(mock_settings.active_workspace_path)
    (workspace / "1_ingest_data" / "README.md").write_text(
        "# Readme content", encoding="utf-8"
    )
    (workspace / "1_ingest_data" / ".hidden_file").write_text(
        "hidden", encoding="utf-8"
    )
    (workspace / "1_ingest_data" / "filing.htm").write_text(
        "<h1>Report</h1>", encoding="utf-8"
    )

    ingester = Ingester()
    ingester.run_ingestion()

    parsed_files = list((workspace / "2_parsed_data").glob("*.md"))
    assert len(parsed_files) == 1
    assert parsed_files[0].name == "filing.md"


@patch("src.services.llm_client.load_config")
@patch("src.agents.orchestrator_pipelines.ingest.load_config")
@patch("src.agents.orchestrator_pipelines.ingest.get_llm_client")
@patch("fitz.open")
def test_ingestion_pdf(
    mock_fitz_open, mock_get_llm, mock_load_config, mock_llm_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings
    mock_llm_load_config.return_value = mock_settings

    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm

    mock_page = MagicMock()
    mock_page.get_text.return_value = (
        "Row 1 Col 1    Row 1 Col 2\nRow 2 Col 1    Row 2 Col 2"
    )
    mock_doc = MagicMock()
    mock_doc.__iter__.return_value = [mock_page]
    mock_fitz_open.return_value = mock_doc

    workspace = Path(mock_settings.active_workspace_path)
    raw_file = workspace / "1_ingest_data" / "filing.pdf"
    raw_file.write_bytes(b"dummy pdf bytes")

    ingester = Ingester()
    ingester.run_ingestion()

    parsed_file = workspace / "2_parsed_data" / "filing.md"
    assert parsed_file.exists()
    content = parsed_file.read_text(encoding="utf-8")
    assert "Row 1 Col 1    Row 1 Col 2" in content

    archived_file = workspace / "3_archived_data" / "filing.pdf"
    assert archived_file.exists()
    assert not raw_file.exists()


@patch("src.services.llm_client.load_config")
@patch("src.agents.orchestrator_pipelines.ingest.load_config")
@patch("src.agents.orchestrator_pipelines.ingest.get_llm_client")
def test_ingester_offsets(
    mock_get_llm, mock_load_config, mock_llm_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings
    mock_llm_load_config.return_value = mock_settings

    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm

    workspace = Path(mock_settings.active_workspace_path)
    raw_file = workspace / "1_ingest_data" / "filing.htm"
    raw_file.write_text(
        "<h1>Annual Report</h1><p>Financial details part 1...</p><p>Financial details part 2...</p>",
        encoding="utf-8",
    )

    with patch("src.agents.orchestrator_pipelines.ingest.chunk_text") as mock_chunk:
        mock_chunk.return_value = [
            "Financial details part 1...",
            "Financial details part 2...",
        ]
        ingester = Ingester()
        ingester.run_ingestion()

    parsed_file = workspace / "2_parsed_data" / "filing.md"
    assert parsed_file.exists()
    content = parsed_file.read_text(encoding="utf-8")

    import re

    matches = re.findall(r"\|\s*(\d+)\s*\|\s*char\s*(\d+)\s*to\s*(\d+)\s*\|", content)
    assert len(matches) == 2

    idx1, start1, end1 = matches[0]
    start1, end1 = int(start1), int(end1)
    assert content[start1:end1] == "Financial details part 1..."

    idx2, start2, end2 = matches[1]
    start2, end2 = int(start2), int(end2)
    assert content[start2:end2] == "Financial details part 2..."


@patch("src.agents.orchestrator_pipelines.ingest.load_config")
@patch("src.agents.orchestrator_pipelines.ingest.get_llm_client")
def test_self_healing_logic(mock_get_llm, mock_load_config, mock_settings):
    mock_load_config.return_value = mock_settings
    workspace = Path(mock_settings.active_workspace_path)

    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm

    parsed_dir = workspace / "2_parsed_data"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    csv_path = parsed_dir / "parsed_data.csv"

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
        writer.writerow(
            {
                "file_hash": "hash123",
                "original_filename": "report.pdf",
                "new_filename": "filing.md",
                "document_type": "annual_filing",
                "document_date": "2023-09-30",
                "fiscal_quarter": "Q1",
                "fiscal_year": "2023",
                "period_end_date": "2023-09-30",
            }
        )

    ingester = Ingester()

    reg = ingester.load_parsed_registry()
    assert "hash123" in reg
    assert reg["hash123"]["fiscal_year"] == "2023"

    # Test overwrite CSV rows
    ingester.overwrite_csv_rows(
        [{"file_hash": "hash123", "fiscal_quarter": "FY", "fiscal_year": "2024"}]
    )

    reg2 = ingester.load_parsed_registry()
    assert reg2["hash123"]["fiscal_quarter"] == "FY"
    assert reg2["hash123"]["fiscal_year"] == "2024"
