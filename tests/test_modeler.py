import pytest
import json
from unittest.mock import patch, MagicMock, ANY

from src.pipeline.modeler_orchestrator import Modeler


@pytest.fixture
def mock_workspace(tmp_path):
    # Setup mock workspace
    workspace = tmp_path / "MOCK"
    workspace.mkdir(parents=True)

    analysis_dir = workspace / "5_historical_analysis"
    analysis_dir.mkdir(parents=True)

    quarter_path = analysis_dir / "financials_quarter.md"
    quarter_path.write_text(
        "## Historical Financials\n"
        "| Time Period | Period End | Revenue | EBITA | EBITA Margin | Adj Tax Rate | NOPAT | Invested Capital | Capital Turnover | ROIC | Organic Growth | Source Document |\n"
        "|-------------|-----------|---------|-------|--------------|-------------|-------|-----------------|------------------|------|----------------|-----------------|\n"
        "| 2023-Q1     | 2023-03-31 | 1000    | 200   | 20.00%       | 25.00%      | 150   | 500             | 2.0x             | 30.0%| 5.00%          | 10-Q            |\n"
        "| 2023-Q2     | 2023-06-30 | 1100    | 220   | 20.00%       | 25.00%      | 165   | 550             | 2.0x             | 30.0%| 5.00%          | 10-Q            |\n"
        "| 2023-Q3     | 2023-09-30 | 1200    | 240   | 20.00%       | 25.00%      | 180   | 600             | 2.0x             | 30.0%| 5.00%          | 10-Q            |\n"
        "| 2023-Q4     | 2023-12-31 | 1300    | 260   | 20.00%       | 25.00%      | 195   | 650             | 2.0x             | 30.0%| 5.00%          | 10-K            |\n"
    )

    analyst_path = analysis_dir / "analyst_views.md"
    analyst_path.write_text(
        "## Analyst Views\n"
        "| Date | Document | Economic Moat | Moat Rationale | Margin Outlook | Margin Magnitude | Margin Rationale | Growth Outlook | Growth Magnitude | Growth Rationale |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        "| 2023-12-31 | 10-K | Wide | Strong brand | Expanding | +2pp | Good | Expanding | +3pp | Good |\n"
    )

    return workspace


@patch("src.pipeline.modeler_agents.margin_agent.run_margin_agent")
@patch("src.pipeline.modeler_agents.growth_agent.run_growth_agent")
@patch("src.pipeline.modeler_agents.non_operating_agent.run_non_operating_agent")
@patch("src.pipeline.modeler_agents.wacc_agent.run_wacc_agent")
@patch("src.pipeline.modeler_orchestrator.load_config")
@patch("src.services.market_data.get_market_profile")
def test_calculate_default_assumptions(
    mock_get_profile,
    mock_load_config,
    mock_run_wacc_agent,
    mock_run_non_operating_agent,
    mock_run_growth_agent,
    mock_run_margin_agent,
    mock_workspace,
):
    # Mock run_wacc_agent
    mock_run_wacc_agent.return_value = {
        "wacc": 0.08,
        "net_debt": 50.0,
        "explanation": "Calculated mock WACC",
    }

    # Mock run_non_operating_agent
    mock_run_non_operating_agent.return_value = {
        "cash": 10.0,
        "short_term_investments": 0.0,
        "debt": 60.0,
        "preferred_equity": 0.0,
        "minority_interest": 0.0,
        "other_financial": 0.0,
        "explanation": "Calculated mock non-operating categories",
    }

    # Mock run_growth_agent
    mock_run_growth_agent.return_value = {
        "base_growth_rate": 0.05,
        "revenue_growth_rate": 0.08,
        "terminal_growth_rate": 0.03,
        "explanation": "Calculated mock growth rates",
    }

    # Mock run_margin_agent
    mock_run_margin_agent.return_value = {
        "base_margin": 0.21,
        "margin_yr5": 0.24,
        "terminal_margin": 0.23,
        "explanation": "Calculated mock margins",
    }

    # Mock market profile lookup
    mock_get_profile.return_value = {
        "valid": True,
        "share_price": 150.0,
        "market_cap": 1500000000,
        "beta": 1.2,
        "shares_outstanding": 10000000,
    }

    # Mock settings
    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(mock_workspace)
    mock_settings.active_ticker = "MOCK"
    mock_load_config.return_value = mock_settings

    modeler = Modeler()
    assumptions = modeler.calculate_default_assumptions("MOCK", mock_workspace)

    assert assumptions["moat"] == "Wide"
    assert assumptions["base_growth_rate"] == 0.05
    assert assumptions["revenue_growth_rate"] == 0.08
    assert assumptions["terminal_growth_rate"] == 0.03
    assert assumptions["base_margin"] == 0.21
    assert assumptions["margin_yr5"] == 0.24
    assert assumptions["terminal_margin"] == 0.23
    assert assumptions["capital_turnover"] == 2.0
    assert assumptions["wacc"] == 0.08
    assert assumptions["net_debt"] == 50.0
    assert assumptions["cash"] == 10.0
    assert assumptions["short_term_investments"] == 0.0
    assert assumptions["debt"] == 60.0
    assert assumptions["preferred_equity"] == 0.0
    assert assumptions["minority_interest"] == 0.0
    assert assumptions["other_financial"] == 0.0


