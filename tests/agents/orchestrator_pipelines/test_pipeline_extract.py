import pytest
import asyncio
from unittest.mock import patch

from src.agents.blackboard_orchestrator import BlackboardOrchestrator
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    CompanyMetadata,
    TemporalBlackboard,
)
from src.core.exceptions import WorkspaceError


@patch("src.agents.blackboard_orchestrator.run_metadata_agent")
def test_single_agent_extract_metadata(mock_run_metadata, temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()

    mock_run_metadata.return_value = CompanyMetadata(
        ticker=ticker, company_name="Mock Apple Inc."
    )

    asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="metadata"))

    mock_run_metadata.assert_called_once()
    state = load_workspace_state(ticker)
    assert state.metadata_status == "completed"
    assert state.metadata.company_name == "Mock Apple Inc."


def test_single_agent_extract_missing_metadata(temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()

    with pytest.raises(WorkspaceError) as exc_info:
        asyncio.run(
            orchestrator.run_pipeline(ticker, stage="extract", agent="balance_sheet")
        )

    assert "Company metadata extraction must be completed first" in str(exc_info.value)


def test_single_agent_extract_shares_missing_prereq(temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker=ticker, company_name="Mock Apple Inc.")
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()

    with pytest.raises(WorkspaceError) as exc_info:
        asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="shares"))

    assert (
        "Income statement must be completed for at least one period before running shares agent"
        in str(exc_info.value)
    )


@patch("src.agents.blackboard_orchestrator.run_diluted_shares_agent")
def test_single_agent_extract_shares_success(mock_run_shares, temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker=ticker, company_name="Mock Apple Inc.")

    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
        income_statement_status="completed",
    )
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()
    mock_run_shares.return_value = (1000.0, 1020.0)

    with patch(
        "src.agents.orchestrator_pipelines.ingest.Ingester.load_parsed_registry"
    ) as mock_registry:
        mock_registry.return_value = {
            "h1": {
                "new_filename": "20240801_10-Q.md",
                "fiscal_year": 2024,
                "fiscal_quarter": "Q3",
                "document_type": "quarterly_filing",
            }
        }

        asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="shares"))

    mock_run_shares.assert_called_once()
    updated_state = load_workspace_state(ticker)
    assert updated_state.reports["2024_Q3"].shares_status == "completed"
    assert updated_state.reports["2024_Q3"].financial_data.basic_shares == 1000.0
    assert updated_state.reports["2024_Q3"].financial_data.diluted_shares == 1020.0


@patch("src.agents.blackboard_orchestrator.run_balance_sheet_agent")
def test_pipeline_metadata_gating(mock_run_bs, temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)
    state.metadata_status = "failed"
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()

    asyncio.run(orchestrator.run_pipeline(ticker, stage="extract"))

    mock_run_bs.assert_not_called()
