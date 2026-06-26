import pytest
import json
from unittest.mock import patch, MagicMock

from src.agents.modeler_agents.wacc_agent import (
    calculate_wacc_formula,
    run_wacc_agent,
)
from src.core.exceptions import LLMError
from src.core.blackboard import (
    WorkspaceContext,
    CompanyMetadata,
    TemporalBlackboard,
    ExtractedFinancialData,
)


def test_calculate_wacc_formula():
    res = calculate_wacc_formula(
        risk_free_rate=0.04,
        equity_risk_premium=0.05,
        beta=1.0,
        share_price=100.0,
        shares_outstanding=10.0,
        total_debt=500.0,
        cash_and_equivalents=100.0,
        interest_expense=25.0,
        pretax_cost_of_debt=0.0,
        tax_rate=0.20,
        market_cap=0.0,
    )

    assert res["unlevered_beta"] == pytest.approx(1.0 / (1.0 + 0.8 * 0.5))
    assert res["cost_debt_pretax"] == pytest.approx(0.05)
    assert res["cost_debt_aftertax"] == pytest.approx(0.04)
    assert res["cost_equity"] == pytest.approx(0.09)
    assert res["weight_equity"] == pytest.approx(1000.0 / 1500.0)
    assert res["weight_debt"] == pytest.approx(500.0 / 1500.0)
    assert res["wacc_raw"] == pytest.approx((2 / 3) * 0.09 + (1 / 3) * 0.04)
    assert res["wacc_final"] == pytest.approx(res["wacc_raw"])


def test_calculate_wacc_formula_capping():
    # Test that WACC is capped at 11% instead of 15%
    res = calculate_wacc_formula(
        risk_free_rate=0.05,
        equity_risk_premium=0.10,
        beta=2.0,
        share_price=100.0,
        shares_outstanding=10.0,
        total_debt=500.0,
        cash_and_equivalents=100.0,
        interest_expense=50.0,
        pretax_cost_of_debt=0.0,
        tax_rate=0.20,
        market_cap=0.0,
    )

    # Raw equity cost = 0.05 + 2.0 * 0.10 = 0.25 (25%)
    # Weight of equity is 2/3, weight of debt is 1/3, after tax cost of debt is 0.1 * 0.8 = 0.08
    # Raw WACC = 2/3 * 0.25 + 1/3 * 0.08 = 0.1667 + 0.0267 = 0.1933 (19.33%)
    # This should be capped at 11% (0.11)
    assert res["wacc_raw"] > 0.15
    assert res["wacc_final"] == pytest.approx(0.11)


