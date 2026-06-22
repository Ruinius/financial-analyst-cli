import typer
from rich.console import Console
from rich.markdown import Markdown
from typing import List, Optional

from src.core.blackboard import (
    load_workspace_state,
    HistoricalFinancialSummary,
    HistoricalAnalystView,
    BaseFinancialModel,
)
from src.utils import formatting

app = typer.Typer()
console = Console()


def format_financials_table(financials: List[HistoricalFinancialSummary]) -> str:
    if not financials:
        return "No financial data available."

    header = (
        "| Period | Revenue | Operating Income | EBITA | Adj. Tax Rate | Diluted Shares | Simple Growth | Organic Growth | Invested Capital | ROIC |\n"
        "|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    )

    rows = []
    # Sort financials by year, then period
    period_order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}
    sorted_financials = sorted(
        financials, key=lambda x: (x.fiscal_year, period_order.get(x.fiscal_period, 0))
    )

    for f in sorted_financials:
        period_str = f"{f.fiscal_year}_{f.fiscal_period}"
        tax_rate_str = (
            f"{f.adjusted_tax_rate * 100:.1f}%"
            if f.adjusted_tax_rate is not None
            else "N/A"
        )
        simple_growth_str = (
            f"{f.simple_growth * 100:.1f}%" if f.simple_growth is not None else "N/A"
        )
        organic_growth_str = (
            f"{f.organic_growth * 100:.1f}%" if f.organic_growth is not None else "N/A"
        )
        roic_str = f"{f.roic * 100:.1f}%" if f.roic is not None else "N/A"

        row = (
            f"| {period_str} | ${f.revenue:,.2f} | ${f.operating_income:,.2f} | ${f.ebita:,.2f} | "
            f"{tax_rate_str} | {f.diluted_shares:,.2f} | {simple_growth_str} | {organic_growth_str} | "
            f"${f.invested_capital:,.2f} | {roic_str} |"
        )
        rows.append(row)

    return header + "\n".join(rows)


def format_analyst_views(views: List[HistoricalAnalystView]) -> str:
    if not views:
        return "No qualitative analyst views available."

    sections = []
    for v in views:
        section = (
            f"### Analyst View from {v.report_date} (Source: {v.source_file})\n\n"
            f"**Economic Moat**: {v.economic_moat}\n"
            f"- *Rationale*: {v.economic_moat_rationale}\n\n"
            f"**Margin Outlook**: {v.margin_outlook} ({v.margin_magnitude})\n"
            f"- *Rationale*: {v.margin_rationale}\n\n"
            f"**Growth Outlook**: {v.growth_outlook} ({v.growth_magnitude})\n"
            f"- *Rationale*: {v.growth_rationale}\n"
        )
        sections.append(section)
    return "\n---\n\n".join(sections)


