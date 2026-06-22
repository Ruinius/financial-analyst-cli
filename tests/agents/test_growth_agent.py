import pytest
import json
from unittest.mock import patch, MagicMock, ANY

from src.agents.modeler_agents.growth_agent import run_growth_agent
from src.core.exceptions import LLMError
from src.core.blackboard import (
    WorkspaceContext,
    CompanyMetadata,
    TemporalBlackboard,
    HistoricalFinancialSummary,
    CompanyLevelData,
)


@patch("src.agents.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_growth_agent(mock_llm_class, mock_curator_class, tmp_path):
    mock_llm = MagicMock()
    mock_llm.settings = MagicMock()
    mock_llm.settings.base_workspace_dir = str(tmp_path)
    mock_chat = MagicMock()
    mock_llm.create_chat.return_value = mock_chat
    mock_chat.get_history.return_value = []
    # Mock LLM turn responses:
    # Turn 0: Call query_blackboard
    # Turn 1: Call finalize
    mock_chat.send_message.side_effect = [
        # Turn 0 tool call
        json.dumps(
            {
                "thought": "I will read the analyst views file from blackboard.",
                "tool": "query_blackboard",
                "arguments": {"section": "company_data"},
            }
        ),
        # Turn 1 tool call
        json.dumps(
            {
                "thought": "I will finalize the growth rate assumptions.",
                "tool": "finalize",
                "arguments": {
                    "base_growth_rate": 0.06,
                    "revenue_growth_rate": 0.075,
                    "terminal_growth_rate": 0.035,
                    "explanation": "Decided based on recent stable quarters and moat strength.",
                },
            }
        ),
    ]

    company_metadata = CompanyMetadata(ticker="MOCK", company_name="MOCK Corp")
    workspace_state = WorkspaceContext(
        metadata=company_metadata,
        company_data=CompanyLevelData(
            quarterly_financials=[
                HistoricalFinancialSummary(
                    fiscal_year=2023,
                    fiscal_period="Q4",
                    revenue=1300.0,
                    operating_income=260.0,
                    ebita=260.0,
                    reported_tax_provision=52.0,
                    adjusted_taxes=52.0,
                    adjusted_tax_rate=20.0,
                    basic_shares=10.0,
                    diluted_shares=10.0,
                    simple_growth=5.0,
                    organic_growth=5.0,
                    net_working_capital=100.0,
                    net_long_term_operating_assets=400.0,
                    invested_capital=500.0,
                    capital_turnover=2.6,
                    nopat=208.0,
                    roic=41.6,
                )
            ]
        ),
        reports={
            "2023_Q4": TemporalBlackboard(
                fiscal_year=2023,
                fiscal_period="Q4",
                is_quarterly=True,
            )
        },
    )

    res = run_growth_agent(
        client=mock_llm,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key="2023_Q4",
        learnings="Mock learning",
    )

    assert res["base_growth_rate"] == 0.06
    assert res["revenue_growth_rate"] == 0.075
    assert res["terminal_growth_rate"] == 0.035
    assert (
        res["explanation"]
        == "Decided based on recent stable quarters and moat strength."
    )

    # Verify CuratorAgent was instantiated and curate_model_agent called
    mock_curator_class.assert_called_once()
    mock_curator_class.return_value.curate_model_agent.assert_called_once_with(
        "MOCK", "Growth", ANY
    )


@patch("src.agents.curator_agent.CuratorAgent")
def test_run_growth_agent_llm_failure(mock_curator, tmp_path):
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
        run_growth_agent(
            client=mock_llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key="2023_Q4",
        )


@patch("src.agents.curator_agent.CuratorAgent")
def test_run_growth_agent_finalize_failure(mock_curator, tmp_path):
    mock_llm = MagicMock()
    mock_llm.settings = MagicMock()
    mock_llm.settings.base_workspace_dir = str(tmp_path)
    mock_chat = MagicMock()
    mock_llm.create_chat.return_value = mock_chat
    mock_chat.get_history.return_value = []
    mock_chat.send_message.return_value = json.dumps(
        {
            "thought": "Let's read a file",
            "tool": "query_blackboard",
            "arguments": {"section": "company_data"},
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
            )
        },
    )

    with pytest.raises(LLMError) as exc_info:
        run_growth_agent(
            client=mock_llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key="2023_Q4",
        )
    assert "failed to finalize growth rate assumptions" in str(exc_info.value)


@patch("src.agents.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_growth_agent_with_folder_index(
    mock_llm_class, mock_curator_class, tmp_path
):
    mock_llm = MagicMock()
    mock_llm.settings = MagicMock()
    mock_llm.settings.base_workspace_dir = str(tmp_path)
    mock_chat = MagicMock()
    mock_llm.create_chat.return_value = mock_chat
    mock_chat.get_history.return_value = []
    mock_chat.send_message.return_value = json.dumps(
        {
            "thought": "Using index file, finalizing.",
            "tool": "finalize",
            "arguments": {
                "base_growth_rate": 0.05,
                "revenue_growth_rate": 0.06,
                "terminal_growth_rate": 0.03,
                "explanation": "Calculated successfully using index.",
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
            )
        },
    )

    res = run_growth_agent(
        client=mock_llm,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key="2023_Q4",
    )

    assert res["base_growth_rate"] == 0.05
    assert res["revenue_growth_rate"] == 0.06
    assert res["terminal_growth_rate"] == 0.03
