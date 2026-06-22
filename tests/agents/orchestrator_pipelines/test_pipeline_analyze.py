import asyncio
from unittest.mock import patch
from pathlib import Path

from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    CompanyMetadata,
    TemporalBlackboard,
    ExtractedFinancialData,
)
from src.agents.blackboard_orchestrator import BlackboardOrchestrator
from src.agents.orchestrator_pipelines.analyze import orchestrate_analyze


@patch("src.agents.curator_agent.CuratorAgent.curate")
@patch("src.agents.indexer_agent.IndexerAgent.run_indexing")
def test_pipeline_analyze_q4_deduction(
    mock_run_indexing, mock_curate, temp_workspace_env
):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()
    workspace = Path(temp_workspace_env.active_workspace_path)

    # 1. Setup metadata and report state with Q1-Q3 and FY completed reports
    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(
        ticker=ticker,
        company_name="Mock Apple Inc.",
        reporting_currency="USD",
        preferred_unit="Millions",
    )

    # Helper to set up reports
    def setup_report(period, rev, ebita, nopat, simple_growth, organic_growth):
        is_q = "Q" in period
        report = TemporalBlackboard(
            fiscal_year=2024,
            fiscal_period=period,
            is_quarterly=is_q,
            balance_sheet_status="completed",
            income_statement_status="completed",
        )
        report.financial_data = ExtractedFinancialData(
            revenue=rev,
            ebita=ebita,
            nopat=nopat,
            operating_income=ebita - 10.0,  # operating_income = EBITA - adjustments
            invested_capital=1000.0,
            basic_shares=500.0,
            diluted_shares=510.0,
            simple_growth=simple_growth,
            organic_growth=organic_growth,
            adjusted_tax_rate=0.21,
            net_working_capital=200.0,
            net_long_term_operating_assets=800.0,
        )
        state.reports[f"2024_{period}"] = report

    # Setup Q1-Q3 (using decimals for growth rates)
    setup_report("Q1", 100.0, 30.0, 24.0, 0.10, 0.08)
    setup_report("Q2", 110.0, 35.0, 28.0, 0.12, 0.10)
    setup_report("Q3", 120.0, 40.0, 32.0, 0.08, 0.07)

    # Setup FY (Annual totals)
    setup_report("FY", 450.0, 140.0, 112.0, 0.11, 0.09)

    save_workspace_state(ticker, state)

    # Run orchestrate_analyze
    asyncio.run(orchestrate_analyze(orchestrator, ticker))

    # 2. Assert Q4 was deduced and stored on the blackboard
    updated_state = load_workspace_state(ticker)
    quarterly_financials = updated_state.company_data.quarterly_financials

    assert len(quarterly_financials) == 4
    q4 = next((q for q in quarterly_financials if q.fiscal_period == "Q4"), None)
    assert q4 is not None

    # Expected Q4 Revenue = 450 - (100 + 110 + 120) = 120
    assert q4.revenue == 120.0

    # Expected Q4 EBITA = 140 - (30 + 35 + 40) = 35
    assert q4.ebita == 35.0

    # Expected Q4 NOPAT = 112 - (24 + 28 + 32) = 28
    assert q4.nopat == 28.0

    # Point-in-time metrics copied from Annual (FY)
    assert q4.invested_capital == 1000.0
    assert q4.diluted_shares == 510.0
    assert q4.basic_shares == 500.0

    # Derived rates
    # Margin = 35 / 120 = 29.17% (HistoricalFinancialSummary margin is calculated as ebita/revenue)
    # capital turnover = 120 * 4 / 1000 = 0.48
    assert q4.capital_turnover == 0.48
    # ROIC = 28 * 4 / 1000 * 100 = 11.20%
    assert q4.roic == 11.20

    # Growth rate checks (backed out fallback rates)
    # Q4 Simple Growth = (ann_rev*ann_growth - q1_rev*q1_growth - ...) / q4_rev
    # ann_simple_inc = 450 * 0.11 = 49.5
    # q1_simple_inc = 100 * 0.10 = 10
    # q2_simple_inc = 110 * 0.12 = 13.2
    # q3_simple_inc = 120 * 0.08 = 9.6
    # q4_simple_inc = 49.5 - 10 - 13.2 - 9.6 = 16.7
    # q4_simple_growth = 16.7 / 120 = 0.139166... which rounds to 0.1392
    assert q4.simple_growth == 0.1392

    # Q4 Organic Growth
    # ann_org_inc = 450 * 0.09 = 40.5
    # q1_org_inc = 100 * 0.08 = 8
    # q2_org_inc = 110 * 0.10 = 11
    # q3_org_inc = 120 * 0.07 = 8.4
    # q4_org_inc = 40.5 - 8 - 11 - 8.4 = 13.1
    # q4_organic_growth = 13.1 / 120 = 0.109166... which rounds to 0.1092
    assert q4.organic_growth == 0.1092

    # 3. Assert flat markdown files were generated
    analysis_dir = workspace / "5_historical_analysis"
    assert (analysis_dir / "financials_quarter.md").exists()
    assert (analysis_dir / "financials_annual.md").exists()
    assert (analysis_dir / "analyst_views.md").exists()
    assert (analysis_dir / "news_trend.md").exists()
    assert (analysis_dir / "transcript_trend.md").exists()

    # Verify content of financials_quarter.md
    quarter_content = (analysis_dir / "financials_quarter.md").read_text(
        encoding="utf-8"
    )
    assert "2024-Q4" in quarter_content
    assert "120.0" in quarter_content

    # 4. Assert IndexerAgent was triggered
    mock_run_indexing.assert_called_once_with(ticker)
