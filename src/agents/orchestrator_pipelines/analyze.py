import logging
from pathlib import Path
from typing import List

from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    HistoricalFinancialSummary,
    HistoricalAnalystView,
)
from src.agents.curator_agent import CuratorAgent
from src.agents.indexer_agent import IndexerAgent

logger = logging.getLogger(__name__)


def deduce_q4_financials(
    quarterly: List[HistoricalFinancialSummary],
    yearly: List[HistoricalFinancialSummary],
) -> List[HistoricalFinancialSummary]:
    """Deduce missing Q4 data from Annual figures (Annual minus Q1-Q3)."""
    # Group quarters by year
    quarters_by_year = {}
    for q in quarterly:
        quarters_by_year.setdefault(q.fiscal_year, {})[q.fiscal_period] = q

    # Sort annual chronologically to ensure prior years are deduced first
    annual_sorted = sorted(
        [y for y in yearly if y.fiscal_period == "FY"], key=lambda x: x.fiscal_year
    )

    deduced_entries = []

    for ann in annual_sorted:
        yr = ann.fiscal_year
        qtrs = quarters_by_year.get(yr, {})

        # Check if we have Q1, Q2, and Q3, but NOT Q4
        if "Q1" in qtrs and "Q2" in qtrs and "Q3" in qtrs and "Q4" not in qtrs:
            try:
                q1, q2, q3 = qtrs["Q1"], qtrs["Q2"], qtrs["Q3"]

                # Calculate Q4 values by subtraction
                q4_rev = ann.revenue - q1.revenue - q2.revenue - q3.revenue
                q4_op_inc = (
                    ann.operating_income
                    - q1.operating_income
                    - q2.operating_income
                    - q3.operating_income
                )
                q4_ebita = ann.ebita - q1.ebita - q2.ebita - q3.ebita
                q4_rep_tax = (
                    ann.reported_tax_provision
                    - q1.reported_tax_provision
                    - q2.reported_tax_provision
                    - q3.reported_tax_provision
                )
                q4_adj_taxes = (
                    ann.adjusted_taxes
                    - q1.adjusted_taxes
                    - q2.adjusted_taxes
                    - q3.adjusted_taxes
                )
                q4_nopat = ann.nopat - q1.nopat - q2.nopat - q3.nopat

                # Point-in-time metrics copy from Annual
                q4_ic = ann.invested_capital
                q4_basic = ann.basic_shares
                q4_diluted = ann.diluted_shares
                q4_nwc = ann.net_working_capital
                q4_nltoa = ann.net_long_term_operating_assets
                q4_adj_tax_rate = ann.adjusted_tax_rate

                # Derived rates
                q4_margin = (q4_ebita / q4_rev) if q4_rev > 0 else 0.0
                q4_turnover = (q4_rev * 4.0 / q4_ic) if q4_ic != 0.0 else 0.0
                q4_roic = (q4_nopat * 4.0 / q4_ic * 100.0) if q4_ic != 0.0 else 0.0

                # Growth calculations
                q4_simple_growth = 0.0
                q4_organic_growth = 0.0

                prior_yr = yr - 1
                prior_qtrs = quarters_by_year.get(prior_yr, {})
                prior_ann = next(
                    (
                        y
                        for y in yearly
                        if y.fiscal_year == prior_yr and y.fiscal_period == "FY"
                    ),
                    None,
                )

                if (
                    prior_ann
                    and "Q1" in prior_qtrs
                    and "Q2" in prior_qtrs
                    and "Q3" in prior_qtrs
                    and "Q4" in prior_qtrs
                ):
                    r1_prior = prior_qtrs["Q1"].revenue
                    r2_prior = prior_qtrs["Q2"].revenue
                    r3_prior = prior_qtrs["Q3"].revenue
                    ann_revenue_prior = prior_ann.revenue
                    r4_prior = ann_revenue_prior - r1_prior - r2_prior - r3_prior

                    if r4_prior > 0:
                        q4_simple_growth = (q4_rev - r4_prior) / r4_prior

                        ann_org_growth = ann.organic_growth
                        q1_org_growth = q1.organic_growth
                        q2_org_growth = q2.organic_growth
                        q3_org_growth = q3.organic_growth

                        ann_org_increase = ann_revenue_prior * ann_org_growth
                        q1_org_increase = r1_prior * q1_org_growth
                        q2_org_increase = r2_prior * q2_org_growth
                        q3_org_increase = r3_prior * q3_org_growth

                        q4_org_increase = (
                            ann_org_increase
                            - q1_org_increase
                            - q2_org_increase
                            - q3_org_increase
                        )
                        q4_organic_growth = q4_org_increase / r4_prior
                else:
                    # Fallback using current year values
                    ann_rev = ann.revenue
                    r1 = q1.revenue
                    r2 = q2.revenue
                    r3 = q3.revenue

                    if q4_rev > 0:
                        ann_org_growth = ann.organic_growth
                        q1_org_growth = q1.organic_growth
                        q2_org_growth = q2.organic_growth
                        q3_org_growth = q3.organic_growth

                        ann_org_increase = ann_rev * ann_org_growth
                        q1_org_increase = r1 * q1_org_growth
                        q2_org_increase = r2 * q2_org_growth
                        q3_org_increase = r3 * q3_org_growth

                        q4_org_increase = (
                            ann_org_increase
                            - q1_org_increase
                            - q2_org_increase
                            - q3_org_increase
                        )
                        q4_organic_growth = q4_org_increase / q4_rev

                        ann_simple_growth = ann.simple_growth
                        q1_simple_growth = q1.simple_growth
                        q2_simple_growth = q2.simple_growth
                        q3_simple_growth = q3.simple_growth

                        ann_simple_increase = ann_rev * ann_simple_growth
                        q1_simple_increase = r1 * q1_simple_growth
                        q2_simple_increase = r2 * q2_simple_growth
                        q3_simple_increase = r3 * q3_simple_growth

                        q4_simple_increase = (
                            ann_simple_increase
                            - q1_simple_increase
                            - q2_simple_increase
                            - q3_simple_increase
                        )
                        q4_simple_growth = q4_simple_increase / q4_rev

                q4_margin = round(q4_margin, 4)
                q4_turnover = round(q4_turnover, 4)
                q4_roic = round(q4_roic, 4)
                q4_simple_growth = round(q4_simple_growth, 4)
                q4_organic_growth = round(q4_organic_growth, 4)

                q4_summary = HistoricalFinancialSummary(
                    fiscal_year=yr,
                    fiscal_period="Q4",
                    revenue=q4_rev,
                    operating_income=q4_op_inc,
                    ebita=q4_ebita,
                    reported_tax_provision=q4_rep_tax,
                    adjusted_taxes=q4_adj_taxes,
                    adjusted_tax_rate=q4_adj_tax_rate,
                    basic_shares=q4_basic,
                    diluted_shares=q4_diluted,
                    simple_growth=q4_simple_growth,
                    organic_growth=q4_organic_growth,
                    net_working_capital=q4_nwc,
                    net_long_term_operating_assets=q4_nltoa,
                    invested_capital=q4_ic,
                    capital_turnover=q4_turnover,
                    nopat=q4_nopat,
                    roic=q4_roic,
                )
                deduced_entries.append(q4_summary)
                quarters_by_year.setdefault(yr, {})["Q4"] = q4_summary
                logger.info(f"Deduced Q4 financials for FY {yr} successfully.")
            except Exception as e:
                logger.warning(f"Failed to deduce Q4 financials for FY {yr}: {e}")

    return deduced_entries


