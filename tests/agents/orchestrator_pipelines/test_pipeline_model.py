import pytest
import json
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.agents.orchestrator_pipelines.model import Modeler
from src.agents.blackboard_orchestrator import BlackboardOrchestrator
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    CompanyMetadata,
    TemporalBlackboard,
)
from src.core.exceptions import WorkspaceError


@patch("src.agents.modeler_agents.margin_agent.run_margin_agent")
@patch("src.agents.modeler_agents.growth_agent.run_growth_agent")
@patch("src.agents.modeler_agents.non_operating_agent.run_non_operating_agent")
@patch("src.agents.modeler_agents.wacc_agent.run_wacc_agent")
@patch("src.agents.orchestrator_pipelines.model.load_config")
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
    mock_settings.base_workspace_dir = str(mock_workspace.parent)
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


@patch("src.agents.orchestrator_pipelines.model.load_config")
def test_generate_financial_model(mock_load_config, mock_workspace):
    mock_settings = MagicMock()
    mock_settings.base_workspace_dir = str(mock_workspace.parent)
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

    json_dir = mock_workspace / "9_scenario_model_json"

    assert not (mock_workspace / "6_financial_model").exists()
    assert list(json_dir.glob("*_0.json"))

    json_path = list(json_dir.glob("*_0.json"))[0]
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["ticker"] == "MOCK"
    assert "valuation" in data
    assert "enterprise_value" in data["valuation"]
    assert "projections" in data
    assert len(data["projections"]) == 10


