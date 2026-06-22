import pytest
import asyncio
import json
from unittest.mock import patch
from pathlib import Path

from src.core.config import Settings, save_config
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    CompanyMetadata,
    TemporalBlackboard,
)
from src.core.exceptions import LLMError
from src.agents.blackboard_orchestrator import BlackboardOrchestrator
from src.agents.extractor_agents.extractor_financials_agents.balance_sheet_agent import (
    BalanceSheetExtraction,
)


@pytest.fixture
def temp_workspace_env(tmp_path, monkeypatch):
    fake_config_path = tmp_path / ".env"
    monkeypatch.setattr("src.core.config.CONFIG_FILE_PATH", fake_config_path)

    settings = Settings(
        full_name="Test Developer",
        email="developer@example.com",
        project_name="TestProject",
        base_workspace_dir=str(tmp_path / "workspace"),
        active_workspace_path=str(tmp_path / "workspace" / "AAPL"),
        active_ticker="AAPL",
    )
    save_config(settings)
    (tmp_path / "workspace" / "AAPL").mkdir(parents=True, exist_ok=True)

    # Create subdirs required by use command / workspace initialization
    (tmp_path / "workspace" / "AAPL" / "1_ingest_data").mkdir(
        parents=True, exist_ok=True
    )
    (tmp_path / "workspace" / "AAPL" / "2_parsed_data").mkdir(
        parents=True, exist_ok=True
    )
    (tmp_path / "workspace" / "AAPL" / "3_archived_data").mkdir(
        parents=True, exist_ok=True
    )
    (tmp_path / "workspace" / "AAPL" / "9_scenario_model_json").mkdir(
        parents=True, exist_ok=True
    )

    return settings


@patch("src.agents.blackboard_orchestrator.run_balance_sheet_agent")
def test_gaap_override_policy(mock_run_bs, temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()
    workspace = Path(temp_workspace_env.active_workspace_path)

    # 1. Initialize metadata
    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker=ticker, company_name="Mock Apple Inc.")

    # Initialize report for 2024_Q3
    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
    )
    save_workspace_state(ticker, state)

    # Mock the parser registry returning two files for 2024_Q3:
    # An earnings announcement (EA) and a quarterly filing (10-Q)
    mock_registry = {
        "h1": {
            "new_filename": "20240725_EA.md",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q3",
            "document_type": "earnings_announcement",
        },
        "h2": {
            "new_filename": "20240801_10-Q.md",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q3",
            "document_type": "quarterly_filing",
        },
    }

    # Write dummy files to workspace 2_parsed_data
    (workspace / "2_parsed_data" / "20240725_EA.md").write_text(
        "Dummy EA Content", encoding="utf-8"
    )
    (workspace / "2_parsed_data" / "20240801_10-Q.md").write_text(
        "Dummy 10-Q Content", encoding="utf-8"
    )

    # When EA is run, it returns mock Balance Sheet extractions
    ea_bs = BalanceSheetExtraction(
        raw_balance_sheet_markdown="| EA Item | 100 |\n",
        currency="USD",
        unit="Millions",
    )

    # When 10-Q is run, it returns formal Balance Sheet extractions
    formal_bs = BalanceSheetExtraction(
        raw_balance_sheet_markdown="| Formal 10-Q Item | 200 |\n",
        currency="USD",
        unit="Millions",
    )

    mock_run_bs.side_effect = [ea_bs, formal_bs]

    with (
        patch(
            "src.agents.orchestrator_pipelines.ingest.Ingester.load_parsed_registry",
            return_value=mock_registry,
        ),
        patch(
            "src.agents.orchestrator_pipelines.extract.parse_markdown_to_line_items"
        ) as mock_parse_items,
    ):
        # We need mock_parse_items to return corresponding LineItem mock objects
        from src.core.blackboard import LineItem

        ea_item = LineItem(
            line_name="EA Item",
            value=100.0,
            operating=True,
            calculated=False,
            category="current_assets",
        )
        formal_item = LineItem(
            line_name="Formal 10-Q Item",
            value=200.0,
            operating=True,
            calculated=False,
            category="current_assets",
        )

        mock_parse_items.side_effect = [[ea_item], [formal_item]]

        # Run extraction stage
        asyncio.run(
            orchestrator.run_pipeline(ticker, stage="extract", agent="balance_sheet")
        )

    # Assert formal filing overwrote EA extractions
    updated_state = load_workspace_state(ticker)
    report = updated_state.reports["2024_Q3"]
    assert (
        report.financial_data.raw_balance_sheet_markdown
        == "| Formal 10-Q Item | 200 |\n"
    )
    assert len(report.financial_data.line_items) == 1
    assert report.financial_data.line_items[0].line_name == "Formal 10-Q Item"
    assert report.financial_data.line_items[0].value == 200.0

    # Verify source files accumulated both filenames
    assert "20240725_EA.md" in report.source_files
    assert "20240801_10-Q.md" in report.source_files


