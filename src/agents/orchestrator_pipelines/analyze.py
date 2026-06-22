import logging
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    HistoricalFinancialSummary,
    HistoricalAnalystView,
)
from src.agents.curator_agent import CuratorAgent

logger = logging.getLogger(__name__)


async def orchestrate_analyze(orchestrator, ticker: str) -> None:
    orchestrator.checkout_status(ticker, "analyzer")
    try:
        state = load_workspace_state(ticker)

        quarterly_financials_list = []
        yearly_financials_list = []
        historical_analyst_views_list = []

        for period_key, report in state.reports.items():
            if (
                report.balance_sheet_status != "completed"
                or report.income_statement_status != "completed"
            ):
                continue

            fy = report.fiscal_year
            fp = report.fiscal_period

            # Create summary record
            summary = HistoricalFinancialSummary(
                fiscal_year=fy,
                fiscal_period=fp,
                revenue=report.financial_data.revenue,
                operating_income=report.financial_data.operating_income,
                ebita=report.financial_data.ebita,
                reported_tax_provision=report.financial_data.reported_tax_provision,
                adjusted_taxes=report.financial_data.adjusted_taxes,
                adjusted_tax_rate=report.financial_data.adjusted_tax_rate,
                basic_shares=report.financial_data.basic_shares,
                diluted_shares=report.financial_data.diluted_shares,
                simple_growth=report.financial_data.simple_growth,
                organic_growth=report.financial_data.organic_growth,
                net_working_capital=report.financial_data.net_working_capital,
                net_long_term_operating_assets=report.financial_data.net_long_term_operating_assets,
                invested_capital=report.financial_data.invested_capital,
                capital_turnover=report.financial_data.capital_turnover,
                nopat=report.financial_data.nopat,
                roic=report.financial_data.roic,
            )

            if report.is_quarterly:
                quarterly_financials_list.append(summary)
            else:
                yearly_financials_list.append(summary)

            # Analyst views
            for ar in report.other_data.analyst_reports:
                view = HistoricalAnalystView(
                    report_date=report.fiscal_period,  # Fallback to period
                    source_file=ar.source_file,
                    economic_moat=ar.economic_moat,
                    economic_moat_rationale=ar.economic_moat_rationale,
                    margin_outlook=ar.margin_outlook,
                    margin_magnitude=ar.margin_magnitude,
                    margin_rationale=ar.margin_rationale,
                    growth_outlook=ar.growth_outlook,
                    growth_magnitude=ar.growth_magnitude,
                    growth_rationale=ar.growth_rationale,
                )
                historical_analyst_views_list.append(view)

        # Sort lists
        quarterly_financials_list.sort(key=lambda x: (x.fiscal_year, x.fiscal_period))
        yearly_financials_list.sort(key=lambda x: x.fiscal_year)

        state.company_data.quarterly_financials = quarterly_financials_list
        state.company_data.yearly_financials = yearly_financials_list
        state.company_data.historical_analyst_views = historical_analyst_views_list

        save_workspace_state(ticker, state)
        orchestrator.checkin_status(ticker, "analyzer", "completed")

        # Curate learnings
        CuratorAgent(orchestrator.settings).curate(
            ticker, "analyze", "Analyzed and synthesized trends."
        )

    except Exception as e:
        logger.error(f"Analysis orchestration failed: {e}")
        orchestrator.checkin_status(ticker, "analyzer", "failed")
