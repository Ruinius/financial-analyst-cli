from unittest.mock import patch
import json
from unittest.mock import MagicMock

from src.agents.modeler_agents.dcf_modeling_agent import run_dcf_modeling_agent
from src.core.blackboard import (
    WorkspaceContext,
    CompanyMetadata,
    TemporalBlackboard,
)


@patch("src.agents.orchestrator_pipelines.model.load_config")
def test_run_dcf_modeling_agent(mock_load_config, tmp_path):
    mock_llm = MagicMock()
    mock_llm.settings = MagicMock()
    mock_llm.settings.base_workspace_dir = str(tmp_path)
    mock_load_config.return_value = mock_llm.settings
    mock_chat = MagicMock()
    mock_llm.create_chat.return_value = mock_chat
    # Needs history object return for get_history(), which is a list of dictionary representations of turns
    mock_chat.get_history.return_value = [
        {"role": "user", "content": "Estimate the parameters..."},
        {
            "role": "model",
            "content": "I will read financials_quarter.md via query_blackboard",
        },
        {"role": "user", "content": "Here is the blackboard content..."},
        {"role": "model", "content": "Let's check the metadata."},
        {"role": "user", "content": "Here is the metadata..."},
        {
            "role": "model",
            "content": "I want to run a test valuation with run_valuation.",
        },
        {"role": "user", "content": "Valuation results: ..."},
        {
            "role": "model",
            "content": "Perfect, WACC is 9%, Growth is 8%. Valuation makes sense. Finalizing.",
        },
    ]
    # Mock LLM turn sequences:
    # Turn 0: Call query_blackboard
    # Turn 1: Call query_blackboard (metadata)
    # Turn 2: Call run_valuation with overridden parameters
    # Turn 3: Call finalize
    mock_chat.send_message.side_effect = [
        json.dumps(
            {
                "thought": "I will read financials_quarter.md via query_blackboard",
                "tool": "query_blackboard",
                "arguments": {"section": "financial_data"},
            }
        ),
        json.dumps(
            {
                "thought": "Let's check the metadata.",
                "tool": "query_blackboard",
                "arguments": {"section": "metadata"},
            }
        ),
        json.dumps(
            {
                "thought": "I want to run a test valuation.",
                "tool": "run_valuation",
                "arguments": {
                    "wacc": 0.09,
                    "revenue_growth_rate": 0.08,
                },
            }
        ),
        json.dumps(
            {
                "thought": "Perfect, WACC is 9%, Growth is 8%. Valuation makes sense. Finalizing.",
                "tool": "finalize",
                "arguments": {
                    "assumptions": {
                        "wacc": 0.09,
                        "revenue_growth_rate": 0.08,
                        "base_revenue": 1000.0,
                        "base_margin": 0.20,
                        "base_ic": 500.0,
                        "shares_outstanding": 100,
                        "margin_yr5": 0.22,
                        "terminal_growth_rate": 0.03,
                        "adjusted_tax_rate": 0.25,
                        "base_growth_rate": 0.05,
                        "capital_turnover": 2.0,
                    },
                    "comments_arg": "The valuation result aligns well with historical trends. A WACC of 9.0% represents a reasonable cost of capital.",
                },
            }
        ),
    ]

    base_assumptions = {
        "wacc": 0.08,
        "revenue_growth_rate": 0.07,
        "base_revenue": 1000.0,
        "base_margin": 0.20,
        "base_ic": 500.0,
        "shares_outstanding": 100,
        "margin_yr5": 0.22,
        "terminal_growth_rate": 0.03,
        "adjusted_tax_rate": 0.25,
        "base_growth_rate": 0.05,
        "capital_turnover": 2.0,
    }

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

    final_assumptions, comments, history_text = run_dcf_modeling_agent(
        client=mock_llm,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key="2023_Q4",
        base_assumptions=base_assumptions,
        learnings="Use correct currency",
    )

    assert final_assumptions["wacc"] == 0.09
    assert final_assumptions["revenue_growth_rate"] == 0.08
    assert "valuation result aligns well" in comments.lower()
    assert "query_blackboard" in history_text
    assert "run_valuation" in history_text
