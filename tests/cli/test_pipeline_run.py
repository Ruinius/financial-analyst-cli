from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from typer.testing import CliRunner
from src.cli.main import app
from src.core.config import Settings

runner = CliRunner()


@pytest.fixture
def mock_settings(tmp_path):
    # Setup temporary directories representing the workspace folders
    workspace_path = tmp_path / "CRM"
    (workspace_path / "1_ingest_data").mkdir(parents=True, exist_ok=True)
    return Settings(
        full_name="Tiger Huang",
        email="tiger@example.com",
        project_name="Value_Investing",
        primary_llm_api_key="test-key",
        base_workspace_dir=str(tmp_path),
        active_workspace_path=str(workspace_path),
        active_ticker="CRM",
    )


@patch("src.cli.main.load_config")
@patch("src.agents.blackboard_orchestrator.BlackboardOrchestrator.run_pipeline")
def test_run_full_pipeline_no_subcommand_non_interactive(
    mock_run_pipeline, mock_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings

    # Invoke 'fa run' in non-interactive mode.
    # Since there are no files in 1_ingest_data/, it shouldn't prompt anyway.
    result = runner.invoke(app, ["run", "--non-interactive"])

    assert result.exit_code == 0
    assert "Starting full data pipeline for CRM..." in result.stdout
    assert "Successfully executed full data pipeline" in result.stdout

    # Verify that run_pipeline was called with stage=None
    mock_run_pipeline.assert_called_once_with(
        "CRM",
        stage=None,
        non_interactive=True,
        limit=None,
    )


@patch("src.cli.main.load_config")
@patch("src.agents.blackboard_orchestrator.BlackboardOrchestrator.run_pipeline")
def test_run_full_pipeline_with_files_prompts_limit(
    mock_run_pipeline, mock_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings

    # Create dummy raw files in 1_ingest_data/
    ingest_dir = Path(mock_settings.active_workspace_path) / "1_ingest_data"
    (ingest_dir / "file1.pdf").write_text("content1")
    (ingest_dir / "file2.html").write_text("content2")

    # Run in interactive mode, providing '2' as the number of files to process
    result = runner.invoke(app, ["run"], input="2\n")

    assert result.exit_code == 0
    assert "found 2 raw file(s) ready for ingestion" in result.stdout.lower()
    assert "How many files would you like to process?" in result.stdout
    assert "Starting full data pipeline for CRM..." in result.stdout

    # Verify that run_pipeline was called with limit=2
    mock_run_pipeline.assert_called_once_with(
        "CRM",
        stage=None,
        non_interactive=False,
        limit=2,
    )


@patch("src.cli.main.load_config")
@patch("src.agents.blackboard_orchestrator.BlackboardOrchestrator.run_pipeline")
def test_run_full_pipeline_non_interactive_skips_prompt(
    mock_run_pipeline, mock_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings

    # Create dummy raw files in 1_ingest_data/
    ingest_dir = Path(mock_settings.active_workspace_path) / "1_ingest_data"
    (ingest_dir / "file1.pdf").write_text("content1")

    # Run in non-interactive mode. It should skip prompting and process "all"
    result = runner.invoke(app, ["run", "--non-interactive"])

    assert result.exit_code == 0
    assert "found 1 raw file(s) ready for ingestion" in result.stdout.lower()
    assert "How many files would you like to process?" not in result.stdout
    assert "Starting full data pipeline for CRM..." in result.stdout

    # Verify that run_pipeline was called with limit=None
    mock_run_pipeline.assert_called_once_with(
        "CRM",
        stage=None,
        non_interactive=True,
        limit=None,
    )


@patch("src.cli.main.load_config")
@patch("src.cli.main.EdgarClient")
@patch("src.agents.blackboard_orchestrator.BlackboardOrchestrator.run_pipeline")
def test_run_subcommand_bypasses_full_pipeline(
    mock_run_pipeline, mock_edgar_client_class, mock_load_config, mock_settings
):
    mock_load_config.return_value = mock_settings

    mock_client = MagicMock()
    mock_client.download_filings.return_value = ["/dummy/path"]
    mock_edgar_client_class.return_value = mock_client

    # Invoke a subcommand, like 'fa run edgar'
    result = runner.invoke(app, ["run", "edgar", "AAPL"])
    assert result.exit_code == 0

    # Verify that run_pipeline (the full pipeline) was NOT called
    mock_run_pipeline.assert_not_called()
