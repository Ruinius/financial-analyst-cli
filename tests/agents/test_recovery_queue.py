import pytest
import asyncio
from unittest.mock import patch, AsyncMock

from src.core.config import Settings, save_config
from src.core.exceptions import LLMError, WorkspaceError
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    CompanyMetadata,
    TemporalBlackboard,
)
from src.agents.blackboard_orchestrator import BlackboardOrchestrator, FailedTask


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

    # Initialize workspace state
    state = load_workspace_state("AAPL")
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker="AAPL", company_name="Apple Inc.")
    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
    )
    save_workspace_state("AAPL", state)

    return settings


def test_is_network_failure():
    orchestrator = BlackboardOrchestrator()

    # Test validation error
    val_err = ValueError("validation failed for field x")
    assert not orchestrator._is_network_failure(val_err)

    # Test quality check failure
    qual_err = LLMError("quality audit failed: assets != liabilities")
    assert not orchestrator._is_network_failure(qual_err)

    # Test network failure
    net_err = LLMError("timeout connecting to API rate limit exceeded")
    assert orchestrator._is_network_failure(net_err)

    # Test generic LLMError
    generic_llm_err = LLMError("generic error")
    assert orchestrator._is_network_failure(generic_llm_err)


@pytest.mark.anyio
async def test_non_interactive_network_retry(temp_workspace_env):
    orchestrator = BlackboardOrchestrator()
    ticker = "AAPL"

    # We will simulate a network failure task that fails twice and succeeds on the third try
    attempt = 0

    async def mock_coro():
        nonlocal attempt
        attempt += 1
        if attempt < 3:
            raise LLMError("Network timeout connecting to provider")
        return "success"

    failed_task = FailedTask(
        task_type="balance_sheet",
        coro_factory=mock_coro,
        period="2024_Q3",
        file_name="20240801_10-Q.md",
        exception=LLMError("Network timeout connecting to provider"),
    )
    orchestrator._failure_queue.append(failed_task)

    await orchestrator._process_failure_queue(ticker, non_interactive=True)

    assert attempt == 3
    assert len(orchestrator._failure_queue) == 0


@pytest.mark.anyio
async def test_non_interactive_validation_halt(temp_workspace_env):
    orchestrator = BlackboardOrchestrator()
    ticker = "AAPL"

    async def mock_coro():
        pass

    failed_task = FailedTask(
        task_type="balance_sheet",
        coro_factory=mock_coro,
        period="2024_Q3",
        file_name="20240801_10-Q.md",
        exception=LLMError("Quality check failure on balance sheet"),
    )
    orchestrator._failure_queue.append(failed_task)

    # Non-interactive mode should call sys.exit(1) on validation error
    with pytest.raises(SystemExit) as excinfo:
        await orchestrator._process_failure_queue(ticker, non_interactive=True)

    assert excinfo.value.code == 1

    # Check that it updated the status to failed in the blackboard
    state = load_workspace_state(ticker)
    assert state.reports["2024_Q3"].balance_sheet_status == "failed"


@pytest.mark.anyio
@patch("typer.prompt")
async def test_interactive_retry_success(mock_prompt, temp_workspace_env):
    # Simulate user choosing "retry"
    mock_prompt.return_value = "retry"

    orchestrator = BlackboardOrchestrator()
    ticker = "AAPL"

    attempt = 0

    async def mock_coro():
        nonlocal attempt
        attempt += 1
        return "success"

    failed_task = FailedTask(
        task_type="balance_sheet",
        coro_factory=mock_coro,
        period="2024_Q3",
        file_name="20240801_10-Q.md",
        exception=LLMError("quality audit failed"),
    )
    orchestrator._failure_queue.append(failed_task)

    await orchestrator._process_failure_queue(ticker, non_interactive=False)

    assert attempt == 1
    assert len(orchestrator._failure_queue) == 0
    mock_prompt.assert_called_once()


@pytest.mark.anyio
@patch("typer.prompt")
async def test_interactive_dont_retry(mock_prompt, temp_workspace_env):
    # Simulate user choosing "dont-retry" (or skip)
    mock_prompt.return_value = "dont-retry"

    orchestrator = BlackboardOrchestrator()
    ticker = "AAPL"

    async def mock_coro():
        pass

    failed_task = FailedTask(
        task_type="balance_sheet",
        coro_factory=mock_coro,
        period="2024_Q3",
        file_name="20240801_10-Q.md",
        exception=LLMError("quality audit failed"),
    )
    orchestrator._failure_queue.append(failed_task)

    await orchestrator._process_failure_queue(ticker, non_interactive=False)

    # Task should be skipped and status marked as failed
    state = load_workspace_state(ticker)
    assert state.reports["2024_Q3"].balance_sheet_status == "failed"
    assert len(orchestrator._failure_queue) == 0


@pytest.mark.anyio
@patch("typer.prompt")
async def test_interactive_stop_all(mock_prompt, temp_workspace_env):
    # Simulate user choosing "stop-all"
    mock_prompt.return_value = "stop-all"

    orchestrator = BlackboardOrchestrator()
    ticker = "AAPL"

    # Create real asyncio Future objects to cancel
    loop = asyncio.get_running_loop()
    mock_task1 = loop.create_future()
    mock_task2 = loop.create_future()
    orchestrator._active_tasks.add(mock_task1)
    orchestrator._active_tasks.add(mock_task2)

    failed_task = FailedTask(
        task_type="balance_sheet",
        coro_factory=AsyncMock(),
        period="2024_Q3",
        file_name="20240801_10-Q.md",
        exception=LLMError("quality audit failed"),
    )
    orchestrator._failure_queue.append(failed_task)

    with pytest.raises(WorkspaceError) as excinfo:
        await orchestrator._process_failure_queue(ticker, non_interactive=False)

    assert "Execution stopped by user" in str(excinfo.value)

    # All active tasks should be cancelled
    assert mock_task1.cancelled()
    assert mock_task2.cancelled()

    # Task status should be marked as failed
    state = load_workspace_state(ticker)
    assert state.reports["2024_Q3"].balance_sheet_status == "failed"