@patch("src.agents.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_wacc_agent(mock_llm_class, mock_curator_class, tmp_path):
    mock_llm = MagicMock()
    mock_llm.settings = MagicMock()
    mock_llm.settings.base_workspace_dir = str(tmp_path)
    mock_chat = MagicMock()
    mock_llm.create_chat.return_value = mock_chat
    mock_chat.get_history.return_value = []
    # Mock LLM turn responses:
    # Turn 0: Call query_blackboard
    # Turn 1: Call calculate_wacc
    # Turn 2: Call finalize
    mock_chat.send_message.side_effect = [
        # Turn 0 tool call
        json.dumps(
            {
                "thought": "I will read the extracted balance sheet file.",
                "tool": "query_blackboard",
                "arguments": {"section": "financial_data", "period": "2023_Q4"},
            }
        ),
        # Turn 1 tool call
        json.dumps(
            {
                "thought": "I have the file. I will calculate WACC now.",
                "tool": "calculate_wacc",
                "arguments": {
                    "risk_free_rate": 0.04,
                    "equity_risk_premium": 0.05,
                    "beta": 1.1,
                    "share_price": 150.0,
                    "shares_outstanding": 10.0,
                    "total_debt": 200.0,
                    "cash_and_equivalents": 50.0,
                    "interest_expense": 10.0,
                    "pretax_cost_of_debt": 0.0,
                    "tax_rate": 0.20,
                },
            }
        ),
        # Turn 2 tool call
        json.dumps(
            {
                "thought": "I will finalize the WACC results.",
                "tool": "finalize",
                "arguments": {
                    "wacc": 0.085,
                    "total_debt": 200.0,
                    "cash_and_equivalents": 50.0,
                    "pretax_cost_of_debt": 0.05,
                    "cost_of_equity": 0.10,
                    "unlevered_beta": 0.95,
                    "explanation": "Calculated successfully using agent tool pipeline.",
                },
            }
        ),
    ]

    company_metadata = CompanyMetadata(ticker="MOCK", company_name="MOCK Corp")
    workspace_state = WorkspaceContext(
        metadata=company_metadata,
        reports={
            "2023_Q4": TemporalBlackboard(
                fiscal_year=2023,
                fiscal_period="Q4",
                is_quarterly=True,
                balance_sheet_status="completed",
                income_statement_status="completed",
                financial_data=ExtractedFinancialData(
                    adjusted_tax_rate=0.20,
                ),
            )
        },
    )

    res = run_wacc_agent(
        client=mock_llm,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key="2023_Q4",
        learnings="Mock learning",
    )

    assert res["wacc"] == 0.085
    assert res["net_debt"] == 150.0
    assert res["unlevered_beta"] == 0.95
    assert res["explanation"] == "Calculated successfully using agent tool pipeline."


@patch("src.agents.curator_agent.CuratorAgent")
def test_run_wacc_agent_llm_failure(mock_curator, tmp_path):
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
                balance_sheet_status="completed",
                income_statement_status="completed",
                financial_data=ExtractedFinancialData(
                    adjusted_tax_rate=0.20,
                ),
            )
        },
    )

    with pytest.raises(LLMError) as exc_info:
        run_wacc_agent(
            client=mock_llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key="2023_Q4",
        )
    assert "WACC Agent failed during LLM generation" in str(exc_info.value)


@patch("src.agents.curator_agent.CuratorAgent")
def test_run_wacc_agent_finalize_failure(mock_curator, tmp_path):
    mock_llm = MagicMock()
    mock_llm.settings = MagicMock()
    mock_llm.settings.base_workspace_dir = str(tmp_path)
    mock_chat = MagicMock()
    mock_llm.create_chat.return_value = mock_chat
    mock_chat.get_history.return_value = []
    # Provide responses that never call the 'finalize' tool
    mock_chat.send_message.return_value = json.dumps(
        {
            "thought": "Let's read a file",
            "tool": "query_blackboard",
            "arguments": {"section": "financial_data"},
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
                balance_sheet_status="completed",
                income_statement_status="completed",
                financial_data=ExtractedFinancialData(
                    adjusted_tax_rate=0.20,
                ),
            )
        },
    )

    with pytest.raises(LLMError) as exc_info:
        run_wacc_agent(
            client=mock_llm,
            company_metadata=company_metadata,
            workspace_state=workspace_state,
            period_key="2023_Q4",
        )
    assert "failed to finalize WACC calculations within the maximum turn limit" in str(
        exc_info.value
    )


@patch("src.agents.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_wacc_agent_with_folder_index(mock_llm_class, mock_curator_class, tmp_path):
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
                "wacc": 0.08,
                "total_debt": 100.0,
                "cash_and_equivalents": 20.0,
                "pretax_cost_of_debt": 0.05,
                "cost_of_equity": 0.09,
                "unlevered_beta": 0.8,
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
                balance_sheet_status="completed",
                income_statement_status="completed",
                financial_data=ExtractedFinancialData(
                    adjusted_tax_rate=0.20,
                ),
            )
        },
    )

    res = run_wacc_agent(
        client=mock_llm,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key="2023_Q4",
    )

    assert res["wacc"] == 0.08
    assert res["net_debt"] == 80.0
    assert res["unlevered_beta"] == 0.8
