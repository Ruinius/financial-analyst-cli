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
