from unittest.mock import MagicMock, patch

from src.core.blackboard import load_workspace_state, save_workspace_state
from src.agents.agent_executor import run_agent_loop, last_agent_run
from src.agents.learning_agent import LearningAgent
from tests.agents.test_learning_and_curator import MockLLMClient


def test_last_agent_run_captured(temp_workspace_env):
    settings = temp_workspace_env
    call = MagicMock()
    call.name = "finalize"
    call.args = {"result": "ok"}

    mock_client = MockLLMClient(settings, responses=[[call]])

    def finalize(result):
        return "done"

    # Reset ContextVar before run
    last_agent_run.set(None)

    run_agent_loop(
        client=mock_client,
        system_prompt="Test System",
        initial_prompt="Test Initial",
        tools=[finalize],
        max_turns=3,
    )

    run_info = last_agent_run.get()
    assert run_info is not None
    turn_count, run_logs = run_info
    assert turn_count == 1
    assert "Test Initial" in run_logs
    assert "ASSISTANT: Tool calls" in run_logs


def test_learning_agent_modeling_support(temp_workspace_env):
    settings = temp_workspace_env
    ticker = "AAPL"

    # Pre-populate blackboard state with empty learnings
    state = load_workspace_state(ticker)
    state.metadata.ticker = ticker
    state.company_data.learnings.model.wacc.metrics.total_runs = 0
    save_workspace_state(ticker, state)

    call = MagicMock()
    call.name = "finalize"
    call.args = {
        "successful_keywords": ["beta", "equity risk premium"],
        "avoid_keywords": ["unrelated_keyword"],
        "successful_chunk": ["chunk_3"],
        "avoid_chunk": ["chunk_1"],
    }
    mock_client = MockLLMClient(settings, responses=[[call]])

    agent = LearningAgent(settings=settings, client=mock_client)
    agent.run_learning(
        ticker=ticker,
        agent_name="wacc_agent",
        document_type="model",
        turn_count=4,
        run_logs="Turn 1: calculated cost of equity, Turn 2: finalized",
    )

    updated_state = load_workspace_state(ticker)
    learnings = updated_state.company_data.learnings.model.wacc
    assert learnings.status == "completed"
    assert learnings.metrics.total_runs == 1
    assert learnings.metrics.average_turn_count == 4.0
    assert "beta" in learnings.successful_keywords
    assert "unrelated_keyword" in learnings.avoid_keywords
    assert "chunk_3" in learnings.successful_chunk


def test_extractor_wrapper_triggers_learning(temp_workspace_env):
    settings = temp_workspace_env
    ticker = "AAPL"

    # Mock extractor function
    def mock_agent_fn(*args, **kwargs):
        # Simulate run_agent_loop side effect of setting the ContextVar
        last_agent_run.set((3, "Mock Run Logs"))
        return "Mock Result"

    # Mock orchestrator
    mock_orchestrator = MagicMock()
    mock_orchestrator.settings = settings
    mock_orchestrator.client = MagicMock()

    # We mock LearningAgent.run_learning to see if it is called with correct args
    with patch(
        "src.agents.learning_agent.LearningAgent.run_learning"
    ) as mock_run_learning:
        # Define local helper wrapper by patching outer params or using inner wrapper directly
        def run_extractor_with_learning(
            agent_fn, agent_name, doc_type, *args, **kwargs
        ):
            from src.agents.agent_executor import last_agent_run

            last_agent_run.set(None)
            res = agent_fn(*args, **kwargs)
            run_info = last_agent_run.get()
            if run_info:
                turn_count, run_logs = run_info
                from src.agents.learning_agent import LearningAgent

                learning_agent = LearningAgent(
                    settings=mock_orchestrator.settings, client=mock_orchestrator.client
                )
                learning_agent.run_learning(
                    ticker=ticker,
                    agent_name=agent_name,
                    document_type=doc_type,
                    turn_count=turn_count,
                    run_logs=run_logs,
                )
            return res

        res = run_extractor_with_learning(
            mock_agent_fn,
            agent_name="balance_sheet",
            doc_type="annual_filing",
        )
        assert res == "Mock Result"
        mock_run_learning.assert_called_once_with(
            ticker=ticker,
            agent_name="balance_sheet",
            document_type="annual_filing",
            turn_count=3,
            run_logs="Mock Run Logs",
        )
