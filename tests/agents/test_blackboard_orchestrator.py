import pytest
from unittest.mock import patch

from src.core.config import Settings, save_config
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    CompanyMetadata,
)
from src.core.exceptions import WorkspaceError
from src.agents.blackboard_orchestrator import BlackboardOrchestrator


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
    return settings


def test_recover_dangling_states(temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)

    # Simulate a dangling metadata_status and a dangling balance_sheet_status
    state.metadata_status = "running"

    from src.core.blackboard import TemporalBlackboard

    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
        balance_sheet_status="running",
    )
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()
    orchestrator.recover_dangling_states(ticker)

    updated_state = load_workspace_state(ticker)
    assert updated_state.metadata_status == "failed"
    assert updated_state.reports["2024_Q3"].balance_sheet_status == "failed"


def test_checkout_and_checkin_status(temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()

    # 1. Test metadata check-out / check-in
    orchestrator.checkout_status(ticker, "metadata")
    state = load_workspace_state(ticker)
    assert state.metadata_status == "running"

    from src.core.blackboard import CompanyMetadata

    dummy_metadata = CompanyMetadata(
        ticker=ticker,
        company_name="Apple Inc.",
        description="Consumer electronics",
    )
    orchestrator.checkin_status(ticker, "metadata", "completed", payload=dummy_metadata)
    state = load_workspace_state(ticker)
    assert state.metadata_status == "completed"
    assert state.metadata.company_name == "Apple Inc."

    # 2. Test period-specific check-out / check-in
    from src.core.blackboard import TemporalBlackboard

    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
    )
    save_workspace_state(ticker, state)

    orchestrator.checkout_status(ticker, "balance_sheet", period="2024_Q3")
    state = load_workspace_state(ticker)
    assert state.reports["2024_Q3"].balance_sheet_status == "running"

    from src.agents.extractor_agents.extractor_financials_agents.balance_sheet_agent import (
        BalanceSheetExtraction,
    )

    dummy_bs = BalanceSheetExtraction(
        raw_balance_sheet_markdown="| Cash | 100 |\n",
        currency="USD",
        unit="Millions",
    )
    orchestrator.checkin_status(
        ticker, "balance_sheet", "completed", period="2024_Q3", payload=dummy_bs
    )
    state = load_workspace_state(ticker)
    assert state.reports["2024_Q3"].balance_sheet_status == "completed"
    assert (
        state.reports["2024_Q3"].financial_data.raw_balance_sheet_markdown
        == "| Cash | 100 |\n"
    )


@patch("src.agents.blackboard_orchestrator.run_metadata_agent")
def test_single_agent_extract_metadata(mock_run_metadata, temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()

    mock_run_metadata.return_value = CompanyMetadata(
        ticker=ticker, company_name="Mock Apple Inc."
    )

    import asyncio

    asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="metadata"))

    mock_run_metadata.assert_called_once()
    state = load_workspace_state(ticker)
    assert state.metadata_status == "completed"
    assert state.metadata.company_name == "Mock Apple Inc."


def test_single_agent_extract_missing_metadata(temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()

    import pytest

    with pytest.raises(WorkspaceError) as exc_info:
        import asyncio

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

    import pytest

    with pytest.raises(WorkspaceError) as exc_info:
        import asyncio

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

    from src.core.blackboard import TemporalBlackboard

    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
        income_statement_status="completed",
    )
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()
    mock_run_shares.return_value = (1000.0, 1020.0)

    with patch("src.agents.ingester.Ingester.load_parsed_registry") as mock_registry:
        mock_registry.return_value = {
            "h1": {
                "new_filename": "20240801_10-Q.md",
                "fiscal_year": 2024,
                "fiscal_quarter": "Q3",
                "document_type": "quarterly_filing",
            }
        }

        import asyncio

        asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="shares"))

    mock_run_shares.assert_called_once()
    updated_state = load_workspace_state(ticker)
    assert updated_state.reports["2024_Q3"].shares_status == "completed"
    assert updated_state.reports["2024_Q3"].financial_data.basic_shares == 1000.0
    assert updated_state.reports["2024_Q3"].financial_data.diluted_shares == 1020.0


def test_single_agent_model_missing_metadata(temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()

    import pytest

    with pytest.raises(WorkspaceError) as exc_info:
        import asyncio

        asyncio.run(orchestrator.run_pipeline(ticker, stage="model", agent="wacc"))

    assert "Company metadata extraction must be completed first" in str(exc_info.value)


@patch("src.agents.blackboard_orchestrator.run_wacc_agent")
def test_single_agent_model_wacc_success(mock_run_wacc, temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker=ticker, company_name="Mock Apple Inc.")

    from src.core.blackboard import TemporalBlackboard

    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
        balance_sheet_status="completed",
        income_statement_status="completed",
    )
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()
    mock_run_wacc.return_value = {
        "wacc": 0.085,
        "cost_equity": 0.095,
        "cost_debt_pretax": 0.065,
        "weight_equity": 0.8,
        "weight_debt": 0.2,
        "explanation": "Calculated mock WACC",
    }

    import asyncio

    asyncio.run(orchestrator.run_pipeline(ticker, stage="model", agent="wacc"))

    mock_run_wacc.assert_called_once()
    updated_state = load_workspace_state(ticker)
    assert updated_state.reports["2024_Q3"].wacc_agent_status == "completed"
    assert updated_state.reports["2024_Q3"].base_model.assumptions.wacc == 0.085


def test_concurrency_settings_and_semaphores(temp_workspace_env):
    # Verify settings defaults
    assert temp_workspace_env.concurrency_limit_company == 1
    assert temp_workspace_env.concurrency_limit_document == 3
    assert temp_workspace_env.concurrency_limit_phase == 3

    # Verify orchestrator picks them up and initializes semaphores
    orchestrator = BlackboardOrchestrator()
    assert orchestrator.company_sem._value == 1
    assert orchestrator.doc_sem._value == 3
    assert orchestrator.phase_sem._value == 3


@patch("src.agents.blackboard_orchestrator.run_balance_sheet_agent")
def test_pipeline_metadata_gating(mock_run_bs, temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)
    # Set metadata_status to failed, which should gate/block extraction stage execution
    state.metadata_status = "failed"
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()

    import asyncio

    asyncio.run(orchestrator.run_pipeline(ticker, stage="extract"))

    # Balance sheet agent must not be run since metadata was not completed
    mock_run_bs.assert_not_called()
