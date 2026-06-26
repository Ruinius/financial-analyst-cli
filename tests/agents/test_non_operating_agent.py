import pytest
import json
from unittest.mock import patch, MagicMock

from src.agents.modeler_agents.non_operating_agent import run_non_operating_agent
from src.core.exceptions import LLMError
from src.core.blackboard import (
    WorkspaceContext,
    CompanyMetadata,
    TemporalBlackboard,
    LineItem,
    ExtractedFinancialData,
)


@patch("src.agents.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_non_operating_agent(mock_llm_class, mock_curator_class, tmp_path):
    mock_llm = MagicMock()
    mock_llm.settings = MagicMock()
    mock_llm.settings.base_workspace_dir = str(tmp_path)
    mock_chat = MagicMock()
    mock_llm.create_chat.return_value = mock_chat
    mock_chat.get_history.return_value = []
    mock_chat.send_message.return_value = json.dumps(
        {
            "thought": "I will finalize the non-operating extraction.",
            "tool": "finalize",
            "arguments": {
                "cash": 20.0,
                "short_term_investments": 10.0,
                "debt": 100.0,
                "preferred_equity": 5.0,
                "minority_interest": 0.0,
                "other_financial": -2.0,
                "explanation": "Mocked successful extraction.",
            },
        }
    )

    company_metadata = CompanyMetadata(ticker="MOCK", company_name="MOCK Corp")
    workspace_state = WorkspaceContext(
        metadata=company_metadata,
        reports={
            "2023_Q4": TemporalBlackboard(
                fiscal_year=2023,
                fiscal_period="Q4",
                is_quarterly=True,
                financial_data=ExtractedFinancialData(
                    line_items=[
                        LineItem(
                            line_name="Cash and cash equivalents",
                            value=20.0,
                            operating=False,
                            category="current_assets",
                        ),
                        LineItem(
                            line_name="Short-term investments",
                            value=10.0,
                            operating=False,
                            category="current_assets",
                        ),
                        LineItem(
                            line_name="Long-term debt",
                            value=100.0,
                            operating=False,
                            category="noncurrent_liabilities",
                        ),
                    ]
                ),
            )
        },
    )

    res = run_non_operating_agent(
        client=mock_llm,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key="2023_Q4",
    )

    assert res["cash"] == 20.0
    assert res["short_term_investments"] == 10.0
    assert res["debt"] == 100.0
    assert res["preferred_equity"] == 5.0
    assert res["minority_interest"] == 0.0
    assert res["other_financial"] == -2.0
    assert res["explanation"] == "Mocked successful extraction."


@patch("src.agents.curator_agent.CuratorAgent")
def test_run_non_operating_agent_missing_files(mock_curator, tmp_path):
    mock_llm = MagicMock()
    company_metadata = CompanyMetadata(ticker="MOCK", company_name="MOCK Corp")
    workspace_state = WorkspaceContext(
        metadata=company_metadata,
        reports={},  # Missing target period to trigger pre-flight check failure
    )

    res = run_non_operating_agent(
        client=mock_llm,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key="2023_Q4",
    )
    assert res["status"] == "failed"
    assert "Missing dependency" in res["error"]


@patch("src.agents.curator_agent.CuratorAgent")
def test_run_non_operating_agent_llm_failure(mock_curator, tmp_path):
    mock_llm = MagicMock()
    mock_llm.settings = MagicMock()
    mock_llm.settings.base_workspace_dir = str(tmp_path)
    mock_chat = MagicMock()
    mock_llm.create_chat.return_value = mock_chat
    mock_chat.get_history.return_value = []
    mock_chat.send_message.side_effect = Exception("API error")

    company_metadata = CompanyMetadata(ticker="MOCK", company_name="MOCK Corp")
    workspace_state = WorkspaceContext(
        metadata=company_metadata,
        reports={
            "2023_Q4": TemporalBlackboard(
                fiscal_year=2023,
                fiscal_period="Q4",
                is_quarterly=True,
            )
        },
    )

    with pytest.raises(LLMError):
        run_non_operating_agent(
            client=mock_llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key="2023_Q4",
        )


@patch("src.agents.curator_agent.CuratorAgent")
def test_run_non_operating_agent_invalid_json(mock_curator, tmp_path):
    mock_llm = MagicMock()
    mock_llm.settings = MagicMock()
    mock_llm.settings.base_workspace_dir = str(tmp_path)
    mock_chat = MagicMock()
    mock_llm.create_chat.return_value = mock_chat
    mock_chat.get_history.return_value = []
    mock_chat.send_message.return_value = "invalid response, no json here"

    company_metadata = CompanyMetadata(ticker="MOCK", company_name="MOCK Corp")
    workspace_state = WorkspaceContext(
        metadata=company_metadata,
        reports={
            "2023_Q4": TemporalBlackboard(
                fiscal_year=2023,
                fiscal_period="Q4",
                is_quarterly=True,
            )
        },
    )

    with pytest.raises(LLMError) as exc_info:
        run_non_operating_agent(
            client=mock_llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key="2023_Q4",
        )
    assert "failed to finalize non-operating extraction" in str(exc_info.value)
