import asyncio
import logging
import json
from pathlib import Path
from typing import Optional

from src.core.exceptions import WorkspaceError
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    TemporalBlackboard,
    LineItem as BlackboardLineItem,
)

logger = logging.getLogger(__name__)


async def orchestrate_extract(
    orchestrator,
    ticker: str,
    agent: Optional[str] = None,
    non_interactive: bool = False,
) -> None:
    import src.agents.blackboard_orchestrator as bo
    from src.agents.ingester import Ingester

    state = load_workspace_state(ticker)
    settings = orchestrator.settings
    workspace = Path(settings.active_workspace_path)

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
        if agent_lower in extract_agent_map:
            normalized_agent = extract_agent_map[agent_lower]
        elif agent_lower in model_agent_map:
            # Modeling agent, skip this stage
            return
        else:
            raise WorkspaceError(f"Unknown agent: '{agent}'")

    # Verify global dependency: company metadata extraction must be completed first for non-metadata agents
    if normalized_agent and normalized_agent != "metadata":
        if state.metadata_status != "completed":
            raise WorkspaceError(
                "Missing dependency: Company metadata extraction must be completed first."
            )

    # 1. Run MetadataAgent if pending or failed, or explicitly targeted
    if (normalized_agent == "metadata") or (
        state.metadata_status in ("pending", "failed") and normalized_agent is None
    ):
        # Load parsed documents context
        parsed_dir = workspace / "2_parsed_data"
        parsed_documents = {}
        if parsed_dir.exists():
            for p in parsed_dir.iterdir():
                if (
                    p.is_file()
                    and p.suffix.lower() == ".md"
                    and p.name.lower() != "readme.md"
                    and not p.name.startswith(".")
                ):
                    try:
                        parsed_documents[p.name] = p.read_text(encoding="utf-8")
                    except Exception:
                        pass

        orchestrator.checkout_status(ticker, "metadata")
        try:
            metadata = await asyncio.to_thread(
                bo.run_metadata_agent,
                client=orchestrator.client,
                ticker=ticker,
                parsed_documents=parsed_documents,
            )
            orchestrator.checkin_status(
                ticker, "metadata", "completed", payload=metadata
            )
        except Exception as e:
            logger.error(f"MetadataAgent execution failed: {e}")
            orchestrator.checkin_status(ticker, "metadata", "failed")
            if non_interactive:
                raise WorkspaceError(f"Metadata extraction failed: {e}")
            return

    # If we are only running metadata agent, stop here
    if normalized_agent == "metadata":
        return

    # Reload state
    state = load_workspace_state(ticker)
    if state.metadata_status != "completed":
        logger.warning(
            "Metadata extraction is not completed. Cannot proceed with sub-agents."
        )
        return

    ingester = Ingester()
    registry = ingester.load_parsed_registry()

    # Group docs by period_key
    periods_docs = {}
    for row in registry.values():
        fy = row.get("fiscal_year")
        fq = row.get("fiscal_quarter")
        if not fy or not fq or fy == "N/A" or fq == "N/A":
            continue
        period_key = f"{fy}_{fq}"
        periods_docs.setdefault(period_key, []).append(row)

    # For each period, initialize reports on blackboard
    for period_key in periods_docs:
        if period_key not in state.reports:
            fy_str, fq_str = period_key.split("_")
            is_q = "Q" in fq_str
            state.reports[period_key] = TemporalBlackboard(
                fiscal_year=int(fy_str),
                fiscal_period=fq_str,
                is_quarterly=is_q,
            )
    save_workspace_state(ticker, state)

    # Get learnings string context
    learnings_path = workspace / f"{ticker}_extract_learning.md"
    learnings = ""
    if learnings_path.exists():
        try:
            learnings = learnings_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # Helper to convert line item types
    from src.agents.extractor_orchestrator import (
        LineItem as OrchestratorLineItem,
        AuditLinkage,
    )
    from src.agents.extractor_agents.extractor_financials import (
        parse_markdown_to_line_items,
    )
    from src.agents.extractor_orchestrator import Extractor

    extractor_dummy = Extractor()

    def convert_to_blackboard_line_item(
        item: OrchestratorLineItem,
    ) -> BlackboardLineItem:
        cat = item.category
        if cat == "current_asset":
            cat = "current_assets"
        elif cat == "noncurrent_asset":
            cat = "noncurrent_assets"
        elif cat == "current_liability":
            cat = "current_liabilities"
        elif cat == "noncurrent_liability":
            cat = "noncurrent_liabilities"
        elif cat not in [
            "current_assets",
            "noncurrent_assets",
            "current_liabilities",
            "noncurrent_liabilities",
            "equity",
            "income_statement",
        ]:
            if "asset" in cat:
                cat = "current_assets"
            elif "liabilit" in cat:
                cat = "current_liabilities"
            elif "equity" in cat:
                cat = "equity"
            else:
                cat = "income_statement"
        return BlackboardLineItem(
            line_name=item.line_name,
            value=item.value,
            operating=item.operating,
            calculated=item.calculated,
            category=cat,
        )

    def convert_to_orchestrator_line_item(
        item: BlackboardLineItem,
    ) -> OrchestratorLineItem:
        cat = item.category
        if cat == "current_assets":
            cat = "current_asset"
        elif cat == "noncurrent_assets":
            cat = "noncurrent_asset"
        return OrchestratorLineItem(
            line_name=item.line_name,
            value=item.value,
            operating=item.operating,
            calculated=item.calculated,
            category=cat,
            audit=AuditLinkage(source_file="blackboard", chunk_id=0, exact_snippet=""),
        )

    updated_periods = set()

    # Check prerequisites for single agents that target specific periods
    if normalized_agent == "shares":
        has_valid_period = any(
            report.income_statement_status == "completed"
            for report in state.reports.values()
        )
        if not has_valid_period:
            raise WorkspaceError(
                "Missing dependency: Income statement must be completed for at least one period before running shares agent."
            )
    elif normalized_agent == "organic_growth":
        has_valid_period = any(
            report.income_statement_status == "completed"
            for report in state.reports.values()
        )
        if not has_valid_period:
            raise WorkspaceError(
                "Missing dependency: Income statement must be completed for at least one period before running organic growth agent."
            )
    elif normalized_agent == "interpretation":
        has_valid_period = any(
            report.balance_sheet_status == "completed"
            and report.income_statement_status == "completed"
            for report in state.reports.values()
        )
        if not has_valid_period:
            raise WorkspaceError(
                "Missing dependency: Both balance sheet and income statement must be completed for at least one period before running interpretation agent."
            )
    elif normalized_agent == "ebita":
        has_valid_period = any(
            report.income_statement_status == "completed"
            for report in state.reports.values()
        )
        if not has_valid_period:
            raise WorkspaceError(
                "Missing dependency: Income statement must be completed for at least one period before running EBITA agent."
            )
    elif normalized_agent == "tax":
        has_valid_period = any(
            report.income_statement_status == "completed"
            for report in state.reports.values()
        )
        if not has_valid_period:
            raise WorkspaceError(
                "Missing dependency: Income statement must be completed for at least one period before running tax agent."
            )

    # Define inner tasks for concurrent execution

    # 1. Extraction Phase (Parallel) Tasks
    async def run_balance_sheet(
        period_key: str, fn: str, content: str, is_q: bool, doc_type: str
    ):
        async with orchestrator.doc_sem:
            orchestrator.checkout_status(ticker, "balance_sheet", period=period_key)
            try:
                res = await asyncio.to_thread(
                    bo.run_balance_sheet_agent,
                    client=orchestrator.client,
                    filename=fn,
                    content=content,
                    company_metadata=state.metadata,
                    learnings=learnings,
                    is_quarterly=is_q,
                )

                # GAAP Override check
                is_formal = doc_type in ("quarterly_filing", "annual_filing")
                cur_state = load_workspace_state(ticker)
                report = cur_state.reports[period_key]

                has_formal_in_source = False
                for sf in report.source_files:
                    for reg_row in registry.values():
                        if reg_row["new_filename"] == sf:
                            if reg_row.get("document_type") in (
                                "quarterly_filing",
                                "annual_filing",
                            ):
                                has_formal_in_source = True
                                break

                should_overwrite = is_formal or not has_formal_in_source

                orchestrator.checkin_status(
                    ticker,
                    "balance_sheet",
                    "completed",
                    period=period_key,
                    payload=res if should_overwrite else None,
                )

                if should_overwrite:
                    # Parse table to line items
                    tmp_file = Path("tmp") / f"bs_{period_key}.md"
                    tmp_file.write_text(
                        res.raw_balance_sheet_markdown, encoding="utf-8"
                    )
                    bs_items = parse_markdown_to_line_items(
                        workspace / "2_parsed_data" / fn,
                        tmp_file,
                        extractor_dummy,
                        "current_assets",
                    )
                    if tmp_file.exists():
                        tmp_file.unlink()

                    # Append to blackboard line items (replacing previous Balance Sheet items)
                    cur_state = load_workspace_state(ticker)
                    report = cur_state.reports[period_key]
                    report.financial_data.line_items = [
                        item
                        for item in report.financial_data.line_items
                        if item.category
                        not in (
                            "current_assets",
                            "noncurrent_assets",
                            "current_liabilities",
                            "noncurrent_liabilities",
                            "equity",
                        )
                    ]
                    report.financial_data.line_items.extend(
                        [convert_to_blackboard_line_item(x) for x in bs_items]
                    )
                    if fn not in report.source_files:
                        report.source_files.append(fn)
                    save_workspace_state(ticker, cur_state)
                else:
                    cur_state = load_workspace_state(ticker)
                    report = cur_state.reports[period_key]
                    if fn not in report.source_files:
                        report.source_files.append(fn)
                    save_workspace_state(ticker, cur_state)
                    logger.info(
                        f"Skipping GAAP override for {fn} as formal filing data is already present."
                    )

                updated_periods.add(period_key)

            except Exception as e:
                logger.error(f"Balance sheet agent failed for {fn}: {e}")
                orchestrator.checkin_status(
                    ticker, "balance_sheet", "failed", period=period_key
                )
                cur_state = load_workspace_state(ticker)
                err_msg = str(e)
                cur_state.reports[period_key].arithmetic_errors.append(
                    f"Balance Sheet Agent failure for {fn}: {err_msg}"
                )
                if fn not in cur_state.reports[period_key].source_files:
                    cur_state.reports[period_key].source_files.append(fn)
                save_workspace_state(ticker, cur_state)
                raise

    async def run_income_statement(
        period_key: str, fn: str, content: str, is_q: bool, doc_type: str
    ):
        async with orchestrator.doc_sem:
            orchestrator.checkout_status(ticker, "income_statement", period=period_key)
            try:
                res = await asyncio.to_thread(
                    bo.run_income_statement_agent,
                    client=orchestrator.client,
                    filename=fn,
                    content=content,
                    company_metadata=state.metadata,
                    learnings=learnings,
                    is_quarterly=is_q,
                )

                # GAAP Override check
                is_formal = doc_type in ("quarterly_filing", "annual_filing")
                cur_state = load_workspace_state(ticker)
                report = cur_state.reports[period_key]

                has_formal_in_source = False
                for sf in report.source_files:
                    for reg_row in registry.values():
                        if reg_row["new_filename"] == sf:
                            if reg_row.get("document_type") in (
                                "quarterly_filing",
                                "annual_filing",
                            ):
                                has_formal_in_source = True
                                break

                should_overwrite = is_formal or not has_formal_in_source

                orchestrator.checkin_status(
                    ticker,
                    "income_statement",
                    "completed",
                    period=period_key,
                    payload=res if should_overwrite else None,
                )

                if should_overwrite:
                    # Parse table to line items
                    tmp_file = Path("tmp") / f"is_{period_key}.md"
                    tmp_file.write_text(
                        res.raw_income_statement_markdown, encoding="utf-8"
                    )
                    is_items = parse_markdown_to_line_items(
                        workspace / "2_parsed_data" / fn,
                        tmp_file,
                        extractor_dummy,
                        "income_statement",
                    )
                    if tmp_file.exists():
                        tmp_file.unlink()

                    # Append to blackboard line items (replacing previous Income Statement items)
                    cur_state = load_workspace_state(ticker)
                    report = cur_state.reports[period_key]
                    report.financial_data.line_items = [
                        item
                        for item in report.financial_data.line_items
                        if item.category != "income_statement"
                    ]
                    report.financial_data.line_items.extend(
                        [convert_to_blackboard_line_item(x) for x in is_items]
                    )
                    if fn not in report.source_files:
                        report.source_files.append(fn)
                    save_workspace_state(ticker, cur_state)
                else:
                    cur_state = load_workspace_state(ticker)
                    report = cur_state.reports[period_key]
                    if fn not in report.source_files:
                        report.source_files.append(fn)
                    save_workspace_state(ticker, cur_state)
                    logger.info(
                        f"Skipping GAAP override for {fn} as formal filing data is already present."
                    )

                updated_periods.add(period_key)

            except Exception as e:
                logger.error(f"Income statement agent failed for {fn}: {e}")
                orchestrator.checkin_status(
                    ticker, "income_statement", "failed", period=period_key
                )
                cur_state = load_workspace_state(ticker)
                err_msg = str(e)
                cur_state.reports[period_key].arithmetic_errors.append(
                    f"Income Statement Agent failure for {fn}: {err_msg}"
                )
                if fn not in cur_state.reports[period_key].source_files:
                    cur_state.reports[period_key].source_files.append(fn)
                save_workspace_state(ticker, cur_state)
                raise

    async def run_analyst_report(period_key: str, fn: str, content: str):
        async with orchestrator.doc_sem:
            try:
                res = await asyncio.to_thread(
                    bo.run_analyst_report_agent,
                    client=orchestrator.client,
                    filename=fn,
                    content=content,
                    company_metadata=state.metadata,
                    learnings=learnings,
                )
                # Checkin
                cur_state = load_workspace_state(ticker)
                cur_state.reports[period_key].other_data.analyst_reports.append(res)
                if fn not in cur_state.reports[period_key].source_files:
                    cur_state.reports[period_key].source_files.append(fn)
                save_workspace_state(ticker, cur_state)
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"AnalystReportAgent failed for {fn}: {e}")
                raise

    async def run_other_doc(period_key: str, fn: str, content: str):
        async with orchestrator.doc_sem:
            try:
                res = await asyncio.to_thread(
                    bo.run_other_doc_agent,
                    client=orchestrator.client,
                    filename=fn,
                    content=content,
                    company_metadata=state.metadata,
                    learnings=learnings,
                )
                # Checkin
                cur_state = load_workspace_state(ticker)
                cur_state.reports[period_key].other_data.others.append(res)
                if fn not in cur_state.reports[period_key].source_files:
                    cur_state.reports[period_key].source_files.append(fn)
                save_workspace_state(ticker, cur_state)
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"OtherDocAgent failed for {fn}: {e}")
                raise

    # 2. Metrics Level 1 (Parallel) Tasks
    async def run_shares_task(period_key: str):
        async with orchestrator.phase_sem:
            cur_state = load_workspace_state(ticker)
            is_q = "Q" in period_key

            registry_rows = periods_docs.get(period_key, [])
            parsed_documents = {}
            for r in registry_rows:
                fn = r["new_filename"]
                doc_path = workspace / "2_parsed_data" / fn
                if doc_path.exists():
                    parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

            orchestrator.checkout_status(ticker, "shares", period=period_key)
            try:
                basic, diluted = await asyncio.to_thread(
                    bo.run_diluted_shares_agent,
                    client=orchestrator.client,
                    parsed_documents=parsed_documents,
                    company_metadata=state.metadata,
                    workspace_state=cur_state,
                    period_key=period_key,
                    is_quarterly=is_q,
                    learnings=learnings,
                )
                orchestrator.checkin_status(
                    ticker,
                    "shares",
                    "completed",
                    period=period_key,
                    payload=(basic, diluted),
                )
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"SharesAgent failed for {period_key}: {e}")
                orchestrator.checkin_status(
                    ticker, "shares", "failed", period=period_key
                )
                raise

    async def run_organic_growth_task(period_key: str):
        async with orchestrator.phase_sem:
            cur_state = load_workspace_state(ticker)
            is_q = "Q" in period_key

            registry_rows = periods_docs.get(period_key, [])
            parsed_documents = {}
            for r in registry_rows:
                fn = r["new_filename"]
                doc_path = workspace / "2_parsed_data" / fn
                if doc_path.exists():
                    parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

            orchestrator.checkout_status(ticker, "organic_growth", period=period_key)
            try:
                (
                    simple_growth,
                    organic_growth,
                    revenue,
                ) = await asyncio.to_thread(
                    bo.run_organic_growth_agent,
                    client=orchestrator.client,
                    parsed_documents=parsed_documents,
                    company_metadata=state.metadata,
                    workspace_state=cur_state,
                    period_key=period_key,
                    is_quarterly=is_q,
                    learnings=learnings,
                )

                # Non-GAAP Preservation
                old_report = cur_state.reports[period_key]
                old_org_growth = old_report.financial_data.organic_growth
                resolved_organic_growth = organic_growth
                if (
                    organic_growth == 0.0 or organic_growth == simple_growth
                ) and old_org_growth != 0.0:
                    resolved_organic_growth = old_org_growth

                orchestrator.checkin_status(
                    ticker,
                    "organic_growth",
                    "completed",
                    period=period_key,
                    payload=(simple_growth, resolved_organic_growth, revenue),
                )
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"OrganicGrowthAgent failed for {period_key}: {e}")
                orchestrator.checkin_status(
                    ticker, "organic_growth", "failed", period=period_key
                )
                raise

    async def run_interpretation_task(period_key: str):
        async with orchestrator.phase_sem:
            cur_state = load_workspace_state(ticker)
            report = cur_state.reports[period_key]
            is_q = "Q" in period_key

            if report.financial_data.line_items:
                try:
                    # Convert to orchestrator LineItem objects
                    orig_items = [
                        convert_to_orchestrator_line_item(x)
                        for x in report.financial_data.line_items
                    ]
                    interpreted_items = await asyncio.to_thread(
                        bo.run_interpretation_agent,
                        client=orchestrator.client,
                        extracted_line_items=orig_items,
                        company_metadata=state.metadata,
                        workspace_state=cur_state,
                        period_key=period_key,
                        is_quarterly=is_q,
                        learnings=learnings,
                    )
                    # Update
                    cur_state = load_workspace_state(ticker)
                    cur_state.reports[period_key].financial_data.line_items = [
                        convert_to_blackboard_line_item(x) for x in interpreted_items
                    ]
                    save_workspace_state(ticker, cur_state)
                    updated_periods.add(period_key)
                except Exception as e:
                    logger.error(f"InterpretationAgent failed for {period_key}: {e}")
                    raise

    # 3. Metrics Level 2 (Parallel) Tasks
    async def run_ebita_task(period_key: str):
        async with orchestrator.phase_sem:
            cur_state = load_workspace_state(ticker)
            is_q = "Q" in period_key

            registry_rows = periods_docs.get(period_key, [])
            parsed_documents = {}
            for r in registry_rows:
                fn = r["new_filename"]
                doc_path = workspace / "2_parsed_data" / fn
                if doc_path.exists():
                    parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

            orchestrator.checkout_status(ticker, "ebita", period=period_key)
            try:
                op_inc, ebita, ebita_adjustments = await asyncio.to_thread(
                    bo.run_ebita_agent,
                    client=orchestrator.client,
                    parsed_documents=parsed_documents,
                    company_metadata=state.metadata,
                    workspace_state=cur_state,
                    period_key=period_key,
                    is_quarterly=is_q,
                    learnings=learnings,
                )

                # Non-GAAP Preservation
                old_report = cur_state.reports[period_key]
                old_ebita = old_report.financial_data.ebita
                old_op_inc = old_report.financial_data.operating_income
                has_old_adjustments = (old_ebita != 0.0) and (old_ebita != old_op_inc)
                has_new_adjustments = (ebita != 0.0) and (ebita != op_inc)

                resolved_ebita = ebita
                resolved_adjustments = ebita_adjustments
                if not has_new_adjustments and has_old_adjustments:
                    resolved_ebita = old_ebita
                    try:
                        resolved_adjustments = json.loads(
                            old_report.financial_data.raw_notes_markdown
                        )
                    except Exception:
                        pass

                orchestrator.checkin_status(
                    ticker,
                    "ebita",
                    "completed",
                    period=period_key,
                    payload=(op_inc, resolved_ebita),
                )

                # Store adjustments in notes/metadata for next agent
                cur_state = load_workspace_state(ticker)
                cur_state.reports[
                    period_key
                ].financial_data.raw_notes_markdown = json.dumps(resolved_adjustments)
                save_workspace_state(ticker, cur_state)
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"EbitaAgent failed for {period_key}: {e}")
                orchestrator.checkin_status(
                    ticker, "ebita", "failed", period=period_key
                )
                raise

    async def run_tax_task(period_key: str):
        async with orchestrator.phase_sem:
            cur_state = load_workspace_state(ticker)
            report = cur_state.reports[period_key]
            is_q = "Q" in period_key

            registry_rows = periods_docs.get(period_key, [])
            parsed_documents = {}
            for r in registry_rows:
                fn = r["new_filename"]
                doc_path = workspace / "2_parsed_data" / fn
                if doc_path.exists():
                    parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

            orchestrator.checkout_status(ticker, "tax", period=period_key)
            try:
                # Get ebita adjustments from notes
                ebita_adjustments = []
                notes = report.financial_data.raw_notes_markdown
                if notes:
                    try:
                        ebita_adjustments = json.loads(notes)
                    except Exception:
                        pass

                op_ebita = (
                    report.financial_data.ebita
                    if report.ebita_status == "completed"
                    else 0.0
                )

                (
                    inc_bt,
                    rep_tax,
                    adj_taxes,
                    tax_adjustments,
                ) = await asyncio.to_thread(
                    bo.run_tax_agent,
                    client=orchestrator.client,
                    parsed_documents=parsed_documents,
                    company_metadata=state.metadata,
                    workspace_state=cur_state,
                    period_key=period_key,
                    operating_income=report.financial_data.operating_income,
                    operating_ebita=op_ebita,
                    ebita_adjustments=ebita_adjustments,
                    is_quarterly=is_q,
                    learnings=learnings,
                )

                # Non-GAAP Preservation
                old_report = cur_state.reports[period_key]
                old_rep_tax = old_report.financial_data.reported_tax_provision
                old_adj_tax = old_report.financial_data.adjusted_taxes
                has_old_tax_adj = (old_adj_tax != 0.0) and (old_adj_tax != old_rep_tax)
                has_new_tax_adj = (adj_taxes != 0.0) and (adj_taxes != rep_tax)

                resolved_adj_taxes = adj_taxes
                if not has_new_tax_adj and has_old_tax_adj:
                    resolved_adj_taxes = old_adj_tax

                orchestrator.checkin_status(
                    ticker,
                    "tax",
                    "completed",
                    period=period_key,
                    payload=(inc_bt, rep_tax, resolved_adj_taxes),
                )
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"TaxAgent failed for {period_key}: {e}")
                orchestrator.checkin_status(ticker, "tax", "failed", period=period_key)
                raise

    # ----------------------------------------------------
    # Execution Gating & Concurrency
    # ----------------------------------------------------

    # 1. Extraction Phase (Parallel)
    extract_tasks = []
    for period_key, doc_rows in periods_docs.items():
        for row in doc_rows:
            fn = row["new_filename"]
            doc_type = row.get("document_type", "other")
            is_q = "Q" in period_key

            doc_path = workspace / "2_parsed_data" / fn
            if not doc_path.exists():
                continue
            content = doc_path.read_text(encoding="utf-8")

            # Check period report lock / status
            report = state.reports[period_key]

            is_formal = doc_type in (
                "quarterly_filing",
                "annual_filing",
                "earnings_announcement",
            )
            if is_formal:
                # Income Statement
                if normalized_agent is None or normalized_agent == "income_statement":
                    if (
                        report.income_statement_status in ("pending", "failed")
                        or (is_formal and fn not in report.source_files)
                        or normalized_agent == "income_statement"
                    ):
                        extract_tasks.append(
                            orchestrator.wrap_task(
                                "income_statement",
                                period_key,
                                fn,
                                lambda pk=period_key,
                                f=fn,
                                c=content,
                                iq=is_q,
                                dt=doc_type: run_income_statement(pk, f, c, iq, dt),
                            )
                        )

                # Balance Sheet
                if normalized_agent is None or normalized_agent == "balance_sheet":
                    if (
                        report.balance_sheet_status in ("pending", "failed")
                        or (is_formal and fn not in report.source_files)
                        or normalized_agent == "balance_sheet"
                    ):
                        extract_tasks.append(
                            orchestrator.wrap_task(
                                "balance_sheet",
                                period_key,
                                fn,
                                lambda pk=period_key,
                                f=fn,
                                c=content,
                                iq=is_q,
                                dt=doc_type: run_balance_sheet(pk, f, c, iq, dt),
                            )
                        )
            else:
                # Qualitative extractions
                if doc_type == "analyst_report":
                    if normalized_agent is None or normalized_agent == "analyst_report":
                        if fn not in report.source_files:
                            extract_tasks.append(
                                orchestrator.wrap_task(
                                    "analyst_report",
                                    period_key,
                                    fn,
                                    lambda pk=period_key,
                                    f=fn,
                                    c=content: run_analyst_report(pk, f, c),
                                )
                            )
                elif doc_type in (
                    "press_release",
                    "news_article",
                    "transcript",
                    "other",
                ):
                    if normalized_agent is None or normalized_agent == "other":
                        if fn not in report.source_files:
                            extract_tasks.append(
                                orchestrator.wrap_task(
                                    "other",
                                    period_key,
                                    fn,
                                    lambda pk=period_key,
                                    f=fn,
                                    c=content: run_other_doc(pk, f, c),
                                )
                            )

    if extract_tasks:
        await asyncio.gather(*extract_tasks, return_exceptions=True)
        await orchestrator._process_failure_queue(ticker, non_interactive)

    # Reload state to have all latest extractions available for metrics
    state = load_workspace_state(ticker)

    # 2. Metrics Level 1 (Parallel)
    metrics_l1_tasks = []
    for period_key in periods_docs:
        report = state.reports[period_key]

        # A. Diluted Shares Agent
        if normalized_agent is None or normalized_agent == "shares":
            if (
                report.shares_status in ("pending", "failed")
                or normalized_agent == "shares"
            ):
                if report.income_statement_status == "completed":
                    metrics_l1_tasks.append(
                        orchestrator.wrap_task(
                            "shares",
                            period_key,
                            None,
                            lambda pk=period_key: run_shares_task(pk),
                        )
                    )

        # B. Organic Growth Agent
        if normalized_agent is None or normalized_agent == "organic_growth":
            if (
                report.organic_growth_status in ("pending", "failed")
                or normalized_agent == "organic_growth"
            ):
                if report.income_statement_status == "completed":
                    metrics_l1_tasks.append(
                        orchestrator.wrap_task(
                            "organic_growth",
                            period_key,
                            None,
                            lambda pk=period_key: run_organic_growth_task(pk),
                        )
                    )

        # C. Interpretation Agent
        if normalized_agent is None or normalized_agent == "interpretation":
            if (
                report.balance_sheet_status == "completed"
                and report.income_statement_status == "completed"
            ):
                metrics_l1_tasks.append(
                    orchestrator.wrap_task(
                        "interpretation",
                        period_key,
                        None,
                        lambda pk=period_key: run_interpretation_task(pk),
                    )
                )

    if metrics_l1_tasks:
        await asyncio.gather(*metrics_l1_tasks, return_exceptions=True)
        await orchestrator._process_failure_queue(ticker, non_interactive)

    # Reload state to have interpretation outputs available for Metrics Level 2
    state = load_workspace_state(ticker)

    # 3. Metrics Level 2 (Parallel)
    metrics_l2_tasks = []
    for period_key in periods_docs:
        report = state.reports[period_key]

        # Run operating_ebita
        if normalized_agent is None or normalized_agent == "ebita":
            if (
                report.ebita_status in ("pending", "failed")
                or normalized_agent == "ebita"
            ):
                if report.income_statement_status == "completed":
                    metrics_l2_tasks.append(
                        orchestrator.wrap_task(
                            "ebita",
                            period_key,
                            None,
                            lambda pk=period_key: run_ebita_task(pk),
                        )
                    )

        # Run adjusted_taxes
        if normalized_agent is None or normalized_agent == "tax":
            if report.tax_status in ("pending", "failed") or normalized_agent == "tax":
                if report.income_statement_status == "completed":
                    metrics_l2_tasks.append(
                        orchestrator.wrap_task(
                            "tax",
                            period_key,
                            None,
                            lambda pk=period_key: run_tax_task(pk),
                        )
                    )

    if metrics_l2_tasks:
        await asyncio.gather(*metrics_l2_tasks, return_exceptions=True)
        await orchestrator._process_failure_queue(ticker, non_interactive)

    # 5. Deterministic Calculations for capital and ROIC
    import src.utils.financial_math as pipeline_math

    cur_state = load_workspace_state(ticker)
    for period_key, report in cur_state.reports.items():
        if normalized_agent and period_key not in updated_periods:
            continue

        if (
            report.balance_sheet_status != "completed"
            or report.income_statement_status != "completed"
        ):
            continue

        try:
            # Calculations
            revenue = report.financial_data.revenue
            ebita = report.financial_data.ebita
            adjusted_tax_rate = report.financial_data.adjusted_tax_rate or 0.21

            is_quarterly = "Q" in period_key
            multiplier = 4.0 if is_quarterly else 1.0

            # Group line items
            oca_items = [
                item
                for item in report.financial_data.line_items
                if item.category == "current_assets" and item.operating
            ]
            ocl_items = [
                item
                for item in report.financial_data.line_items
                if item.category == "current_liabilities" and item.operating
            ]
            onca_items = [
                item
                for item in report.financial_data.line_items
                if item.category == "noncurrent_assets" and item.operating
            ]
            oncl_items = [
                item
                for item in report.financial_data.line_items
                if item.category == "noncurrent_liabilities" and item.operating
            ]

            oca = sum(item.value for item in oca_items)
            ocl = sum(item.value for item in ocl_items)
            onca = sum(item.value for item in onca_items)
            oncl = sum(item.value for item in oncl_items)

            ann_rev = revenue * multiplier
            nwc, nltoa, ic, turnover = pipeline_math.calculate_invested_capital(
                oca, ocl, onca, oncl, ann_rev
            )

            nopat, annualized_nopat, roic = pipeline_math.calculate_roic(
                ebita, adjusted_tax_rate, ic, multiplier
            )

            # Save back
            report.financial_data.net_working_capital = nwc
            report.financial_data.net_long_term_operating_assets = nltoa
            report.financial_data.invested_capital = ic
            report.financial_data.capital_turnover = turnover
            report.financial_data.nopat = nopat
            report.financial_data.roic = roic

        except Exception as e:
            logger.error(f"Deterministic calculations failed for {period_key}: {e}")

    save_workspace_state(ticker, cur_state)
