import pytest
import json
from unittest.mock import patch, MagicMock

from src.pipeline.modeler import Modeler


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


@patch("src.pipeline.modeler.load_config")
@patch("src.services.market_data.get_market_profile")
def test_calculate_default_assumptions(
    mock_get_profile, mock_load_config, mock_workspace
):
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
    assert assumptions["terminal_growth_rate"] == 0.04
    assert assumptions["base_revenue"] == 4600.0  # 1000 + 1100 + 1200 + 1300
    assert assumptions["margin_yr5"] == pytest.approx(
        (200 + 220 + 240 + 260) / 4600.0 + 0.02
    )  # base + 2pp
    assert assumptions["revenue_growth_rate"] == pytest.approx(
        0.05 + 0.03
    )  # base + 3pp
    assert assumptions["capital_turnover"] == 2.0
    assert assumptions["wacc"] > 0.0


@patch("src.pipeline.modeler.load_config")
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
        "terminal_growth_rate": 0.04,
        "adjusted_tax_rate": 0.21,
        "base_revenue": 1000.0,
        "base_ic": 500.0,
        "shares_outstanding": 100,
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