def write_analyst_views(path: Path, views: List[HistoricalAnalystView]) -> None:
    lines = [
        "# Analyst Views History\n",
        "| Date | Document | Analyst Company | Economic Moat | Moat Rationale | Margin Outlook | Margin Magnitude | Margin Rationale | Growth Outlook | Growth Magnitude | Growth Rationale |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for v in views:
        lines.append(
            f"| {v.report_date} | [{v.source_file}](../4_extracted_data/{v.source_file}) | Unknown | "
            f"{v.economic_moat} | {v.economic_moat_rationale} | {v.margin_outlook} | {v.margin_magnitude} | {v.margin_rationale} | "
            f"{v.growth_outlook} | {v.growth_magnitude} | {v.growth_rationale} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_news_trend(path: Path, entries: list) -> None:
    lines = [
        "# News and Press Trends\n",
        "| Date | Document | Summary |",
        "|---|---|---|",
    ]
    for e in entries:
        summary_clean = e["summary"].replace("\n", " ")
        lines.append(
            f"| {e['date']} | [{e['document']}](../4_extracted_data/{e['document']}) | {summary_clean} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_transcript_trend(path: Path, entries: list) -> None:
    lines = [
        "# Conference Call Transcript Trends\n",
        "| Date | Document | Key Themes & Summaries |",
        "|---|---|---|",
    ]
    for e in entries:
        summary_clean = e["summary"].replace("\n", " ")
        lines.append(
            f"| {e['date']} | [{e['document']}](../4_extracted_data/{e['document']}) | {summary_clean} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_financials(
    path: Path,
    entries: List[HistoricalFinancialSummary],
    is_quarterly: bool,
    currency: str = "USD",
    unit: str = "Millions",
) -> None:
    entries_sorted = sorted(
        entries,
        key=lambda x: (
            x.fiscal_year,
            {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}.get(x.fiscal_period, 0),
        ),
    )

    lines = [
        f"# Historical Financials - {'Quarterly' if is_quarterly else 'Annual'}\n",
        f"**Currency**: {currency}",
        f"**Unit**: {unit}\n",
        "| Time Period | Period End | Revenue | EBITA | EBITA Margin | Adj Tax Rate | NOPAT | Invested Capital | Capital Turnover | ROIC | Organic Growth | Source Document |",
        "|-------------|-----------|---------|-------|--------------|-------------|-------|-----------------|------------------|------|----------------|-----------------|",
    ]
    for e in entries_sorted:
        margin = (e.ebita / e.revenue * 100.0) if e.revenue > 0 else 0.0
        tax_rate_pct = e.adjusted_tax_rate * 100.0
        org_growth_pct = (
            e.organic_growth * 100.0 if e.organic_growth is not None else 0.0
        )
        roic_pct = e.roic

        period_str = (
            f"{e.fiscal_year}-Q{e.fiscal_period.replace('Q', '')}"
            if is_quarterly
            else f"{e.fiscal_year}"
        )
        source_doc = "Blackboard State"
        if e.fiscal_period == "Q4":
            source_doc = "Deducted"
        doc_link = source_doc

        lines.append(
            f"| {period_str} | N/A | {e.revenue:,.1f} | {e.ebita:,.1f} | "
            f"{margin:.2f}% | {tax_rate_pct:.2f}% | {e.nopat:,.2f} | "
            f"{e.invested_capital:,.1f} | {e.capital_turnover:.2f}x | {roic_pct:.2f}% | "
            f"{org_growth_pct:.2f}% | {doc_link} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def orchestrate_analyze(orchestrator, ticker: str) -> None:
    orchestrator.checkout_status(ticker, "analyzer")
    try:
        state = load_workspace_state(ticker)
        workspace = Path(orchestrator.settings.active_workspace_path)
        analysis_dir = workspace / "5_historical_analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        doc_meta = {}
        for doc in state.raw_documents:
            doc_meta[doc.file_name] = {
                "type": doc.document_type,
                "date": doc.document_date or "N/A",
            }

        quarterly_financials_list = []
        yearly_financials_list = []
        historical_analyst_views_list = []
        news_entries = []
        transcript_entries = []

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

            # Qualitative others (press release, transcript, etc.)
            for other in report.other_data.others:
                meta = doc_meta.get(other.source_file, {})
                dtype = meta.get("type")
                ddate = meta.get("date", "N/A")

                entry = {
                    "date": ddate,
                    "document": other.source_file,
                    "summary": other.summary,
                }
                if dtype == "transcript":
                    transcript_entries.append(entry)
                elif dtype in ("press_release", "news_article", "other"):
                    news_entries.append(entry)

        # Deduce missing Q4 financials
        deduced_q4 = deduce_q4_financials(
            quarterly_financials_list, yearly_financials_list
        )
        quarterly_financials_list.extend(deduced_q4)

        # Sort lists
        quarterly_financials_list.sort(
            key=lambda x: (
                x.fiscal_year,
                {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}.get(x.fiscal_period, 0),
            )
        )
        yearly_financials_list.sort(key=lambda x: x.fiscal_year)

        state.company_data.quarterly_financials = quarterly_financials_list
        state.company_data.yearly_financials = yearly_financials_list
        state.company_data.historical_analyst_views = historical_analyst_views_list

        # Save output files to disk for human and tool usage
        write_analyst_views(
            analysis_dir / "analyst_views.md", historical_analyst_views_list
        )
        write_news_trend(analysis_dir / "news_trend.md", news_entries)
        write_transcript_trend(analysis_dir / "transcript_trend.md", transcript_entries)
        write_financials(
            analysis_dir / "financials_quarter.md",
            quarterly_financials_list,
            is_quarterly=True,
            currency=state.metadata.reporting_currency,
            unit=state.metadata.preferred_unit,
        )
        write_financials(
            analysis_dir / "financials_annual.md",
            yearly_financials_list,
            is_quarterly=False,
            currency=state.metadata.reporting_currency,
            unit=state.metadata.preferred_unit,
        )

        save_workspace_state(ticker, state)
        orchestrator.checkin_status(ticker, "analyzer", "completed")

        # Curate learnings
        CuratorAgent(orchestrator.settings).curate(
            ticker, "analyze", "Analyzed and synthesized trends."
        )

        # Run Indexing
        try:
            IndexerAgent(orchestrator.settings).run_indexing(ticker)
        except Exception as idx_err:
            logger.error(f"IndexerAgent failed after analysis: {idx_err}")

    except Exception as e:
        logger.error(f"Analysis orchestration failed: {e}")
        orchestrator.checkin_status(ticker, "analyzer", "failed")
