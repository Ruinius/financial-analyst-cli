import json
import logging
from typing import List, Optional, Dict, Any

from src.services.llm_client import LLMClient
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    HistoricalFinancialSummary,
)
from src.agents.agent_executor import run_agent_loop

logger = logging.getLogger(__name__)


def format_summary_tables_for_prompt(
    quarterly: List[HistoricalFinancialSummary],
    yearly: List[HistoricalFinancialSummary],
) -> str:
    """Format quarterly and yearly financial summaries into clean Markdown tables for LLM inspection."""
    lines = []

    lines.append("### Quarterly Financial Summary Table")
    if quarterly:
        lines.append(
            "| Period | Revenue | Op Income | EBITA | Invested Capital | NWC | NLTOA | NOPAT | ROIC (%) | Cap Turnover |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for q in quarterly:
            period_str = f"{q.fiscal_year}_{q.fiscal_period}"
            lines.append(
                f"| {period_str} | {q.revenue:,.2f} | {q.operating_income:,.2f} | {q.ebita:,.2f} | "
                f"{q.invested_capital:,.2f} | {q.net_working_capital:,.2f} | {q.net_long_term_operating_assets:,.2f} | "
                f"{q.nopat:,.2f} | {q.roic:.2f}% | {q.capital_turnover:.2f} |"
            )
    else:
        lines.append("No quarterly summaries available.")

    lines.append("\n### Annual Financial Summary Table")
    if yearly:
        lines.append(
            "| Period | Revenue | Op Income | EBITA | Invested Capital | NWC | NLTOA | NOPAT | ROIC (%) | Cap Turnover |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for y in yearly:
            period_str = f"{y.fiscal_year}_{y.fiscal_period}"
            lines.append(
                f"| {period_str} | {y.revenue:,.2f} | {y.operating_income:,.2f} | {y.ebita:,.2f} | "
                f"{y.invested_capital:,.2f} | {y.net_working_capital:,.2f} | {y.net_long_term_operating_assets:,.2f} | "
                f"{y.nopat:,.2f} | {y.roic:.2f}% | {y.capital_turnover:.2f} |"
            )
    else:
        lines.append("No annual summaries available.")

    return "\n".join(lines)


def detect_summary_table_anomalies(
    quarterly: List[HistoricalFinancialSummary],
    yearly: List[HistoricalFinancialSummary],
    reports: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Detect statistical metric jumps/spikes and cross-period line item classification inconsistencies."""
    anomalies = []
    all_summaries = quarterly + yearly
    if not all_summaries:
        return anomalies

    # 1. Collect positive Invested Capital values and check for statistical spikes/drops
    ic_vals = [
        abs(s.invested_capital) for s in all_summaries if s.invested_capital != 0.0
    ]
    if ic_vals:
        sorted_ic = sorted(ic_vals)
        median_ic = sorted_ic[len(sorted_ic) // 2]
        if median_ic > 0:
            for s in all_summaries:
                ratio = s.invested_capital / median_ic
                if ratio >= 3.0:
                    anomalies.append(
                        f"METRIC SPIKE: Period '{s.fiscal_year}_{s.fiscal_period}' has Invested Capital = {s.invested_capital:,.2f}, "
                        f"which is {ratio:.1f}x higher than the median Invested Capital ({median_ic:,.2f}). "
                        f"Check if 'Goodwill', 'Acquired Intangible Assets', 'Long-term Deferred Tax Assets', or subtotal lines are misclassified!"
                    )
                elif ratio <= -3.0 or (s.invested_capital < 0 and median_ic > 0):
                    anomalies.append(
                        f"METRIC DISTORTION: Period '{s.fiscal_year}_{s.fiscal_period}' has negative/distorted Invested Capital = {s.invested_capital:,.2f} "
                        f"vs median {median_ic:,.2f}."
                    )

    # 2. Check cross-period line item classification inconsistencies
    if reports:
        item_operating_map = {}
        for p_key, report in reports.items():
            fd = getattr(report, "financial_data", None)
            if not fd or not fd.line_items:
                continue
            for item in fd.line_items:
                norm_name = item.line_name.strip().lower()
                if any(
                    k in norm_name
                    for k in [
                        "goodwill",
                        "intangible",
                        "right-of-use",
                        "deferred income tax",
                    ]
                ):
                    item_operating_map.setdefault(item.line_name, {})[p_key] = (
                        item.operating
                    )

        for name, p_map in item_operating_map.items():
            true_periods = [p for p, op in p_map.items() if op is True]
            false_periods = [p for p, op in p_map.items() if op is False]
            if true_periods and false_periods:
                anomalies.append(
                    f"CLASSIFICATION INCONSISTENCY: Line item '{name}' is marked operating=True in {true_periods} "
                    f"but operating=False in {false_periods}. Ensure line item classifications are consistent across ALL periods!"
                )

    return anomalies


def _normalize_period_key(period_key: str, available_keys: List[str]) -> Optional[str]:
    """Resolve user/LLM period key input (e.g. '2024_Q1', '2024-Q1', '2024 Q1', '2024_FY') to exact key in reports dict."""
    if period_key in available_keys:
        return period_key

    cleaned = period_key.strip().replace("-", "_").replace(" ", "_")
    if cleaned in available_keys:
        return cleaned

    for k in available_keys:
        if cleaned.lower() == k.lower():
            return k

    return None


def run_self_healing_analyzer_agent(
    client: LLMClient,
    ticker: str,
    max_turns: int = 10,
) -> Dict[str, Any]:
    """
    Self-healing AI agent that inspects quarterly and annual summary tables across time periods
    to identify financial calculation anomalies, unexpected metric jumps (e.g. 10x invested capital jump),
    or misclassified line items.

    Allows retrieving detailed line items for suspect period summary tables and changing
    line item classification (operating vs non-operating, calculated vs non-calculated).
    Enforces a strict 10-turn limit.
    """
    import src.utils.formatting as formatting

    formatting.print_info("Starting sub-agent: SelfHealingAnalyzerAgent...")

    state = load_workspace_state(ticker)
    quarterly = state.company_data.quarterly_financials
    yearly = state.company_data.yearly_financials

    summary_tables_md = format_summary_tables_for_prompt(quarterly, yearly)

    detected_anomalies = detect_summary_table_anomalies(
        quarterly, yearly, reports=state.reports
    )
    anomaly_section = ""
    if detected_anomalies:
        anomaly_section = (
            "\n\nProgrammatically Detected Metric Spikes/Anomalies:\n"
            + "\n".join(f"- {a}" for a in detected_anomalies)
        )

    system_prompt = (
        "You are Sir Pennyworth, a senior quantitative auditor acting as the Self-Healing Financial Analyzer Agent.\n"
        "Your primary objective is to inspect financial summary tables across consecutive time periods (quarters and years) "
        "to detect calculation anomalies, inconsistent trends, unexpected spikes/drops (e.g., a 10x jump in invested capital, "
        "sudden sign flips, or unnatural margins/ROIC), and line item classification errors.\n\n"
        "Rules:\n"
        "1. Inspect the provided quarterly and annual summary tables carefully.\n"
        "2. If an anomaly or spike in Invested Capital or NLTOA is reported (e.g., 2025_Q2 or 2026_Q1), call `retrieve_summary_table_details` for that period "
        "and compare line item classification flags (operating vs non-operating, calculated vs non-calculated) with normal neighboring periods.\n"
        "3. Rule for Goodwill & Intangibles: Goodwill and Acquired Intangible Assets are NON-OPERATING assets (operating=False) for ALL periods.\n"
        "4. Call `change_line_item_classification` to update any misclassified line items (e.g., set operating=False for 'Goodwill' or 'Acquired Intangible Assets', or calculated=True for subtotals).\n"
        "5. When your analysis and fixes are complete, call `finalize` with a summary of findings.\n"
        "6. You have a maximum limit of 10 turns."
    )

    initial_prompt = (
        f"Starting self-healing financial analysis for ticker '{ticker}'.\n\n"
        f"Deterministic Financial Summary Tables:\n{summary_tables_md}"
        f"{anomaly_section}\n\n"
        "Please inspect the summary tables across time periods for anomalies or strange jumps. "
        "Retrieve details for suspect periods and adjust line item classifications if needed."
    )

    def retrieve_summary_table_details(period_key: str) -> str:
        """Retrieve full details for a summary table period, including line items, raw tables, and current metrics.

        Args:
            period_key: The period identifier (e.g. '2024_Q1', '2023_FY').
        """
        cur_state = load_workspace_state(ticker)
        matched_key = _normalize_period_key(period_key, list(cur_state.reports.keys()))

        if not matched_key or matched_key not in cur_state.reports:
            return f"Period '{period_key}' not found in workspace reports. Available periods: {list(cur_state.reports.keys())}"

        report = cur_state.reports[matched_key]
        fd = report.financial_data

        items_list = []
        for item in fd.line_items:
            items_list.append(
                {
                    "line_name": item.line_name,
                    "value": item.value,
                    "category": item.category,
                    "operating": item.operating,
                    "calculated": item.calculated,
                }
            )

        details = {
            "period_key": matched_key,
            "fiscal_year": report.fiscal_year,
            "fiscal_period": report.fiscal_period,
            "metrics": {
                "revenue": fd.revenue,
                "operating_income": fd.operating_income,
                "ebita": fd.ebita,
                "net_working_capital": fd.net_working_capital,
                "net_long_term_operating_assets": fd.net_long_term_operating_assets,
                "invested_capital": fd.invested_capital,
                "capital_turnover": fd.capital_turnover,
                "nopat": fd.nopat,
                "roic": fd.roic,
            },
            "line_items_count": len(items_list),
            "line_items": items_list,
            "raw_income_statement_preview": (
                fd.raw_income_statement_markdown[:500] + "..."
                if fd.raw_income_statement_markdown
                else None
            ),
            "raw_balance_sheet_preview": (
                fd.raw_balance_sheet_markdown[:500] + "..."
                if fd.raw_balance_sheet_markdown
                else None
            ),
            "arithmetic_errors": report.arithmetic_errors,
        }
        return json.dumps(details, indent=2)

    def change_line_item_classification(
        period_key: str,
        line_name: str,
        operating: Optional[bool] = None,
        calculated: Optional[bool] = None,
    ) -> str:
        """Change classification flags (operating vs non-operating, calculated vs non-calculated) for line items.

        Args:
            period_key: The period identifier (e.g. '2024_Q1', '2023_FY').
            line_name: Name of line item to modify (case-insensitive substring match or exact match).
            operating: Optional boolean flag to set line item as operating (True) or non-operating (False).
            calculated: Optional boolean flag to set line item as calculated total/subtotal (True) or raw line (False).
        """
        cur_state = load_workspace_state(ticker)
        matched_key = _normalize_period_key(period_key, list(cur_state.reports.keys()))

        if not matched_key or matched_key not in cur_state.reports:
            return f"Period '{period_key}' not found in workspace reports."

        if operating is None and calculated is None:
            return "No classification changes specified. Please provide 'operating' or 'calculated' boolean values."

        report = cur_state.reports[matched_key]
        modified_items = []

        target_name_lower = line_name.strip().lower()
        for item in report.financial_data.line_items:
            item_name_lower = item.line_name.strip().lower()
            if (
                target_name_lower == item_name_lower
                or target_name_lower in item_name_lower
            ):
                if operating is not None:
                    item.operating = bool(operating)
                if calculated is not None:
                    item.calculated = bool(calculated)
                modified_items.append(
                    {
                        "line_name": item.line_name,
                        "operating": item.operating,
                        "calculated": item.calculated,
                    }
                )

        if not modified_items:
            return (
                f"No line item matching '{line_name}' found in period '{matched_key}'."
            )

        save_workspace_state(ticker, cur_state)
        return (
            f"Successfully updated classification for {len(modified_items)} line item(s) in period '{matched_key}':\n"
            f"{json.dumps(modified_items, indent=2)}"
        )

    def finalize(
        anomalies_detected: Optional[list] = None,
        audit_summary: Optional[str] = None,
    ) -> str:
        """Finalize the self-healing analysis.

        Args:
            anomalies_detected: List of anomalies or strange jumps identified and audited.
            audit_summary: Overall narrative summary of audit findings and classification adjustments.
        """
        return "Self-healing analyzer execution finalized."

    tools = [retrieve_summary_table_details, change_line_item_classification, finalize]

    finalized_args = {}
    try:
        finalized_args, history = run_agent_loop(
            client=client,
            system_prompt=system_prompt,
            initial_prompt=initial_prompt,
            tools=tools,
            max_turns=max_turns,
            agent_name="self_healing_analyzer",
        )
    except Exception as e:
        logger.warning(
            f"Self-healing analyzer agent completed loop with message/exception: {e}"
        )

    formatting.print_success("Sub-agent completed: SelfHealingAnalyzerAgent")
    return finalized_args or {}
