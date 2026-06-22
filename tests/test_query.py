from unittest.mock import patch
from typer.testing import CliRunner

from src.cli.commands.query import app, console

from src.core.blackboard import (
    WorkspaceContext,
    CompanyMetadata,
    CompanyLevelData,
    HistoricalFinancialSummary,
    HistoricalAnalystView,
    TemporalBlackboard,
    BaseFinancialModel,
    ModelAssumptions,
    DCFProjectionYear,
    RawDocumentState,
    LineItem,
    ExtractedFinancialData,
)

console.width = 200
runner = CliRunner()


@patch("src.cli.commands.query.load_workspace_state")
def test_query_summary(mock_load_state):
    ticker = "AAPL"
    state = WorkspaceContext(
        metadata=CompanyMetadata(ticker=ticker),
        company_data=CompanyLevelData(
            yearly_financials=[
                HistoricalFinancialSummary(
                    fiscal_year=2024,
                    fiscal_period="FY",
                    revenue=380000.0,
                    operating_income=110000.0,
                    ebita=115000.0,
                    reported_tax_provision=20000.0,
                    adjusted_taxes=21000.0,
                    adjusted_tax_rate=0.18,
                    basic_shares=15000.0,
                    diluted_shares=15200.0,
                    simple_growth=0.06,
                    organic_growth=0.07,
                    net_working_capital=5000.0,
                    net_long_term_operating_assets=45000.0,
                    invested_capital=50000.0,
                    capital_turnover=7.6,
                    nopat=94000.0,
                    roic=1.88,
                )
            ],
            quarterly_financials=[
                HistoricalFinancialSummary(
                    fiscal_year=2024,
                    fiscal_period="Q3",
                    revenue=95000.0,
                    operating_income=27000.0,
                    ebita=28000.0,
                    reported_tax_provision=5000.0,
                    adjusted_taxes=5200.0,
                    adjusted_tax_rate=0.185,
                    basic_shares=15000.0,
                    diluted_shares=15200.0,
                    simple_growth=0.05,
                    organic_growth=0.055,
                    net_working_capital=5000.0,
                    net_long_term_operating_assets=45000.0,
                    invested_capital=50000.0,
                    capital_turnover=7.6,
                    nopat=23000.0,
                    roic=0.46,
                )
            ],
        ),
    )
    mock_load_state.return_value = state

    result = runner.invoke(app, ["summary", ticker])
    assert result.exit_code == 0
    assert "Annual Financials" in result.stdout
    assert "2024_FY" in result.stdout
    assert "$380,000.00" in result.stdout
    assert "2024_Q3" in result.stdout
    assert "$95,000.00" in result.stdout


@patch("src.cli.commands.query.load_workspace_state")
def test_query_assessment(mock_load_state):
    ticker = "AAPL"
    state = WorkspaceContext(
        metadata=CompanyMetadata(ticker=ticker),
        company_data=CompanyLevelData(
            historical_analyst_views=[
                HistoricalAnalystView(
                    report_date="2024-08-01",
                    source_file="report.pdf",
                    economic_moat="Wide Moat",
                    economic_moat_rationale="Strong brand and ecosystem",
                    margin_outlook="Stable",
                    margin_magnitude="High",
                    margin_rationale="Pricing power",
                    growth_outlook="Moderate",
                    growth_magnitude="Single digit",
                    growth_rationale="Services expansion",
                )
            ]
        ),
    )
    mock_load_state.return_value = state

    result = runner.invoke(app, ["assessment", ticker])
    assert result.exit_code == 0
    assert "Analyst View from 2024-08-01" in result.stdout
    assert "Wide Moat" in result.stdout
    assert "Strong brand" in result.stdout