@patch("src.agents.modeler_agents.margin_agent.run_margin_agent")
@patch("src.agents.modeler_agents.growth_agent.run_growth_agent")
@patch("src.agents.modeler_agents.non_operating_agent.run_non_operating_agent")
@patch("src.agents.modeler_agents.wacc_agent.run_wacc_agent")
@patch("src.agents.orchestrator_pipelines.model.load_config")
@patch("src.services.market_data.get_market_profile")
def test_calculate_default_assumptions_ltm_unavailable(
    mock_get_profile,
    mock_load_config,
    mock_run_wacc_agent,
    mock_run_non_operating_agent,
    mock_run_growth_agent,
    mock_run_margin_agent,
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "MOCK"
    workspace.mkdir(parents=True)
    fake_config_path = tmp_path / ".env"
    monkeypatch.setattr("src.core.config.CONFIG_FILE_PATH", fake_config_path)
    from src.core.config import Settings, save_config

    settings = Settings(
        full_name="Test Developer",
        email="developer@example.com",
        project_name="TestProject",
        base_workspace_dir=str(tmp_path),
        active_workspace_path=str(workspace),
        active_ticker="MOCK",
    )
    save_config(settings)
    state_file = workspace / "workspace_state.json"
    state_data = {
        "metadata": {"ticker": "MOCK", "company_name": "Mock Company"},
        "metadata_status": "completed",
        "company_data": {
            "quarterly_financials": [
                {
                    "fiscal_year": 2023,
                    "fiscal_period": "Q1",
                    "revenue": 1000.0,
                    "operating_income": 200.0,
                    "ebita": 200.0,
                    "reported_tax_provision": 50.0,
                    "adjusted_taxes": 50.0,
                    "adjusted_tax_rate": 0.25,
                    "basic_shares": 10.0,
                    "diluted_shares": 10.0,
                    "simple_growth": 0.05,
                    "organic_growth": 0.05,
                    "net_working_capital": 100.0,
                    "net_long_term_operating_assets": 400.0,
                    "invested_capital": 500.0,
                    "capital_turnover": 2.0,
                    "nopat": 150.0,
                    "roic": 30.0,
                },
                {
                    "fiscal_year": 2023,
                    "fiscal_period": "Q2",
                    "revenue": 1100.0,
                    "operating_income": 220.0,
                    "ebita": 220.0,
                    "reported_tax_provision": 77.0,
                    "adjusted_taxes": 77.0,
                    "adjusted_tax_rate": 0.35,
                    "basic_shares": 10.0,
                    "diluted_shares": 10.0,
                    "simple_growth": 0.05,
                    "organic_growth": 0.05,
                    "net_working_capital": 110.0,
                    "net_long_term_operating_assets": 440.0,
                    "invested_capital": 600.0,
                    "capital_turnover": 2.0,
                    "nopat": 165.0,
                    "roic": 30.0,
                },
            ],
            "historical_analyst_views": [
                {
                    "report_date": "2023-06-30",
                    "source_file": "10-Q",
                    "economic_moat": "Wide",
                    "economic_moat_rationale": "Strong brand",
                    "margin_outlook": "Expanding",
                    "margin_magnitude": "+2pp",
                    "margin_rationale": "Good",
                    "growth_outlook": "Expanding",
                    "growth_magnitude": "+3pp",
                    "growth_rationale": "Good",
                }
            ],
        },
    }
    state_file.write_text(json.dumps(state_data), encoding="utf-8")

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
    mock_settings.base_workspace_dir = str(workspace.parent)
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


@patch("src.agents.orchestrator_pipelines.model.load_config")
def test_generate_financial_model_mid_year_and_markdown(
    mock_load_config, tmp_path, monkeypatch
):
    workspace = tmp_path / "MOCK"
    workspace.mkdir(parents=True, exist_ok=True)
    fake_config_path = tmp_path / ".env"
    monkeypatch.setattr("src.core.config.CONFIG_FILE_PATH", fake_config_path)
    from src.core.config import Settings, save_config

    settings = Settings(
        full_name="Test Developer",
        email="developer@example.com",
        project_name="TestProject",
        base_workspace_dir=str(tmp_path),
        active_workspace_path=str(workspace),
        active_ticker="MOCK",
    )
    save_config(settings)

    mock_settings = MagicMock()
    mock_settings.base_workspace_dir = str(workspace.parent)
    mock_settings.active_workspace_path = str(workspace)
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

    state_file = workspace / "workspace_state.json"
    state_data = {
        "metadata": {"ticker": "MOCK", "company_name": "Mock Company"},
        "metadata_status": "completed",
        "company_data": {
            "quarterly_financials": [
                {
                    "fiscal_year": 2023,
                    "fiscal_period": "Q1",
                    "revenue": 1000.0,
                    "operating_income": 200.0,
                    "ebita": 200.0,
                    "reported_tax_provision": 50.0,
                    "adjusted_taxes": 50.0,
                    "adjusted_tax_rate": 0.25,
                    "basic_shares": 10.0,
                    "diluted_shares": 10.0,
                    "simple_growth": 0.05,
                    "organic_growth": 0.05,
                    "net_working_capital": 100.0,
                    "net_long_term_operating_assets": 400.0,
                    "invested_capital": 500.0,
                    "capital_turnover": 2.0,
                    "nopat": 150.0,
                    "roic": 30.0,
                }
            ]
        },
    }
    state_file.write_text(json.dumps(state_data), encoding="utf-8")

    mock_settings.base_workspace_dir = str(workspace.parent)
    mock_settings.active_workspace_path = str(workspace)

    modeler = Modeler()
    modeler.generate_financial_model("MOCK", workspace, assumptions)

    json_dir = workspace / "9_scenario_model_json"
    json_files = list(json_dir.glob("*.json"))
    assert len(json_files) == 1

    with open(json_files[0], "r", encoding="utf-8") as f:
        data = json.load(f)

    # Check that assumptions and projections are correct in JSON
    assert data["ticker"] == "MOCK"
    assert data["assumptions"]["ltm_warning"] is True
    assert "valuation" in data
    assert "projections" in data
    assert len(data["projections"]) == 10
    assert not (workspace / "6_financial_model").exists()


@patch("src.agents.orchestrator_pipelines.model.load_config")
@patch("src.agents.orchestrator_pipelines.model.Modeler.calculate_default_assumptions")
@patch("src.agents.orchestrator_pipelines.model.Modeler.estimate_llm_assumptions")
@patch(
    "src.agents.orchestrator_pipelines.model.Modeler.propose_and_validate_assumptions"
)
@patch("src.agents.orchestrator_pipelines.model.Modeler.generate_financial_model")
@patch("src.agents.orchestrator_pipelines.model.CuratorAgent")
@patch("src.agents.orchestrator_pipelines.model.IndexerAgent", create=True)
@patch("src.cli.commands.use.main_use")
def test_run_modeling_curator_calls(
    mock_main_use,
    mock_indexer_class,
    mock_curator_class,
    mock_generate,
    mock_propose,
    mock_estimate,
    mock_calculate,
    mock_load_config,
    temp_workspace_env,
):
    workspace = Path(temp_workspace_env.base_workspace_dir) / "MOCK"
    workspace.mkdir(parents=True, exist_ok=True)
    # Write a minimal blackboard state with quarterly_financials so modeling is not skipped
    state_file = workspace / "workspace_state.json"
    state_data = {
        "metadata": {"ticker": "MOCK", "company_name": "Mock Company"},
        "metadata_status": "completed",
        "company_data": {
            "quarterly_financials": [
                {
                    "fiscal_year": 2023,
                    "fiscal_period": "Q1",
                    "revenue": 1000.0,
                    "operating_income": 200.0,
                    "ebita": 200.0,
                    "reported_tax_provision": 50.0,
                    "adjusted_taxes": 50.0,
                    "adjusted_tax_rate": 0.25,
                    "basic_shares": 10.0,
                    "diluted_shares": 10.0,
                    "simple_growth": 0.05,
                    "organic_growth": 0.05,
                    "net_working_capital": 100.0,
                    "net_long_term_operating_assets": 400.0,
                    "invested_capital": 500.0,
                    "capital_turnover": 2.0,
                    "nopat": 150.0,
                    "roic": 30.0,
                }
            ]
        },
    }
    import json

    state_file.write_text(json.dumps(state_data), encoding="utf-8")

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_settings.active_ticker = "MOCK"
    mock_load_config.return_value = mock_settings

    mock_calculate.return_value = {
        "wacc_explanation": "WACC logic",
        "growth_explanation": "Growth logic",
        "margin_explanation": "Margin logic",
        "non_operating_explanation": "Non-Operating logic",
    }
    mock_estimate.return_value = {
        "dcf_agent_log": "DCF agent logs here",
    }
    mock_propose.side_effect = lambda ticker, ws, assumptions: assumptions

    modeler = Modeler()
    modeler.run_modeling("MOCK")

    # Assert main_use was called with the ticker
    mock_main_use.assert_called_once_with("MOCK")

    # Assert CuratorAgent was called twice
    assert mock_curator_class.call_count == 2

    # Verify calls to curate
    curator_mock_inst = mock_curator_class.return_value
    assert curator_mock_inst.curate.call_count == 2

    first_call_args = curator_mock_inst.curate.call_args_list[0]
    second_call_args = curator_mock_inst.curate.call_args_list[1]

    # First run before DCF: update_wiki=False
    assert first_call_args[0][0] == "MOCK"
    assert first_call_args[0][1] == "model"
    assert "WACC logic" in first_call_args[0][2]
    assert first_call_args[1].get("update_wiki") is False

    # Second run after DCF: update_wiki=True
    assert second_call_args[0][0] == "MOCK"
    assert second_call_args[0][1] == "model"
    assert "DCF agent logs here" in second_call_args[0][2]
    assert second_call_args[1].get("update_wiki") is True


def test_single_agent_model_missing_metadata(temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()

    with pytest.raises(WorkspaceError) as exc_info:
        asyncio.run(orchestrator.run_pipeline(ticker, stage="model", agent="wacc"))

    assert "Company metadata extraction must be completed first" in str(exc_info.value)


@patch("src.agents.blackboard_orchestrator.run_wacc_agent")
def test_single_agent_model_wacc_success(mock_run_wacc, temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker=ticker, company_name="Mock Apple Inc.")

    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
        balance_sheet_status="completed",
        income_statement_status="completed",
    )
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()
    mock_run_wacc.return_value = {
        "wacc": 0.085,
        "cost_equity": 0.095,
        "cost_debt_pretax": 0.065,
        "weight_equity": 0.8,
        "weight_debt": 0.2,
        "explanation": "Calculated mock WACC",
    }

    asyncio.run(orchestrator.run_pipeline(ticker, stage="model", agent="wacc"))

    mock_run_wacc.assert_called_once()
    updated_state = load_workspace_state(ticker)
    assert updated_state.reports["2024_Q3"].wacc_agent_status == "completed"
    assert updated_state.reports["2024_Q3"].base_model.assumptions.wacc == 0.085
