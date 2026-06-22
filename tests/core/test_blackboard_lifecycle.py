from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    CompanyMetadata,
    TemporalBlackboard,
)
from src.agents.blackboard_orchestrator import BlackboardOrchestrator
from src.agents.extractor_agents.extractor_financials_agents.balance_sheet_agent import (
    BalanceSheetExtraction,
)


def test_recover_dangling_states(temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)

    # Simulate a dangling metadata_status and a dangling balance_sheet_status
    state.metadata_status = "running"

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
    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
    )
    save_workspace_state(ticker, state)

    orchestrator.checkout_status(ticker, "balance_sheet", period="2024_Q3")
    state = load_workspace_state(ticker)
    assert state.reports["2024_Q3"].balance_sheet_status == "running"

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
