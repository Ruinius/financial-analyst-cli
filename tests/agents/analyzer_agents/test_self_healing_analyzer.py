from unittest.mock import MagicMock, patch

from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    CompanyMetadata,
    TemporalBlackboard,
    ExtractedFinancialData,
    HistoricalFinancialSummary,
    LineItem,
)
from src.agents.analyzer_agents.self_healing_analyzer import (
    run_self_healing_analyzer_agent,
    format_summary_tables_for_prompt,
)


def test_format_summary_tables_for_prompt():
    q = [
        HistoricalFinancialSummary(
            fiscal_year=2024,
            fiscal_period="Q1",
            revenue=100.0,
            operating_income=20.0,
            ebita=25.0,
            reported_tax_provision=5.0,
            adjusted_taxes=5.0,
            adjusted_tax_rate=0.20,
            basic_shares=10.0,
            diluted_shares=10.0,
            simple_growth=0.05,
            organic_growth=0.05,
            net_working_capital=50.0,
            net_long_term_operating_assets=150.0,
            invested_capital=200.0,
            capital_turnover=2.0,
            nopat=20.0,
            roic=40.0,
        )
    ]
    y = [
        HistoricalFinancialSummary(
            fiscal_year=2023,
            fiscal_period="FY",
            revenue=400.0,
            operating_income=80.0,
            ebita=90.0,
            reported_tax_provision=18.0,
            adjusted_taxes=18.0,
            adjusted_tax_rate=0.20,
            basic_shares=10.0,
            diluted_shares=10.0,
            simple_growth=0.10,
            organic_growth=0.10,
            net_working_capital=60.0,
            net_long_term_operating_assets=140.0,
            invested_capital=200.0,
            capital_turnover=2.0,
            nopat=72.0,
            roic=36.0,
        )
    ]

    res = format_summary_tables_for_prompt(q, y)
    assert "2024_Q1" in res
    assert "2023_FY" in res
    assert "Quarterly Financial Summary Table" in res
    assert "Annual Financial Summary Table" in res


@patch("src.agents.analyzer_agents.self_healing_analyzer.run_agent_loop")
def test_self_healing_analyzer_agent_tools(mock_run_loop, temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)
    state.metadata = CompanyMetadata(ticker=ticker)

    # Setup report with an anomalous line item (e.g. Total Assets flagged as raw operating line item instead of calculated)
    report = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q1",
        is_quarterly=True,
        balance_sheet_status="completed",
        income_statement_status="completed",
    )
    report.financial_data = ExtractedFinancialData(
        revenue=100.0,
        ebita=30.0,
        operating_income=25.0,
        line_items=[
            LineItem(
                line_name="Cash and Cash Equivalents",
                value=50.0,
                operating=True,
                calculated=False,
                category="current_assets",
            ),
            LineItem(
                line_name="Total Current Assets",
                value=500.0,
                operating=True,
                calculated=False,  # Anomaly: total current assets counted as raw item
                category="current_assets",
            ),
        ],
    )
    state.reports["2024_Q1"] = report
    save_workspace_state(ticker, state)

    client = MagicMock()

    # Capture tool functions passed to run_agent_loop
    captured_tools = {}

    def fake_run_agent_loop(
        client, system_prompt, initial_prompt, tools, max_turns, agent_name
    ):
        for tool in tools:
            captured_tools[tool.__name__] = tool
        # Simulate tool call to retrieve details and change line item classification
        retrieve_fn = captured_tools["retrieve_summary_table_details"]
        change_fn = captured_tools["change_line_item_classification"]
        finalize_fn = captured_tools["finalize"]

        details_json = retrieve_fn("2024_Q1")
        assert "Total Current Assets" in details_json

        change_res = change_fn(
            period_key="2024_Q1",
            line_name="Total Current Assets",
            operating=True,
            calculated=True,
        )
        assert "Successfully updated classification" in change_res

        _ = finalize_fn(
            anomalies_detected=["Total Current Assets calculated flag updated"],
            audit_summary="Fixed total current assets duplicate count.",
        )
        return {"audit_summary": "Fixed total current assets duplicate count."}, []

    mock_run_loop.side_effect = fake_run_agent_loop

    result = run_self_healing_analyzer_agent(client=client, ticker=ticker, max_turns=10)

    # Verify run_agent_loop was called with max_turns=10
    mock_run_loop.assert_called_once()
    assert mock_run_loop.call_args[1]["max_turns"] == 10
    assert result == {"audit_summary": "Fixed total current assets duplicate count."}

    # Verify line item classification was updated and persisted on blackboard
    updated_state = load_workspace_state(ticker)
    item = next(
        i
        for i in updated_state.reports["2024_Q1"].financial_data.line_items
        if i.line_name == "Total Current Assets"
    )
    assert item.calculated is True