@patch("src.cli.commands.query.load_workspace_state")
def test_query_valuation(mock_load_state):
    ticker = "AAPL"
    base_model = BaseFinancialModel(
        assumptions=ModelAssumptions(
            wacc=0.08,
            company_beta_levered=1.1,
            company_beta_unlevered=1.0,
            industry_beta_unlevered=0.9,
            risk_free_rate=0.04,
            equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06,
            cost_of_equity=0.095,
            weight_equity=0.8,
            weight_debt=0.2,
            target_debt_to_equity=0.25,
            interest_expense=1000.0,
            capital_turnover=2.0,
            base_revenue=380000.0,
            base_invested_capital=100000.0,
            revenue_growth_base=0.08,
            revenue_growth_yr5=0.06,
            ebita_margin_base=0.25,
            ebita_margin_yr5=0.26,
            terminal_margin=0.25,
            terminal_growth_rate=0.03,
            adjusted_tax_rate=0.21,
            excess_cash=10000.0,
            short_term_investments=20000.0,
            debt=30000.0,
            preferred_equity=0.0,
            minority_interest=0.0,
            other_financial_assets_net=5000.0,
            net_debt=0.0,
            shares_outstanding=15000.0,
            share_price=180.0,
            market_cap=2700000.0,
        ),
        projections=[
            DCFProjectionYear(
                year=2025,
                revenue=410400.0,
                growth=0.08,
                ebita=106704.0,
                margin=0.26,
                nopat=84296.16,
                reinvestment=15000.0,
                invested_capital=115000.0,
                roic=0.73,
                fcf=69296.16,
                discount_factor=0.925,
                present_value=64100.0,
            )
        ],
        calculated_intrinsic_value_per_share=210.5,
        calculated_equity_value=3157500.0,
        calculated_enterprise_value=3127500.0,
        upside_downside_percentage="16.9%",
        dcf_run_date="2026-06-22",
    )

    report = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="FY",
        is_quarterly=False,
        base_model=base_model,
    )

    state = WorkspaceContext(
        metadata=CompanyMetadata(ticker=ticker), reports={"2024_FY": report}
    )
    mock_load_state.return_value = state

    result = runner.invoke(app, ["valuation", ticker])
    assert result.exit_code == 0
    assert "Valuation Report (2024_FY)" in result.stdout
    assert "210.50" in result.stdout
    assert "16.9%" in result.stdout
    assert "WACC" in result.stdout
    assert "Cost of Equity" in result.stdout


@patch("src.cli.commands.query.load_workspace_state")
def test_query_trace(mock_load_state):
    ticker = "AAPL"
    report = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
        source_files=["20240801_10-Q.md"],
        balance_sheet_status="completed",
        income_statement_status="completed",
        financial_data=ExtractedFinancialData(
            revenue=95000.0,
            line_items=[
                LineItem(
                    line_name="Total Current Assets",
                    value=150000.0,
                    operating=True,
                    calculated=False,
                    category="current_assets",
                )
            ],
        ),
    )
    state = WorkspaceContext(
        metadata=CompanyMetadata(ticker=ticker),
        raw_documents=[
            RawDocumentState(
                file_name="20240801_10-Q.md",
                sha256="abc123sha",
                ingestion_status="completed",
            )
        ],
        metadata_status="completed",
        analyzer_status="completed",
        curator_status="pending",
        reports={"2024_Q3": report},
    )
    mock_load_state.return_value = state

    # Trace without filters
    result = runner.invoke(app, ["trace", ticker])
    assert result.exit_code == 0
    assert "20240801_10-Q.md" in result.stdout
    assert "Metadata Extraction" in result.stdout
    assert "Balance Sheet: completed" in result.stdout

    # Trace with metric option
    result_metric = runner.invoke(app, ["trace", ticker, "--metric", "Current Assets"])
    assert result_metric.exit_code == 0
    assert "Total Current Assets" in result_metric.stdout
    assert "150,000.00" in result_metric.stdout

    # Trace with period option
    result_period = runner.invoke(app, ["trace", ticker, "--period", "2024_Q3"])
    assert result_period.exit_code == 0
    assert "Period: 2024_Q3" in result_period.stdout