@patch("src.agents.blackboard_orchestrator.run_organic_growth_agent")
@patch("src.agents.blackboard_orchestrator.run_ebita_agent")
@patch("src.agents.blackboard_orchestrator.run_tax_agent")
def test_nongaap_preservation_policy(
    mock_run_tax, mock_run_ebita, mock_run_growth, temp_workspace_env
):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()

    # 1. Setup metadata and report state with pre-existing EA non-GAAP metrics
    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker=ticker, company_name="Mock Apple Inc.")

    # Initialize report for 2024_Q3 with existing non-GAAP metrics
    report = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
        income_statement_status="completed",
    )
    report.financial_data.organic_growth = 0.085
    report.financial_data.simple_growth = 0.090
    report.financial_data.ebita = 1200.0
    report.financial_data.operating_income = (
        1000.0  # adjustments exist because ebita != operating_income
    )
    report.financial_data.raw_notes_markdown = json.dumps(
        [{"name": "Restructuring", "value": 200.0}]
    )
    report.financial_data.adjusted_taxes = 250.0
    report.financial_data.reported_tax_provision = 200.0  # adjustments exist

    state.reports["2024_Q3"] = report
    save_workspace_state(ticker, state)

    # Mock registry returns only a 10-Q filing (representing the 10-Q run after EA)
    mock_registry = {
        "h2": {
            "new_filename": "20240801_10-Q.md",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q3",
            "document_type": "quarterly_filing",
        }
    }
    workspace = Path(temp_workspace_env.active_workspace_path)
    (workspace / "2_parsed_data" / "20240801_10-Q.md").write_text(
        "Dummy 10-Q Content", encoding="utf-8"
    )

    # Mock agents returning zero/default/unadjusted values on the 10-Q
    mock_run_growth.return_value = (
        0.090,
        0.090,
        10000.0,
    )  # organic growth is simple growth (no adjustments found)
    mock_run_ebita.return_value = (
        1000.0,
        1000.0,
        [],
    )  # ebita is same as op_inc (no adjustments found)
    mock_run_tax.return_value = (
        1200.0,
        200.0,
        200.0,
        [],
    )  # adjusted taxes equals reported tax provision (no adjustments found)

    with (
        patch(
            "src.agents.orchestrator_pipelines.ingest.Ingester.load_parsed_registry",
            return_value=mock_registry,
        ),
        patch(
            "src.agents.orchestrator_pipelines.extract.parse_markdown_to_line_items",
            return_value=[],
        ),
    ):
        # Run stage-extract for metric agents
        asyncio.run(
            orchestrator.run_pipeline(ticker, stage="extract", agent="organic_growth")
        )
        asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="ebita"))
        asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="tax"))

    # Assert that non-GAAP metrics (organic growth, EBITA adjustments, adjusted taxes) were preserved!
    updated_state = load_workspace_state(ticker)
    rep = updated_state.reports["2024_Q3"]

    assert rep.financial_data.organic_growth == 0.085  # Preserved
    assert rep.financial_data.simple_growth == 0.090  # GAAP, updated
    assert (
        rep.financial_data.ebita == 1200.0
    )  # Preserved because new ebita has no adjustments but old had
    assert json.loads(rep.financial_data.raw_notes_markdown) == [
        {"name": "Restructuring", "value": 200.0}
    ]  # Preserved
    assert (
        rep.financial_data.adjusted_taxes == 250.0
    )  # Preserved because new tax has no adjustments but old had


@patch("src.agents.blackboard_orchestrator.run_balance_sheet_agent")
def test_quality_audit_failures_written_to_blackboard(mock_run_bs, temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()
    workspace = Path(temp_workspace_env.active_workspace_path)

    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker=ticker, company_name="Mock Apple Inc.")
    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
    )
    save_workspace_state(ticker, state)

    mock_registry = {
        "h1": {
            "new_filename": "20240801_10-Q.md",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q3",
            "document_type": "quarterly_filing",
        }
    }
    (workspace / "2_parsed_data" / "20240801_10-Q.md").write_text(
        "Dummy 10-Q Content", encoding="utf-8"
    )

    # Simulate sub-agent quality checks failing and running out of execution turns
    mock_run_bs.side_effect = LLMError(
        "Agent failed to finalize execution. Quality audit failures: ['Assets = 100, Liabilities + Equity = 120']"
    )

    with patch(
        "src.agents.orchestrator_pipelines.ingest.Ingester.load_parsed_registry",
        return_value=mock_registry,
    ):
        with pytest.raises(SystemExit):
            asyncio.run(
                orchestrator.run_pipeline(
                    ticker, stage="extract", agent="balance_sheet", non_interactive=True
                )
            )

    # Assert that task status is failed, and error details were written to arithmetic_errors
    updated_state = load_workspace_state(ticker)
    report = updated_state.reports["2024_Q3"]
    assert report.balance_sheet_status == "failed"
    assert len(report.arithmetic_errors) == 1
    assert (
        "Quality audit failures: ['Assets = 100, Liabilities + Equity = 120']"
        in report.arithmetic_errors[0]
    )