@patch("src.pipeline.modeler_orchestrator.load_config")
def test_generate_financial_model(mock_load_config, mock_workspace):
    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(mock_workspace)
    mock_settings.active_ticker = "MOCK"
    mock_load_config.return_value = mock_settings

    assumptions = {
        "wacc": 0.10,
        "capital_turnover": 2.0,
        "revenue_growth_rate": 0.10,
        "base_growth_rate": 0.05,
        "margin_yr5": 0.25,
        "base_margin": 0.20,
        "terminal_margin": 0.23,
        "terminal_growth_rate": 0.04,
        "adjusted_tax_rate": 0.21,
        "base_revenue": 1000.0,
        "base_ic": 500.0,
        "shares_outstanding": 100,
        "cash": 10.0,
        "short_term_investments": 0.0,
        "debt": 60.0,
        "preferred_equity": 0.0,
        "minority_interest": 0.0,
        "other_financial": 0.0,
        "net_debt": 50.0,
    }

    modeler = Modeler()
    modeler.generate_financial_model("MOCK", mock_workspace, assumptions)

    model_dir = mock_workspace / "6_financial_model"
    json_dir = mock_workspace / "7_historical_model_json"

    assert list(model_dir.glob("*_model.md"))
    assert list(json_dir.glob("*_0.json"))

    json_path = list(json_dir.glob("*_0.json"))[0]
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["ticker"] == "MOCK"
    assert "valuation" in data
    assert "enterprise_value" in data["valuation"]
    assert "projections" in data
    assert len(data["projections"]) == 10


def test_calculate_wacc_formula():
    from src.pipeline.modeler_agents.wacc_agent import calculate_wacc_formula

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


