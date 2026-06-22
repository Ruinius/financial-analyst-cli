import asyncio
import logging
from pathlib import Path
from typing import Optional

from src.core.exceptions import WorkspaceError
from src.core.blackboard import (
    load_workspace_state,
    DCFProjectionYear,
    ModelAssumptions,
    BaseFinancialModel,
)
from src.agents.modeler_orchestrator import Modeler
from src.agents.curator_agent import CuratorAgent

logger = logging.getLogger(__name__)


async def orchestrate_model(
    orchestrator,
    ticker: str,
    agent: Optional[str] = None,
    non_interactive: bool = False,
) -> None:
    import src.agents.blackboard_orchestrator as bo

    state = load_workspace_state(ticker)

    extract_agent_map = {
        "metadata": "metadata",
        "metadata_agent": "metadata",
        "balance_sheet": "balance_sheet",
        "balance_sheet_agent": "balance_sheet",
        "income_statement": "income_statement",
        "income_statement_agent": "income_statement",
        "shares": "shares",
        "shares_agent": "shares",
        "diluted_shares": "shares",
        "diluted_shares_agent": "shares",
        "organic_growth": "organic_growth",
        "organic_growth_agent": "organic_growth",
        "interpretation": "interpretation",
        "interpretation_agent": "interpretation",
        "ebita": "ebita",
        "ebita_agent": "ebita",
        "operating_ebita": "ebita",
        "operating_ebita_agent": "ebita",
        "tax": "tax",
        "tax_agent": "tax",
        "adjusted_taxes": "tax",
        "adjusted_taxes_agent": "tax",
        "analyst_report": "analyst_report",
        "analyst_report_agent": "analyst_report",
        "other": "other",
        "other_doc": "other",
        "other_doc_agent": "other",
    }

    model_agent_map = {
        "wacc": "wacc_agent",
        "wacc_agent": "wacc_agent",
        "growth": "growth_agent",
        "growth_agent": "growth_agent",
        "margin": "margin_agent",
        "margin_agent": "margin_agent",
        "non_operating": "non_operating_agent",
        "non_operating_agent": "non_operating_agent",
        "dcf": "dcf_modeling",
        "dcf_modeling": "dcf_modeling",
        "dcf_modeling_agent": "dcf_modeling",
    }

    normalized_agent = None
    if agent:
        agent_lower = agent.lower().strip()
        if agent_lower in model_agent_map:
            normalized_agent = model_agent_map[agent_lower]
        elif agent_lower in extract_agent_map:
            # Extraction agent, bypass this stage
            return
        else:
            raise WorkspaceError(f"Unknown agent: '{agent}'")

    # Verify global dependencies for model stage
    if normalized_agent:
        if state.metadata_status != "completed":
            raise WorkspaceError(
                "Missing dependency: Company metadata extraction must be completed first."
            )
        if not state.reports:
            raise WorkspaceError("No periods initialized on the blackboard.")

    if not state.reports:
        logger.warning("No reports found to execute modeling.")
        return

    # Find latest period key
    latest_period = sorted(list(state.reports.keys()))[-1]
    report = state.reports[latest_period]

    # Verify specific modeling dependencies
    if normalized_agent == "wacc_agent":
        if (
            report.balance_sheet_status != "completed"
            or report.income_statement_status != "completed"
        ):
            raise WorkspaceError(
                "Missing dependency: Balance sheet and income statement must be completed for the latest period before running WACC agent."
            )
    elif normalized_agent == "growth_agent":
        if state.analyzer_status != "completed":
            raise WorkspaceError(
                "Missing dependency: Trend analysis stage must be completed before running growth agent."
            )
    elif normalized_agent == "margin_agent":
        if state.analyzer_status != "completed":
            raise WorkspaceError(
                "Missing dependency: Trend analysis stage must be completed before running margin agent."
            )
    elif normalized_agent == "non_operating_agent":
        if report.balance_sheet_status != "completed":
            raise WorkspaceError(
                "Missing dependency: Balance sheet must be completed for the latest period before running non-operating agent."
            )
    elif normalized_agent == "dcf_modeling":
        if (
            report.wacc_agent_status != "completed"
            or report.growth_agent_status != "completed"
            or report.margin_agent_status != "completed"
            or report.non_operating_agent_status != "completed"
        ):
            raise WorkspaceError(
                "Missing dependency: All modeling assumptions (WACC, growth, margin, non-operating) must be completed before running DCF modeling agent."
            )

    learning_context = ""
    learnings_path = (
        Path(orchestrator.settings.active_workspace_path)
        / f"{ticker}_model_learning.md"
    )
    if learnings_path.exists():
        try:
            learning_context = learnings_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # Level 1 (Parallel): wacc_agent, growth_agent, margin_agent, non_operating_agent
    async def process_modeling_l1():
        tasks = []

        # A. WACC Agent
        if normalized_agent is None or normalized_agent == "wacc_agent":
            if (
                report.wacc_agent_status in ("pending", "failed")
                or normalized_agent == "wacc_agent"
            ):

                async def run_wacc():
                    async with orchestrator.phase_sem:
                        orchestrator.checkout_status(
                            ticker, "wacc_agent", period=latest_period
                        )
                        try:
                            wacc_res = await asyncio.to_thread(
                                bo.run_wacc_agent,
                                client=orchestrator.client,
                                company_metadata=state.metadata,
                                workspace_state=state,
                                period_key=latest_period,
                                learnings=learning_context,
                            )
                            orchestrator.checkin_status(
                                ticker,
                                "wacc_agent",
                                "completed",
                                period=latest_period,
                                payload=wacc_res,
                            )
                        except Exception as e:
                            logger.error(f"WACC Agent failed: {e}")
                            orchestrator.checkin_status(
                                ticker, "wacc_agent", "failed", period=latest_period
                            )
                            raise

                tasks.append(
                    orchestrator.wrap_task("wacc_agent", latest_period, None, run_wacc)
                )

        # B. Growth Agent
        if normalized_agent is None or normalized_agent == "growth_agent":
            if (
                report.growth_agent_status in ("pending", "failed")
                or normalized_agent == "growth_agent"
            ):

                async def run_growth():
                    async with orchestrator.phase_sem:
                        orchestrator.checkout_status(
                            ticker, "growth_agent", period=latest_period
                        )
                        try:
                            growth_res = await asyncio.to_thread(
                                bo.run_growth_agent,
                                client=orchestrator.client,
                                company_metadata=state.metadata,
                                workspace_state=state,
                                period_key=latest_period,
                                learnings=learning_context,
                            )
                            orchestrator.checkin_status(
                                ticker,
                                "growth_agent",
                                "completed",
                                period=latest_period,
                                payload=growth_res,
                            )
                        except Exception as e:
                            logger.error(f"Growth Agent failed: {e}")
                            orchestrator.checkin_status(
                                ticker,
                                "growth_agent",
                                "failed",
                                period=latest_period,
                            )
                            raise

                tasks.append(
                    orchestrator.wrap_task(
                        "growth_agent", latest_period, None, run_growth
                    )
                )

        # C. Margin Agent
        if normalized_agent is None or normalized_agent == "margin_agent":
            if (
                report.margin_agent_status in ("pending", "failed")
                or normalized_agent == "margin_agent"
            ):

                async def run_margin():
                    async with orchestrator.phase_sem:
                        orchestrator.checkout_status(
                            ticker, "margin_agent", period=latest_period
                        )
                        try:
                            margin_res = await asyncio.to_thread(
                                bo.run_margin_agent,
                                client=orchestrator.client,
                                company_metadata=state.metadata,
                                workspace_state=state,
                                period_key=latest_period,
                                learnings=learning_context,
                            )
                            orchestrator.checkin_status(
                                ticker,
                                "margin_agent",
                                "completed",
                                period=latest_period,
                                payload=margin_res,
                            )
                        except Exception as e:
                            logger.error(f"Margin Agent failed: {e}")
                            orchestrator.checkin_status(
                                ticker,
                                "margin_agent",
                                "failed",
                                period=latest_period,
                            )
                            raise

                tasks.append(
                    orchestrator.wrap_task(
                        "margin_agent", latest_period, None, run_margin
                    )
                )

        # D. Non-Operating Agent
        if normalized_agent is None or normalized_agent == "non_operating_agent":
            if (
                report.non_operating_agent_status in ("pending", "failed")
                or normalized_agent == "non_operating_agent"
            ):

                async def run_non_operating():
                    async with orchestrator.phase_sem:
                        orchestrator.checkout_status(
                            ticker, "non_operating_agent", period=latest_period
                        )
                        try:
                            non_op_res = await asyncio.to_thread(
                                bo.run_non_operating_agent,
                                client=orchestrator.client,
                                company_metadata=state.metadata,
                                workspace_state=state,
                                period_key=latest_period,
                                learnings=learning_context,
                            )
                            orchestrator.checkin_status(
                                ticker,
                                "non_operating_agent",
                                "completed",
                                period=latest_period,
                                payload=non_op_res,
                            )
                        except Exception as e:
                            logger.error(f"Non-Operating Agent failed: {e}")
                            orchestrator.checkin_status(
                                ticker,
                                "non_operating_agent",
                                "failed",
                                period=latest_period,
                            )
                            raise

                tasks.append(
                    orchestrator.wrap_task(
                        "non_operating_agent",
                        latest_period,
                        None,
                        run_non_operating,
                    )
                )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            await orchestrator._process_failure_queue(ticker, non_interactive)

    await process_modeling_l1()

    if normalized_agent in (
        "wacc_agent",
        "growth_agent",
        "margin_agent",
        "non_operating_agent",
    ):
        return

    # Compile DCF model assumptions
    cur_state = load_workspace_state(ticker)
    cur_report = cur_state.reports[latest_period]

    if not cur_report.base_model or cur_report.dcf_modeling_status in (
        "pending",
        "failed",
    ):
        modeler = Modeler()

        workspace = Path(orchestrator.settings.active_workspace_path)
        base_assumptions = modeler.calculate_default_assumptions(
            ticker, workspace, learning_context
        )

        try:
            sub_agent_logs = (
                f"WACC explanation: {base_assumptions.get('wacc_explanation', '')}\n"
                f"Growth explanation: {base_assumptions.get('growth_explanation', '')}\n"
                f"Margin explanation: {base_assumptions.get('margin_explanation', '')}\n"
                f"Non-Operating explanation: {base_assumptions.get('non_operating_explanation', '')}"
            )
            CuratorAgent(orchestrator.settings).curate(
                ticker, "model", sub_agent_logs, update_wiki=False
            )
        except Exception as e:
            logger.error(f"Curator initial model curation failed: {e}")

        # Reload updated model learning context after curation
        curated_learning_context = ""
        if learnings_path.exists():
            try:
                curated_learning_context = learnings_path.read_text(encoding="utf-8")
            except Exception:
                pass

        # Level 2 (Sequential): Run dcf_modeling_agent in a wrapped task
        async def run_dcf_modeling():
            orchestrator.checkout_status(ticker, "dcf_modeling", period=latest_period)
            try:
                final_assumptions = modeler.estimate_llm_assumptions(
                    ticker, workspace, base_assumptions, curated_learning_context
                )

                # Recalculate projections and output
                dcf_result, projections, valuation_table_str = (
                    modeler.run_valuation_calculation(
                        ticker, workspace, final_assumptions
                    )
                )

                # Create BaseFinancialModel Pydantic model
                model_assumptions = ModelAssumptions(
                    wacc=final_assumptions["wacc"],
                    company_beta_levered=final_assumptions.get("levered_beta", 1.0),
                    company_beta_unlevered=final_assumptions.get("unlevered_beta", 1.0),
                    industry_beta_unlevered=final_assumptions.get(
                        "unlevered_beta", 1.0
                    ),
                    risk_free_rate=final_assumptions.get("risk_free_rate", 0.042),
                    equity_risk_premium=final_assumptions.get(
                        "equity_risk_premium", 0.05
                    ),
                    pretax_cost_of_debt=final_assumptions.get(
                        "cost_debt_pretax", 0.062
                    ),
                    cost_of_equity=final_assumptions.get("cost_equity", 0.092),
                    weight_equity=final_assumptions.get("weight_equity", 1.0),
                    weight_debt=final_assumptions.get("weight_debt", 0.0),
                    target_debt_to_equity=final_assumptions.get(
                        "target_debt_to_equity", 0.0
                    ),
                    interest_expense=final_assumptions.get("interest_expense", 0.0),
                    capital_turnover=final_assumptions["capital_turnover"],
                    base_revenue=final_assumptions["base_revenue"],
                    base_invested_capital=final_assumptions["base_ic"],
                    revenue_growth_base=final_assumptions["base_growth_rate"],
                    revenue_growth_yr5=final_assumptions["revenue_growth_rate"],
                    ebita_margin_base=final_assumptions["base_margin"],
                    ebita_margin_yr5=final_assumptions["margin_yr5"],
                    terminal_margin=final_assumptions["terminal_margin"],
                    terminal_growth_rate=final_assumptions["terminal_growth_rate"],
                    adjusted_tax_rate=final_assumptions["adjusted_tax_rate"],
                    excess_cash=final_assumptions.get("cash", 0.0),
                    short_term_investments=final_assumptions.get(
                        "short_term_investments", 0.0
                    ),
                    debt=final_assumptions.get("debt", 0.0),
                    preferred_equity=final_assumptions.get("preferred_equity", 0.0),
                    minority_interest=final_assumptions.get("minority_interest", 0.0),
                    other_financial_assets_net=final_assumptions.get(
                        "other_financial", 0.0
                    ),
                    net_debt=final_assumptions.get("net_debt", 0.0),
                    shares_outstanding=final_assumptions["shares_outstanding"],
                    share_price=final_assumptions.get("share_price", 0.0),
                    market_cap=final_assumptions.get("market_cap", 0.0),
                )

                proj_years = [
                    DCFProjectionYear(
                        year=p["year"],
                        revenue=p["revenue"],
                        growth=p["growth"],
                        ebita=p["ebita"],
                        margin=p["margin"],
                        nopat=p["nopat"],
                        reinvestment=p["reinvestment"],
                        invested_capital=p["ic"],
                        roic=p["roic"],
                        fcf=p["fcf"],
                        discount_factor=p["df"],
                        present_value=p["pv"],
                    )
                    for p in projections
                ]

                base_model = BaseFinancialModel(
                    assumptions=model_assumptions,
                    projections=proj_years,
                    calculated_intrinsic_value_per_share=dcf_result[
                        "intrinsic_value_per_share"
                    ],
                    calculated_equity_value=dcf_result["equity_value"],
                    calculated_enterprise_value=dcf_result["enterprise_value"],
                    upside_downside_percentage=dcf_result["upside_downside"],
                    dcf_run_date=dcf_result["calculation_date"],
                )

                orchestrator.checkin_status(
                    ticker,
                    "dcf_modeling",
                    "completed",
                    period=latest_period,
                    payload=base_model,
                )

                # Generate financial model files on disk for backward compatibility
                modeler.generate_financial_model(ticker, workspace, final_assumptions)

                # Curate wiki
                dcf_agent_logs = final_assumptions.get("dcf_agent_log", "")
                CuratorAgent(orchestrator.settings).curate(
                    ticker, "model", dcf_agent_logs, update_wiki=True
                )

            except Exception as e:
                logger.error(f"DCF Modeling Agent failed: {e}")
                orchestrator.checkin_status(
                    ticker, "dcf_modeling", "failed", period=latest_period
                )
                raise

        await orchestrator.wrap_task(
            "dcf_modeling", latest_period, None, run_dcf_modeling
        )
        await orchestrator._process_failure_queue(ticker, non_interactive)