def format_valuation_model(model: BaseFinancialModel, period_str: str) -> str:
    assumptions = model.assumptions
    projections = model.projections

    md = (
        f"# Valuation Report ({period_str}) - Run Date: {model.dcf_run_date}\n\n"
        f"## Intrinsic Value Outputs\n"
        f"- **Calculated Intrinsic Value per Share**: ${model.calculated_intrinsic_value_per_share:,.2f}\n"
        f"- **Calculated Equity Value**: ${model.calculated_equity_value:,.2f}\n"
        f"- **Calculated Enterprise Value**: ${model.calculated_enterprise_value:,.2f}\n"
        f"- **Upside / Downside**: {model.upside_downside_percentage}\n\n"
        f"## Model Assumptions\n"
        f"### WACC & Capital Structure\n"
        f"- **Weighted Average Cost of Capital (WACC)**: {assumptions.wacc * 100:.2f}%\n"
        f"- **Cost of Equity**: {assumptions.cost_of_equity * 100:.2f}%\n"
        f"- **Pre-tax Cost of Debt**: {assumptions.pretax_cost_of_debt * 100:.2f}%\n"
        f"- **Weight of Equity / Debt**: {assumptions.weight_equity * 100:.1f}% / {assumptions.weight_debt * 100:.1f}%\n"
        f"- **Target Debt/Equity**: {assumptions.target_debt_to_equity:,.2f}\n"
        f"- **Levered / Unlevered Beta**: {assumptions.company_beta_levered:.2f} / {assumptions.company_beta_unlevered:.2f}\n"
        f"- **Risk-free Rate / Equity Risk Premium**: {assumptions.risk_free_rate * 100:.2f}% / {assumptions.equity_risk_premium * 100:.2f}%\n"
        f"- **Shares Outstanding**: {assumptions.shares_outstanding:,.2f} million\n"
        f"- **Current Share Price**: ${assumptions.share_price:,.2f}\n"
        f"- **Market Cap**: ${assumptions.market_cap:,.2f} million\n\n"
        f"### Revenue & EBITA Growth\n"
        f"- **Base Revenue**: ${assumptions.base_revenue:,.2f} million\n"
        f"- **Base Invested Capital**: ${assumptions.base_invested_capital:,.2f} million\n"
        f"- **Revenue Growth (Base / Year 5)**: {assumptions.revenue_growth_base * 100:.2f}% / {assumptions.revenue_growth_yr5 * 100:.2f}%\n"
        f"- **EBITA Margin (Base / Year 5)**: {assumptions.ebita_margin_base * 100:.2f}% / {assumptions.ebita_margin_yr5 * 100:.2f}%\n"
        f"- **Terminal Growth Rate**: {assumptions.terminal_growth_rate * 100:.2f}%\n"
        f"- **Terminal Margin**: {assumptions.terminal_margin * 100:.2f}%\n"
        f"- **Adjusted Tax Rate**: {assumptions.adjusted_tax_rate * 100:.2f}%\n"
        f"- **Capital Turnover**: {assumptions.capital_turnover:.2f}x\n\n"
        f"### Balance Sheet Adjustments / Bridge\n"
        f"- **Excess Cash**: ${assumptions.excess_cash:,.2f} million\n"
        f"- **Short Term Investments**: ${assumptions.short_term_investments:,.2f} million\n"
        f"- **Debt**: ${assumptions.debt:,.2f} million\n"
        f"- **Preferred Equity / Minority Interest**: ${assumptions.preferred_equity:,.2f} / ${assumptions.minority_interest:,.2f} million\n"
        f"- **Other Financial Assets (Net)**: ${assumptions.other_financial_assets_net:,.2f} million\n"
        f"- **Net Debt**: ${assumptions.net_debt:,.2f} million\n\n"
        f"## 10-Year Projections\n"
        f"| Year | Revenue | Growth | EBITA | Margin | NOPAT | Reinvestment | Invested Capital | ROIC | FCF | PV of FCF |\n"
        f"|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    )

    for p in projections:
        md += (
            f"| {p.year} | ${p.revenue:,.1f} | {p.growth * 100:.1f}% | ${p.ebita:,.1f} | {p.margin * 100:.1f}% | "
            f"${p.nopat:,.1f} | ${p.reinvestment:,.1f} | ${p.invested_capital:,.1f} | {p.roic * 100:.1f}% | "
            f"${p.fcf:,.1f} | ${p.present_value:,.1f} |\n"
        )

    return md


@app.command("summary")
def query_summary(ticker: str = typer.Argument(..., help="Company ticker symbol")):
    """Display historical metric tables."""
    try:
        state = load_workspace_state(ticker)
    except Exception as e:
        formatting.print_error(f"Failed to load state: {str(e)}")
        return

    formatting.speak(
        f"Here is a summary of historical financial tables for {ticker}, my dear fellow:"
    )

    console.print("[bold cyan]Annual Financials:[/bold cyan]")
    annual_table = format_financials_table(state.company_data.yearly_financials)
    console.print(Markdown(annual_table))
    console.print()

    console.print("[bold cyan]Quarterly Financials:[/bold cyan]")
    quarterly_table = format_financials_table(state.company_data.quarterly_financials)
    console.print(Markdown(quarterly_table))


@app.command("assessment")
def query_assessment(ticker: str = typer.Argument(..., help="Company ticker symbol")):
    """Display qualitative moat and margin assessments."""
    try:
        state = load_workspace_state(ticker)
    except Exception as e:
        formatting.print_error(f"Failed to load state: {str(e)}")
        return

    formatting.speak(
        f"Here is the qualitative moat and margin assessment report for {ticker}:"
    )
    views_md = format_analyst_views(state.company_data.historical_analyst_views)
    console.print(Markdown(views_md))


@app.command("valuation")
def query_valuation(ticker: str = typer.Argument(..., help="Company ticker symbol")):
    """Display WACC metrics and intrinsic value models."""
    try:
        state = load_workspace_state(ticker)
    except Exception as e:
        formatting.print_error(f"Failed to load state: {str(e)}")
        return

    completed_reports = [
        (period, r) for period, r in state.reports.items() if r.base_model is not None
    ]

    if not completed_reports:
        formatting.print_warning(
            f"No valuation models found in workspace state for {ticker}"
        )
        return

    # Sort reports by year and quarter/FY
    period_order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}
    latest_period, latest_report = max(
        completed_reports,
        key=lambda x: (x[1].fiscal_year, period_order.get(x[1].fiscal_period, 0)),
    )

    formatting.speak(
        f"Behold the cost of capital and DCF intrinsic valuation models for {ticker}:"
    )
    val_md = format_valuation_model(latest_report.base_model, latest_period)
    console.print(Markdown(val_md))


