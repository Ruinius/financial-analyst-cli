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


@patch("src.cli.main.load_config")
@patch("src.agents.blackboard_orchestrator.BlackboardOrchestrator.run_pipeline")
def test_run_extract_menu_choices(mock_run_pipeline, mock_load_config, mock_settings):
    mock_load_config.return_value = mock_settings

    # Create dummy parsed files in 2_parsed_data/
    parsed_dir = Path(mock_settings.active_workspace_path) / "2_parsed_data"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    # create files in reverse-chronological order (descending by filename)
    (parsed_dir / "2026_q2_crm.md").write_text("q2 crm content")
    (parsed_dir / "2026_q1_crm.md").write_text("q1 crm content")

    from src.core.blackboard import load_workspace_state, save_workspace_state

    def mock_run_side_effect(*args, **kwargs):
        st = load_workspace_state("CRM")
        for rep in st.reports.values():
            rep.balance_sheet_status = "completed"
            rep.income_statement_status = "completed"
            rep.shares_status = "completed"
            rep.organic_growth_status = "completed"
            rep.ebita_status = "completed"
            rep.tax_status = "completed"
        save_workspace_state("CRM", st)

    mock_run_pipeline.side_effect = mock_run_side_effect

    # 1. Hitting Enter / default
    result = runner.invoke(app, ["run", "extract"], input="\n")
    assert result.exit_code == 0
    assert "I found 2 total file(s) in our workspace directory" in result.stdout
    # Check that letters [a] and [b] are printed (2026_q2_crm.md is first, so 'a', 2026_q1_crm.md is 'b')
    assert "[a]" in result.stdout
    assert "[b]" in result.stdout
    assert "2026_q2_crm.md" in result.stdout
    assert "2026_q1_crm.md" in result.stdout

    mock_run_pipeline.assert_called_with(
        "CRM",
        stage="extract",
        agent=None,
        non_interactive=False,
        limit=None,
        force=False,
        target_files=None,
    )

    # 2. Entering a letter label "a" to target first file
    result = runner.invoke(app, ["run", "extract"], input="a\n")
    assert result.exit_code == 0
    mock_run_pipeline.assert_called_with(
        "CRM",
        stage="extract",
        agent=None,
        non_interactive=False,
        limit=None,
        force=True,
        target_files=["2026_q2_crm.md"],
    )

    # 3. Entering a number limit "1"
    result = runner.invoke(app, ["run", "extract"], input="1\n")
    assert result.exit_code == 0
    mock_run_pipeline.assert_called_with(
        "CRM",
        stage="extract",
        agent=None,
        non_interactive=False,
        limit=1,
        force=False,
        target_files=None,
    )


@patch("src.cli.main.load_config")
@patch("src.agents.blackboard_orchestrator.BlackboardOrchestrator.run_pipeline")
@patch("src.core.blackboard.load_workspace_state")
@patch("src.cli.main.Ingester.load_parsed_registry")
def test_run_extract_menu_pending_status(
    mock_load_registry,
    mock_load_state,
    mock_run_pipeline,
    mock_load_config,
    mock_settings,
):
    mock_settings.active_ticker = "CRM"
    mock_load_config.return_value = mock_settings
    mock_run_pipeline.return_value = True

    parsed_dir = Path(mock_settings.active_workspace_path) / "2_parsed_data"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    (parsed_dir / "20250822_10K_parsed.md").write_text("10k content")

    from src.core.blackboard import (
        CompanyMetadata,
        TemporalBlackboard,
        WorkspaceContext,
    )

    st = WorkspaceContext(metadata=CompanyMetadata(ticker="CRM"))
    rep = TemporalBlackboard(
        fiscal_year=2025,
        fiscal_period="FY",
        is_quarterly=False,
        source_files=["20250822_10K_parsed.md"],
    )
    rep.balance_sheet_status = "completed"
    rep.income_statement_status = "completed"
    rep.shares_status = "completed"
    rep.organic_growth_status = "completed"
    rep.ebita_status = "completed"
    rep.tax_status = "completed"
    st.reports["2025_FY"] = rep
    mock_load_state.return_value = st
    mock_load_registry.return_value = {
        "hash1": {
            "new_filename": "20250822_10K_parsed.md",
            "fiscal_year": "2025",
            "fiscal_quarter": "FY",
            "document_type": "annual_filing",
        }
    }

    result = runner.invoke(app, ["run", "extract"], input="\n")
    assert result.exit_code == 0, result.output
    assert "[Pending]" in result.stdout
    assert "1 pending" in result.stdout