@patch("src.pipeline.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_wacc_agent(mock_llm_class, mock_curator_class, tmp_path):
    from src.pipeline.modeler_agents.wacc_agent import run_wacc_agent

    mock_llm = MagicMock()
    # Mock LLM turn responses:
    # Turn 0: Call pull_markdown_file
    # Turn 1: Call calculate_wacc
    # Turn 2: Call finalize
    mock_llm.generate.side_effect = [
        # Turn 0 tool call
        json.dumps(
            {
                "thought": "I will read the extracted balance sheet file.",
                "tool": "pull_markdown_file",
                "arguments": {"file_name": "latest_balance_sheet.md"},
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

    mock_workspace = tmp_path / "MOCK"
    mock_workspace.mkdir(parents=True)
    extracted_dir = mock_workspace / "4_extracted_data"
    extracted_dir.mkdir(parents=True)
    (extracted_dir / "latest_balance_sheet.md").write_text(
        "Dummy balance sheet data", encoding="utf-8"
    )

    res = run_wacc_agent(
        ticker="MOCK",
        workspace=mock_workspace,
        share_price=150.0,
        market_cap=1500000000,
        beta=1.1,
        tax_rate=0.20,
        llm=mock_llm,
        learning_context="Mock learning",
    )

    assert res["wacc"] == 0.085
    assert res["net_debt"] == 150.0
    assert res["unlevered_beta"] == 0.95
    assert res["explanation"] == "Calculated successfully using agent tool pipeline."

    # Verify CuratorAgent was instantiated and curate_model_agent called
    mock_curator_class.assert_called_once()
    mock_curator_class.return_value.curate_model_agent.assert_called_once()


@patch("src.pipeline.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_growth_agent(mock_llm_class, mock_curator_class, tmp_path):
    from src.pipeline.modeler_agents.growth_agent import run_growth_agent

    mock_llm = MagicMock()
    # Mock LLM turn responses:
    # Turn 0: Call pull_markdown_file
    # Turn 1: Call finalize
    mock_llm.generate.side_effect = [
        # Turn 0 tool call
        json.dumps(
            {
                "thought": "I will read the analyst views file.",
                "tool": "pull_markdown_file",
                "arguments": {"file_name": "analyst_views.md"},
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

    mock_workspace = tmp_path / "MOCK"
    mock_workspace.mkdir(parents=True)
    analysis_dir = mock_workspace / "5_historical_analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "analyst_views.md").write_text(
        "Dummy analyst views data", encoding="utf-8"
    )

    res = run_growth_agent(
        ticker="MOCK",
        workspace=mock_workspace,
        base_growth_rate=0.05,
        target_growth_yr5=0.08,
        terminal_growth_rate=0.03,
        llm=mock_llm,
        learning_context="Mock learning",
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


@patch("src.pipeline.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_margin_agent(mock_llm_class, mock_curator_class, tmp_path):
    from src.pipeline.modeler_agents.margin_agent import run_margin_agent

    mock_llm = MagicMock()
    # Mock LLM turn responses:
    # Turn 0: Call pull_markdown_file
    # Turn 1: Call finalize
    mock_llm.generate.side_effect = [
        # Turn 0 tool call
        json.dumps(
            {
                "thought": "I will read the analyst views file.",
                "tool": "pull_markdown_file",
                "arguments": {"file_name": "analyst_views.md"},
            }
        ),
        # Turn 1 tool call
        json.dumps(
            {
                "thought": "I will finalize the margin assumptions.",
                "tool": "finalize",
                "arguments": {
                    "base_margin": 0.22,
                    "margin_yr5": 0.25,
                    "terminal_margin": 0.24,
                    "explanation": "Decided based on recent stable operating trends and cost cutting.",
                },
            }
        ),
    ]

    mock_workspace = tmp_path / "MOCK"
    mock_workspace.mkdir(parents=True)
    analysis_dir = mock_workspace / "5_historical_analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "analyst_views.md").write_text(
        "Dummy analyst views data", encoding="utf-8"
    )

    res = run_margin_agent(
        ticker="MOCK",
        workspace=mock_workspace,
        base_margin=0.20,
        margin_yr5=0.23,
        terminal_margin=0.23,
        llm=mock_llm,
        learning_context="Mock learning",
    )

    assert res["base_margin"] == 0.22
    assert res["margin_yr5"] == 0.25
    assert res["terminal_margin"] == 0.24
    assert (
        res["explanation"]
        == "Decided based on recent stable operating trends and cost cutting."
    )

    # Verify CuratorAgent was instantiated and curate_model_agent called
    mock_curator_class.assert_called_once()
    mock_curator_class.return_value.curate_model_agent.assert_called_once_with(
        "MOCK", "Margin", ANY
    )


@patch("src.pipeline.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_non_operating_agent(mock_llm_class, mock_curator_class, tmp_path):
    from src.pipeline.modeler_agents.non_operating_agent import run_non_operating_agent

    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps(
        {
            "cash": 20.0,
            "short_term_investments": 10.0,
            "debt": 100.0,
            "preferred_equity": 5.0,
            "minority_interest": 0.0,
            "other_financial": -2.0,
            "explanation": "Mocked successful extraction.",
        }
    )

    mock_workspace = tmp_path / "MOCK"
    mock_workspace.mkdir(parents=True)
    extracted_dir = mock_workspace / "4_extracted_data"
    extracted_dir.mkdir(parents=True)

    # Write mock *_extracted.md and *_balance_sheet.md
    extracted_file = extracted_dir / "20260617_MOCK_10Q_extracted.md"
    extracted_file.write_text(
        "#### Non-Operating Assets\n- Cash: 20\n- ST Investments: 10\n"
        "#### Non-Operating Liabilities\n- Debt: 100\n",
        encoding="utf-8",
    )

    bs_file = extracted_dir / "20260617_MOCK_10Q_balance_sheet.md"
    bs_file.write_text("Balance sheet details", encoding="utf-8")

    res = run_non_operating_agent(
        ticker="MOCK",
        workspace=mock_workspace,
        llm=mock_llm,
    )

    assert res["cash"] == 20.0
    assert res["short_term_investments"] == 10.0
    assert res["debt"] == 100.0
    assert res["preferred_equity"] == 5.0
    assert res["minority_interest"] == 0.0
    assert res["other_financial"] == -2.0
    assert res["explanation"] == "Mocked successful extraction."

    mock_curator_class.assert_called_once()
    mock_curator_class.return_value.curate_model_agent.assert_called_once()


def test_calculate_wacc_formula_capping():
    from src.pipeline.modeler_agents.wacc_agent import calculate_wacc_formula

    # Test that WACC is capped at 11% instead of 15%
    # Using high raw beta & equity risk premium to push WACC above 11%
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


@patch("src.pipeline.curator_agent.CuratorAgent")
def test_run_wacc_agent_llm_failure(mock_curator, tmp_path):
    from src.pipeline.modeler_agents.wacc_agent import run_wacc_agent
    from src.core.exceptions import LLMError

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("API error")

    with pytest.raises(LLMError) as exc_info:
        run_wacc_agent(
            ticker="MOCK",
            workspace=tmp_path,
            share_price=150.0,
            market_cap=1500000000,
            beta=1.1,
            tax_rate=0.20,
            llm=mock_llm,
        )
    assert "WACC Agent failed during LLM generation" in str(exc_info.value)


@patch("src.pipeline.curator_agent.CuratorAgent")
def test_run_wacc_agent_finalize_failure(mock_curator, tmp_path):
    from src.pipeline.modeler_agents.wacc_agent import run_wacc_agent
    from src.core.exceptions import LLMError

    mock_llm = MagicMock()
    # Provide 4 responses that never call the 'finalize' tool
    mock_llm.generate.return_value = json.dumps(
        {
            "thought": "Let's read a file",
            "tool": "pull_markdown_file",
            "arguments": {"file_name": "none.md"},
        }
    )

    with pytest.raises(LLMError) as exc_info:
        run_wacc_agent(
            ticker="MOCK",
            workspace=tmp_path,
            share_price=150.0,
            market_cap=1500000000,
            beta=1.1,
            tax_rate=0.20,
            llm=mock_llm,
        )
    assert "failed to finalize WACC calculations within the maximum turn limit" in str(
        exc_info.value
    )


@patch("src.pipeline.curator_agent.CuratorAgent")
def test_run_growth_agent_llm_failure(mock_curator, tmp_path):
    from src.pipeline.modeler_agents.growth_agent import run_growth_agent
    from src.core.exceptions import LLMError

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("API error")

    with pytest.raises(LLMError):
        run_growth_agent(
            ticker="MOCK",
            workspace=tmp_path,
            base_growth_rate=0.05,
            target_growth_yr5=0.08,
            terminal_growth_rate=0.03,
            llm=mock_llm,
        )


@patch("src.pipeline.curator_agent.CuratorAgent")
def test_run_growth_agent_finalize_failure(mock_curator, tmp_path):
    from src.pipeline.modeler_agents.growth_agent import run_growth_agent
    from src.core.exceptions import LLMError

    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps(
        {
            "thought": "Let's read a file",
            "tool": "pull_markdown_file",
            "arguments": {"file_name": "none.md"},
        }
    )

    with pytest.raises(LLMError) as exc_info:
        run_growth_agent(
            ticker="MOCK",
            workspace=tmp_path,
            base_growth_rate=0.05,
            target_growth_yr5=0.08,
            terminal_growth_rate=0.03,
            llm=mock_llm,
        )
    assert "failed to finalize growth rate assumptions" in str(exc_info.value)


@patch("src.pipeline.curator_agent.CuratorAgent")
def test_run_margin_agent_llm_failure(mock_curator, tmp_path):
    from src.pipeline.modeler_agents.margin_agent import run_margin_agent
    from src.core.exceptions import LLMError

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("API error")

    with pytest.raises(LLMError):
        run_margin_agent(
            ticker="MOCK",
            workspace=tmp_path,
            base_margin=0.20,
            margin_yr5=0.23,
            terminal_margin=0.23,
            llm=mock_llm,
        )


@patch("src.pipeline.curator_agent.CuratorAgent")
def test_run_margin_agent_finalize_failure(mock_curator, tmp_path):
    from src.pipeline.modeler_agents.margin_agent import run_margin_agent
    from src.core.exceptions import LLMError

    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps(
        {
            "thought": "Let's read a file",
            "tool": "pull_markdown_file",
            "arguments": {"file_name": "none.md"},
        }
    )

    with pytest.raises(LLMError) as exc_info:
        run_margin_agent(
            ticker="MOCK",
            workspace=tmp_path,
            base_margin=0.20,
            margin_yr5=0.23,
            terminal_margin=0.23,
            llm=mock_llm,
        )
    assert "failed to finalize EBITA margin assumptions" in str(exc_info.value)


@patch("src.pipeline.curator_agent.CuratorAgent")
def test_run_non_operating_agent_missing_files(mock_curator, tmp_path):
    from src.pipeline.modeler_agents.non_operating_agent import run_non_operating_agent
    from src.core.exceptions import WorkspaceError

    mock_llm = MagicMock()

    # Empty workspace, no extracted financial files
    with pytest.raises(WorkspaceError) as exc_info:
        run_non_operating_agent(
            ticker="MOCK",
            workspace=tmp_path,
            llm=mock_llm,
        )
    assert (
        "No extracted financial files found containing non-operating sections"
        in str(exc_info.value)
    )


@patch("src.pipeline.curator_agent.CuratorAgent")
def test_run_non_operating_agent_llm_failure(mock_curator, tmp_path):
    from src.pipeline.modeler_agents.non_operating_agent import run_non_operating_agent
    from src.core.exceptions import LLMError

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("API error")

    # Create dummy files so file-finding check passes
    extracted_dir = tmp_path / "4_extracted_data"
    extracted_dir.mkdir(parents=True)
    (extracted_dir / "20260617_MOCK_10Q_extracted.md").write_text(
        "#### Non-Operating Assets\n- Cash: 20\n", encoding="utf-8"
    )

    with pytest.raises(LLMError):
        run_non_operating_agent(
            ticker="MOCK",
            workspace=tmp_path,
            llm=mock_llm,
        )


@patch("src.pipeline.curator_agent.CuratorAgent")
def test_run_non_operating_agent_invalid_json(mock_curator, tmp_path):
    from src.pipeline.modeler_agents.non_operating_agent import run_non_operating_agent
    from src.core.exceptions import LLMError

    mock_llm = MagicMock()
    mock_llm.generate.return_value = "invalid response, no json here"

    # Create dummy files so file-finding check passes
    extracted_dir = tmp_path / "4_extracted_data"
    extracted_dir.mkdir(parents=True)
    (extracted_dir / "20260617_MOCK_10Q_extracted.md").write_text(
        "#### Non-Operating Assets\n- Cash: 20\n", encoding="utf-8"
    )

    with pytest.raises(LLMError) as exc_info:
        run_non_operating_agent(
            ticker="MOCK",
            workspace=tmp_path,
            llm=mock_llm,
        )
    assert "LLM response did not contain a valid JSON object" in str(exc_info.value)


@patch("src.pipeline.modeler_agents.margin_agent.run_margin_agent")
@patch("src.pipeline.modeler_agents.growth_agent.run_growth_agent")
@patch("src.pipeline.modeler_agents.non_operating_agent.run_non_operating_agent")
@patch("src.pipeline.modeler_agents.wacc_agent.run_wacc_agent")
@patch("src.pipeline.modeler_orchestrator.load_config")
@patch("src.services.market_data.get_market_profile")
def test_calculate_default_assumptions_ltm_unavailable(
    mock_get_profile,
    mock_load_config,
    mock_run_wacc_agent,
    mock_run_non_operating_agent,
    mock_run_growth_agent,
    mock_run_margin_agent,
    tmp_path,
):
    workspace = tmp_path / "MOCK"
    workspace.mkdir(parents=True)
    analysis_dir = workspace / "5_historical_analysis"
    analysis_dir.mkdir(parents=True)

    # Only 2 quarters available -> LTM not available
    quarter_path = analysis_dir / "financials_quarter.md"
    quarter_path.write_text(
        "## Historical Financials\n"
        "| Time Period | Period End | Revenue | EBITA | EBITA Margin | Adj Tax Rate | NOPAT | Invested Capital | Capital Turnover | ROIC | Organic Growth | Source Document |\n"
        "|-------------|-----------|---------|-------|--------------|-------------|-------|-----------------|------------------|------|----------------|-----------------|\n"
        "| 2023-Q1     | 2023-03-31 | 1000    | 200   | 20.00%       | 25.00%      | 150   | 500             | 2.0x             | 30.0%| 5.00%          | 10-Q            |\n"
        "| 2023-Q2     | 2023-06-30 | 1100    | 220   | 20.00%       | 35.00%      | 165   | 600             | 2.0x             | 30.0%| 5.00%          | 10-Q            |\n"
    )

    analyst_path = analysis_dir / "analyst_views.md"
    analyst_path.write_text(
        "## Analyst Views\n"
        "| Date | Document | Economic Moat | Moat Rationale | Margin Outlook | Margin Magnitude | Margin Rationale | Growth Outlook | Growth Magnitude | Growth Rationale |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        "| 2023-06-30 | 10-Q | Wide | Strong brand | Expanding | +2pp | Good | Expanding | +3pp | Good |\n"
    )

    # Mock all external calls
    mock_run_wacc_agent.return_value = {
        "wacc": 0.08,
        "net_debt": 50.0,
        "explanation": "Calculated mock WACC",
    }
    mock_run_non_operating_agent.return_value = {
        "cash": 10.0,
        "short_term_investments": 0.0,
        "debt": 60.0,
        "preferred_equity": 0.0,
        "minority_interest": 0.0,
        "other_financial": 0.0,
        "explanation": "Calculated mock non-operating categories",
    }
    mock_run_growth_agent.return_value = {
        "base_growth_rate": 0.05,
        "revenue_growth_rate": 0.08,
        "terminal_growth_rate": 0.03,
        "explanation": "Calculated mock growth rates",
    }
    mock_run_margin_agent.return_value = {
        "base_margin": 0.21,
        "margin_yr5": 0.24,
        "terminal_margin": 0.23,
        "explanation": "Calculated mock margins",
    }
    mock_get_profile.return_value = {
        "valid": True,
        "share_price": 150.0,
        "market_cap": 1500000000,
        "beta": 1.2,
        "shares_outstanding": 10000000,
    }
    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_settings.active_ticker = "MOCK"
    mock_load_config.return_value = mock_settings

    modeler = Modeler()
    assumptions = modeler.calculate_default_assumptions("MOCK", workspace)

    assert assumptions["ltm_warning"] is True
    # 2 quarters: 1000 + 1100 = 2100. Annualized (2100 * 4 / 2) = 4200.0
    assert assumptions["base_revenue"] == pytest.approx(4200.0)
    # Invested Capital: median of [500, 600] = 550.0
    assert assumptions["base_ic"] == pytest.approx(550.0)
    # Adjusted Tax: median of all available [25%, 35%] = 30% = 0.30
    assert assumptions["adjusted_tax_rate"] == pytest.approx(0.30)


@patch("src.pipeline.modeler_orchestrator.load_config")
def test_generate_financial_model_mid_year_and_markdown(mock_load_config, tmp_path):
    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(tmp_path)
    mock_settings.active_ticker = "MOCK"
    mock_load_config.return_value = mock_settings

    assumptions = {
        "wacc": 0.10,
        "capital_turnover": 2.0,
        "revenue_growth_rate": 0.10,
        "base_growth_rate": 0.05,
        "margin_yr5": 0.25,
        "base_margin": 0.20,
        "terminal_margin": 0.23,
        "terminal_growth_rate": 0.04,
        "adjusted_tax_rate": 0.21,
        "base_revenue": 1000.0,
        "base_ic": 500.0,
        "shares_outstanding": 100,
        "cash": 10.0,
        "short_term_investments": 0.0,
        "debt": 60.0,
        "preferred_equity": 0.0,
        "minority_interest": 0.0,
        "other_financial": 0.0,
        "net_debt": 50.0,
        "ltm_warning": True,
    }

    # Setup financials_quarter.md in historical analysis directory
    analysis_dir = tmp_path / "5_historical_analysis"
    analysis_dir.mkdir(parents=True)
    quarter_path = analysis_dir / "financials_quarter.md"
    quarter_path.write_text(
        "## Historical Financials\n"
        "| Time Period | Period End | Revenue | EBITA | EBITA Margin | Adj Tax Rate | NOPAT | Invested Capital | Capital Turnover | ROIC | Organic Growth | Source Document |\n"
        "|-------------|-----------|---------|-------|--------------|-------------|-------|-----------------|------------------|------|----------------|-----------------|\n"
        "| 2023-Q1     | 2023-03-31 | 1000    | 200   | 20.00%       | 25.00%      | 150   | 500             | 2.0x             | 30.0%| 5.00%          | 10-Q            |\n"
    )

    modeler = Modeler()
    modeler.generate_financial_model("MOCK", tmp_path, assumptions)

    model_dir = tmp_path / "6_financial_model"
    md_files = list(model_dir.glob("*_model.md"))
    assert len(md_files) == 1

    md_content = md_files[0].read_text(encoding="utf-8")

    # Check that warning callout is in markdown
    assert "[!WARNING]" in md_content
    assert "LTM is absolutely not available" in md_content

    # Check that columns are correct
    assert "Time Period" in md_content
    assert "Revenue ($M)" in md_content
    assert "Discount Factor" in md_content
    assert "Discounted FCF" in md_content

    # Check that Base (Year 0), historical quarter 2023-Q1, Year 1, and Terminal rows are present
    assert "2023-Q1" in md_content
    assert "Base (Year 0)" in md_content
    assert "Year 1" in md_content
    assert "Terminal" in md_content

    # Check that the Valuation table is present and formatted correctly
    assert "| Field | Value |" in md_content
    assert "| Enterprise Value |" in md_content
    assert "| (+) Cash and Equivalents |" in md_content
    assert "| (-) Total Debt |" in md_content
    assert "| **Equity Value** |" in md_content
    assert "| Diluted Shares Outstanding |" in md_content
    assert "| **Intrinsic Value Per Share** |" in md_content
    assert "| Currency |" in md_content
    assert "| FX Rate Applied |" in md_content
    assert "| ADR Ratio Applied |" in md_content
    assert "| Current Market Price |" in md_content
    assert "| **Upside/Downside** |" in md_content
    assert "| Calculation Date |" in md_content


@patch("src.pipeline.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_wacc_agent_with_folder_index(mock_llm_class, mock_curator_class, tmp_path):
    from src.pipeline.modeler_agents.wacc_agent import run_wacc_agent

    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps(
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

    # Setup index file in the workspace root
    index_file = tmp_path / "MOCK_folder_index.md"
    index_content = (
        "# Test Folder Index WACC\n- File: 4_extracted_data/latest_balance_sheet.md"
    )
    index_file.write_text(index_content, encoding="utf-8")

    res = run_wacc_agent(
        ticker="MOCK",
        workspace=tmp_path,
        share_price=100.0,
        market_cap=1000000.0,
        beta=1.0,
        tax_rate=0.20,
        llm=mock_llm,
    )

    assert res["wacc"] == 0.08
    assert res["net_debt"] == 80.0
    assert res["unlevered_beta"] == 0.8

    # Verify LLM was prompted with index content
    args, kwargs = mock_llm.generate.call_args
    prompt_arg = args[0]
    assert "Test Folder Index WACC" in prompt_arg
    assert "latest_balance_sheet.md" in prompt_arg


@patch("src.pipeline.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_growth_agent_with_folder_index(
    mock_llm_class, mock_curator_class, tmp_path
):
    from src.pipeline.modeler_agents.growth_agent import run_growth_agent

    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps(
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

    # Setup index file in the workspace root
    index_file = tmp_path / "MOCK_folder_index.md"
    index_content = (
        "# Test Folder Index Growth\n- File: 5_historical_analysis/analyst_views.md"
    )
    index_file.write_text(index_content, encoding="utf-8")

    res = run_growth_agent(
        ticker="MOCK",
        workspace=tmp_path,
        base_growth_rate=0.05,
        target_growth_yr5=0.08,
        terminal_growth_rate=0.03,
        llm=mock_llm,
    )

    assert res["base_growth_rate"] == 0.05
    assert res["revenue_growth_rate"] == 0.06
    assert res["terminal_growth_rate"] == 0.03

    # Verify LLM was prompted with index content
    args, kwargs = mock_llm.generate.call_args
    prompt_arg = args[0]
    assert "Test Folder Index Growth" in prompt_arg
    assert "analyst_views.md" in prompt_arg


@patch("src.pipeline.curator_agent.CuratorAgent")
@patch("src.services.llm_client.LLMClient")
def test_run_margin_agent_with_folder_index(
    mock_llm_class, mock_curator_class, tmp_path
):
    from src.pipeline.modeler_agents.margin_agent import run_margin_agent

    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps(
        {
            "thought": "Using index file, finalizing.",
            "tool": "finalize",
            "arguments": {
                "base_margin": 0.20,
                "margin_yr5": 0.22,
                "terminal_margin": 0.21,
                "explanation": "Calculated successfully using index.",
            },
        }
    )

    # Setup index file in the workspace root
    index_file = tmp_path / "MOCK_folder_index.md"
    index_content = "# Test Folder Index Margin\n- File: 5_historical_analysis/financials_quarter.md"
    index_file.write_text(index_content, encoding="utf-8")

    res = run_margin_agent(
        ticker="MOCK",
        workspace=tmp_path,
        base_margin=0.20,
        margin_yr5=0.23,
        terminal_margin=0.23,
        llm=mock_llm,
    )

    assert res["base_margin"] == 0.20
    assert res["margin_yr5"] == 0.22
    assert res["terminal_margin"] == 0.21

    # Verify LLM was prompted with index content
    args, kwargs = mock_llm.generate.call_args
    prompt_arg = args[0]
    assert "Test Folder Index Margin" in prompt_arg
    assert "financials_quarter.md" in prompt_arg


def test_run_dcf_modeling_agent(tmp_path):
    from src.pipeline.modeler_agents.dcf_modeling_agent import run_dcf_modeling_agent

    mock_llm = MagicMock()
    # Mock LLM turn sequences:
    # Turn 0: Call pull_historical_analysis_file
    # Turn 1: Call get_market_data
    # Turn 2: Call run_valuation with overridden parameters
    # Turn 3: Call finalize
    mock_llm.generate.side_effect = [
        json.dumps(
            {
                "thought": "I will read financials_quarter.md",
                "tool": "pull_historical_analysis_file",
                "arguments": {"file_name": "financials_quarter.md"},
            }
        ),
        json.dumps(
            {
                "thought": "Let's check the current market price and currency.",
                "tool": "get_market_data",
                "arguments": {},
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
                    "comments": "The valuation result aligns well with historical trends. A WACC of 9.0% represents a reasonable cost of capital.",
                },
            }
        ),
    ]

    analysis_dir = tmp_path / "5_historical_analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "financials_quarter.md").write_text(
        "historical metrics", encoding="utf-8"
    )

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

    final_assumptions, comments, history_text = run_dcf_modeling_agent(
        ticker="MOCK",
        workspace=tmp_path,
        base_assumptions=base_assumptions,
        llm=mock_llm,
        learning_context="Use correct currency",
    )

    assert final_assumptions["wacc"] == 0.09
    assert final_assumptions["revenue_growth_rate"] == 0.08
    assert "valuation result aligns well" in comments.lower()
    assert "pull_historical_analysis_file" in history_text
    assert "get_market_data" in history_text
    assert "run_valuation" in history_text