@app.command("trace")
def query_trace(
    ticker: str = typer.Argument(..., help="Company ticker symbol"),
    metric: Optional[str] = typer.Option(
        None, "--metric", "-m", help="Metric name to trace (e.g. 'Revenue')"
    ),
    period: Optional[str] = typer.Option(
        None, "--period", "-p", help="Period to trace (e.g. '2024_Q3')"
    ),
):
    """Retrieve full pipeline trace, document status, and arithmetic error logs."""
    try:
        state = load_workspace_state(ticker)
    except Exception as e:
        formatting.print_error(f"Failed to load state: {str(e)}")
        return

    formatting.speak(f"Here is the execution trace and lineage analysis for {ticker}:")

    # 1. Raw Document Statuses
    if not metric:
        console.print("[bold cyan]Raw Document Ingestion Status:[/bold cyan]")
        if not state.raw_documents:
            console.print("No raw documents registered.")
        for doc in state.raw_documents:
            status_color = (
                "green"
                if doc.ingestion_status == "completed"
                else "yellow"
                if doc.ingestion_status == "running"
                else "red"
            )
            console.print(
                f"- {doc.file_name}: [{status_color}]{doc.ingestion_status}[/{status_color}]"
            )
        console.print()

        # 2. Stage Execution Statuses
        console.print("[bold cyan]Pipeline Stage Execution Statuses:[/bold cyan]")
        metadata_color = "green" if state.metadata_status == "completed" else "red"
        analyzer_color = "green" if state.analyzer_status == "completed" else "red"
        curator_color = "green" if state.curator_status == "completed" else "red"
        console.print(
            f"- Metadata Extraction: [{metadata_color}]{state.metadata_status}[/{metadata_color}]"
        )
        console.print(
            f"- Longitudinal Trends Analyzer: [{analyzer_color}]{state.analyzer_status}[/{analyzer_color}]"
        )
        console.print(
            f"- Curator Wiki compiler: [{curator_color}]{state.curator_status}[/{curator_color}]"
        )
        console.print()

    # 3. Period Report Statuses and Logs
    console.print("[bold cyan]Period Report Statuses & Audit Logs:[/bold cyan]")
    target_periods = [period] if period else list(state.reports.keys())

    if not target_periods:
        console.print("No period reports registered.")

    for p in sorted(target_periods):
        if p not in state.reports:
            console.print(
                f"[bold yellow]Period '{p}' not found in state.[/bold yellow]"
            )
            continue
        report = state.reports[p]
        console.print(f"[bold underline]Period: {p}[/bold underline]")
        console.print(
            f"  Source files: {', '.join(report.source_files) if report.source_files else 'None'}"
        )

        # Sub-agents statuses
        statuses = [
            f"Balance Sheet: {report.balance_sheet_status}",
            f"Income Statement: {report.income_statement_status}",
            f"Shares Outstanding: {report.shares_status}",
            f"Organic Growth: {report.organic_growth_status}",
            f"Operating EBITA: {report.ebita_status}",
            f"Adjusted Taxes: {report.tax_status}",
        ]
        console.print(f"  Extraction Sub-agents: {', '.join(statuses)}")

        # Modeling statuses
        model_statuses = [
            f"WACC: {report.wacc_agent_status}",
            f"Growth Assumptions: {report.growth_agent_status}",
            f"Margin Assumptions: {report.margin_agent_status}",
            f"Non-operating assets/bridge: {report.non_operating_agent_status}",
            f"DCF Valuation: {report.dcf_modeling_status}",
        ]
        console.print(f"  Modeling Sub-agents: {', '.join(model_statuses)}")

        # Arithmetic and Quality Logs
        if report.arithmetic_errors:
            console.print("  [bold red]Arithmetic / Quality Audit Errors:[/bold red]")
            for err in report.arithmetic_errors:
                console.print(f"    - {err}")
        else:
            console.print(
                "  [green]No arithmetic or validation errors reported.[/green]"
            )
        console.print()

    # 4. Metric Tracing
    if metric:
        console.print(f"[bold cyan]Lineage Trace for Metric: '{metric}'[/bold cyan]")
        found_any = False
        for p in sorted(state.reports.keys()):
            report = state.reports[p]
            # Check basic fields
            fd = report.financial_data
            for key, val in fd.model_dump().items():
                if metric.lower() in key.lower() and isinstance(val, (int, float)):
                    console.print(
                        f"- Period {p}: [bold]{key}[/bold] = {val:,.2f} (Extracted Core Field)"
                    )
                    found_any = True

            # Check individual line items
            for item in fd.line_items:
                if metric.lower() in item.line_name.lower():
                    calc_type = "Calculated" if item.calculated else "Direct Extraction"
                    op_type = "Operating" if item.operating else "Non-operating"
                    console.print(
                        f"- Period {p}: [bold]{item.line_name}[/bold] = {item.value:,.2f} "
                        f"({item.category} | {calc_type} | {op_type})"
                    )
                    found_any = True
        if not found_any:
            console.print(
                f"[yellow]No line items matching '{metric}' found in any period.[/yellow]"
            )
