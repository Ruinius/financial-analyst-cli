import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.core.config import Settings, save_config
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
)
from src.services.llm_client import LLMClient, ChatSession
from src.agents.agent_executor import run_agent_loop
from src.agents.learning_agent import LearningAgent
from src.agents.curator_agent import CuratorAgent


class MockChatSession(ChatSession):
    def __init__(self, responses, history=None):
        self.responses = list(responses)
        self.history = history if history is not None else []
        self.sent_messages = []

    def send_message(self, message: str, tool_responses=None):
        self.sent_messages.append((message, tool_responses))
        self.history.append({"role": "user", "content": message})
        if tool_responses:
            for r in tool_responses:
                self.history.append(
                    {
                        "role": "user",
                        "content": f"Observation {r['name']}: {r['content']}",
                    }
                )

        # Return next response
        if self.responses:
            resp = self.responses.pop(0)
            if isinstance(resp, list):
                self.history.append(
                    {"role": "assistant", "content": f"Tool calls: {resp}"}
                )
            else:
                self.history.append({"role": "assistant", "content": resp})
            return resp
        return "No more mock responses"

    def get_history(self):
        return self.history


class MockLLMClient(LLMClient):
    def __init__(self, settings, responses):
        super().__init__(settings)
        self.responses = responses

    def generate(
        self,
        prompt,
        system_prompt=None,
        model=None,
        temperature=0.1,
        stream_thinking=True,
    ):
        return "Mock response"

    def generate_structured(
        self, prompt, response_schema, system_prompt=None, model=None, temperature=0.1
    ):
        return response_schema()

    def create_chat(self, system_prompt=None, tools=None, model=None, temperature=0.1):
        return MockChatSession(self.responses)


@pytest.fixture
def temp_workspace_env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
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
        # Create ticker workspace dir
        (tmp_path / "workspace" / "AAPL").mkdir(parents=True, exist_ok=True)
        yield settings


def test_progressive_turn_warning(temp_workspace_env):
    settings = temp_workspace_env
    # We simulate 3 turns. Turn 1 (initial), Turn 2, and Turn 3 (critical).
    # response 1: tool call to 'keyword_search'
    # response 2: tool call to 'finalize'
    call1 = MagicMock()
    call1.name = "keyword_search"
    call1.args = {"keywords": ["test"]}

    call2 = MagicMock()
    call2.name = "finalize"
    call2.args = {"result": "success"}

    mock_client = MockLLMClient(settings, responses=[[call1], [call2]])

    def keyword_search(keywords):
        return "found some results"

    def finalize(result):
        return "finalized"

    tools = [keyword_search, finalize]

    finalized_args, history = run_agent_loop(
        client=mock_client,
        system_prompt="Test agent",
        initial_prompt="Hello",
        tools=tools,
        max_turns=3,
        average_turn_count=2.5,
    )

    assert finalized_args == {"result": "success"}
    # Let's inspect raw contents
    history_str = str(history)
    assert "Turn 1 of 3" in history_str
    assert "Remaining turn allowance: 3" in history_str
    assert "Historical average runs for this task: 2.5 turns" in history_str


def test_learning_agent_no_deviation(temp_workspace_env):
    settings = temp_workspace_env
    ticker = "AAPL"

    # Pre-populate state with metrics: runs=1, avg_turns=5.0
    state = load_workspace_state(ticker)
    state.metadata.ticker = ticker
    state.company_data.learnings.annual_filing.balance_sheet.metrics.total_runs = 1
    state.company_data.learnings.annual_filing.balance_sheet.metrics.average_turn_count = 5.0
    state.company_data.learnings.annual_filing.balance_sheet.metrics.last_turn_count = 5
    save_workspace_state(ticker, state)

    # Trigger with turn_count = 5 (no deviation, shouldn't trigger LLM updates)
    mock_client = MockLLMClient(settings, responses=[])
    agent = LearningAgent(settings=settings, client=mock_client)

    agent.run_learning(
        ticker=ticker,
        agent_name="balance_sheet",
        document_type="annual_filing",
        turn_count=5,
        run_logs="Turn 1: searched, Turn 2: finalized",
    )

    # Metrics should be updated: runs=2, avg_turns=5.0
    updated_state = load_workspace_state(ticker)
    metrics = updated_state.company_data.learnings.annual_filing.balance_sheet.metrics
    assert metrics.total_runs == 2
    assert metrics.last_turn_count == 5
    assert metrics.average_turn_count == 5.0


def test_learning_agent_with_deviation(temp_workspace_env):
    settings = temp_workspace_env
    ticker = "AAPL"

    # Pre-populate state
    state = load_workspace_state(ticker)
    state.metadata.ticker = ticker
    state.company_data.learnings.annual_filing.balance_sheet.metrics.total_runs = 1
    state.company_data.learnings.annual_filing.balance_sheet.metrics.average_turn_count = 5.0
    state.company_data.learnings.annual_filing.balance_sheet.metrics.last_turn_count = 5
    save_workspace_state(ticker, state)

    # Turn count = 8 (deviation is 3.0 >= 1.0, should trigger LLM learning run)
    call = MagicMock()
    call.name = "finalize"
    call.args = {
        "successful_keywords": ["balance sheet", "consolidated"],
        "avoid_keywords": ["unrelated"],
        "successful_chunk": ["12"],
        "avoid_chunk": ["4"],
    }
    mock_client = MockLLMClient(settings, responses=[[call]])
    agent = LearningAgent(settings=settings, client=mock_client)

    agent.run_learning(
        ticker=ticker,
        agent_name="balance_sheet",
        document_type="annual_filing",
        turn_count=8,
        run_logs="Some logs",
    )

    # Check state updates
    updated_state = load_workspace_state(ticker)
    agent_learning = updated_state.company_data.learnings.annual_filing.balance_sheet
    assert agent_learning.status == "completed"
    assert "balance sheet" in agent_learning.successful_keywords
    assert "unrelated" in agent_learning.avoid_keywords
    assert "12" in agent_learning.successful_chunk
    assert "4" in agent_learning.avoid_chunk

    # Metrics should be: runs=2, avg_turns = (5.0 + 8) / 2 = 6.5
    assert agent_learning.metrics.total_runs == 2
    assert agent_learning.metrics.average_turn_count == 6.5
    assert agent_learning.metrics.last_turn_count == 8


def test_curator_agent_wiki(temp_workspace_env):
    settings = temp_workspace_env
    ticker = "AAPL"

    # Prepare some reports and metadata on the blackboard
    state = load_workspace_state(ticker)
    state.metadata.company_name = "Apple Inc."
    state.metadata.description = "Smartphone maker"
    save_workspace_state(ticker, state)

    # Mock the LLM to finalize compiled content
    call = MagicMock()
    call.name = "finalize"
    call.args = {
        "content": "# Wiki: AAPL\n\n## Bull Perspective\n- Apple has strong cash flow.\n\n## Bear Perspective\n- Hardware cycles are slow."
    }

    mock_client = MockLLMClient(settings, responses=[[call]])

    with patch(
        "src.agents.curator_agent.get_llm_client", return_ok=True
    ) as mock_get_llm:
        mock_get_llm.return_value = mock_client
        curator = CuratorAgent(settings=settings)
        curator.curate_wiki(ticker)

    # Check if wiki file was written atomically and matches the content
    wiki_path = Path(settings.active_workspace_path) / f"{ticker}_wiki.md"
    assert wiki_path.exists()
    wiki_content = wiki_path.read_text(encoding="utf-8")
    assert "Apple has strong cash flow" in wiki_content
    assert "Hardware cycles are slow" in wiki_content
