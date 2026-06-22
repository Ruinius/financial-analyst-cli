import asyncio
import logging
import json
from pathlib import Path
from typing import Any, Optional, Literal

from src.core.config import load_config
from src.core.exceptions import WorkspaceError
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    TemporalBlackboard,
    LineItem as BlackboardLineItem,
    BaseFinancialModel,
    DCFProjectionYear,
    ModelAssumptions,
)
from src.services.llm_client import get_llm_client

# Extractor agents
from src.agents.extractor_agents.metadata_agent import run_metadata_agent
from src.agents.extractor_agents.extractor_financials_agents.balance_sheet_agent import (
    run_balance_sheet_agent,
)
from src.agents.extractor_agents.extractor_financials_agents.income_statement_agent import (
    run_income_statement_agent,
)
from src.agents.extractor_agents.extractor_financials_agents.interpretation_agent import (
    run_interpretation_agent,
)
from src.agents.extractor_agents.extractor_financials_agents.diluted_shares_agent import (
    run_diluted_shares_agent,
)
from src.agents.extractor_agents.extractor_financials_agents.organic_growth_agent import (
    run_organic_growth_agent,
)
from src.agents.extractor_agents.extractor_financials_agents.ebita_agent import (
    run_ebita_agent,
)
from src.agents.extractor_agents.extractor_financials_agents.tax_agent import (
    run_tax_agent,
)
from src.agents.extractor_agents.extractor_analyst_report import (
    run_analyst_report_agent,
)
from src.agents.extractor_agents.extractor_other import run_other_doc_agent

# Modeler agents
from src.agents.modeler_agents.wacc_agent import run_wacc_agent
from src.agents.modeler_agents.growth_agent import run_growth_agent
from src.agents.modeler_agents.margin_agent import run_margin_agent
from src.agents.modeler_agents.non_operating_agent import run_non_operating_agent

logger = logging.getLogger(__name__)


class BlackboardOrchestrator:
    def __init__(self, settings=None, client=None):
        self.settings = settings or load_config()
        self.client = client or get_llm_client()

        # Concurrency knobs (configurable via settings)
        company_limit = getattr(self.settings, "concurrency_limit_company", 1)
        doc_limit = getattr(self.settings, "concurrency_limit_document", 3)
        phase_limit = getattr(self.settings, "concurrency_limit_phase", 3)

        self.company_sem = asyncio.Semaphore(company_limit)
        self.doc_sem = asyncio.Semaphore(doc_limit)
        self.phase_sem = asyncio.Semaphore(phase_limit)
        self.sem = self.phase_sem  # Alias for backward compatibility

    def recover_dangling_states(self, ticker: str) -> None:
        """Scan the blackboard for tasks stuck in 'running' state and reset them to 'failed'."""
        try:
            state = load_workspace_state(ticker)
        except Exception:
            return

        if state.recover_dangling_states():
            save_workspace_state(ticker, state)
            logger.info("Recovered dangling 'running' states on blackboard startup.")

    def checkout_status(
        self,
        ticker: str,
        task_type: str,
        period: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> None:
        """Transition a task flag to 'running' and save state atomically to disk."""
        state = load_workspace_state(ticker)
        state.checkout_status(task_type, period, file_name)
        save_workspace_state(ticker, state)

    def checkin_status(
        self,
        ticker: str,
        task_type: str,
        status: Literal["completed", "failed"],
        period: Optional[str] = None,
        file_name: Optional[str] = None,
        payload: Optional[Any] = None,
    ) -> None:
        """Transition a task flag to completed/failed and write payload to appropriate block."""
        state = load_workspace_state(ticker)
        state.checkin_status(task_type, status, period, file_name, payload)
        save_workspace_state(ticker, state)

    async def run_pipeline(
        self,
        ticker: str,
        stage: Optional[str] = None,
        agent: Optional[str] = None,
        non_interactive: bool = False,
    ) -> None:
        """Executes full or stage-level execution of the blackboard coordinator."""
        async with self.company_sem:
            self.recover_dangling_states(ticker)

            if stage is None or stage == "ingest":
                await self._orchestrate_ingest(ticker)

            if stage is None or stage == "extract":
                await self._orchestrate_extract(ticker, agent, non_interactive)

            if stage is None or stage == "analyze":
                await self._orchestrate_analyze(ticker)

            if stage is None or stage == "model":
                await self._orchestrate_model(ticker, agent, non_interactive)

    async def _orchestrate_ingest(self, ticker: str) -> None:
        """Orchestrate ingest stage."""
        from src.agents.ingester import Ingester, compute_sha256

        ingester = Ingester()
        settings = self.settings
        workspace = Path(settings.active_workspace_path)
        ingest_dir = workspace / "1_ingest_data"
        if not ingest_dir.exists():
            return

        raw_files = [
            p
            for p in ingest_dir.iterdir()
            if p.is_file()
            and p.name.lower() != "readme.md"
            and not p.name.startswith(".")
        ]

        if not raw_files:
            return

        registry = ingester.load_parsed_registry()

        for raw_file in raw_files:
            file_hash = compute_sha256(raw_file)
            state = load_workspace_state(ticker)
            is_processed = any(
                doc.file_name == raw_file.name and doc.ingestion_status == "completed"
                for doc in state.raw_documents
            )
            if is_processed or file_hash in registry:
                continue

            self.checkout_status(ticker, "ingestion", file_name=raw_file.name)
            try:
                await asyncio.to_thread(ingester.ingest_single_file, raw_file, registry)
                self.checkin_status(
                    ticker,
                    "ingestion",
                    "completed",
                    file_name=raw_file.name,
                    payload={"sha256": file_hash},
                )
            except Exception as e:
                logger.error(f"Ingestion failed for {raw_file.name}: {e}")
                self.checkin_status(
                    ticker, "ingestion", "failed", file_name=raw_file.name
                )

        ingester.save_parsed_registry(registry)
        ingester.run_quality_check_agent()
        ingester.heal_markdown_files()
        ingester.heal_ingest_context(registry)

    async def _orchestrate_extract(
        self, ticker: str, agent: Optional[str] = None, non_interactive: bool = False
    ) -> None:
        """Orchestrate extract stage."""
        state = load_workspace_state(ticker)
        settings = self.settings
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

            self.checkout_status(ticker, "metadata")
            try:
                metadata = await asyncio.to_thread(
                    run_metadata_agent,
                    client=self.client,
                    ticker=ticker,
                    parsed_documents=parsed_documents,
                )
                self.checkin_status(ticker, "metadata", "completed", payload=metadata)
            except Exception as e:
                logger.error(f"MetadataAgent execution failed: {e}")
                self.checkin_status(ticker, "metadata", "failed")
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

        # Load parsed registry to group documents by period
        from src.agents.ingester import Ingester

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
                audit=AuditLinkage(
                    source_file="blackboard", chunk_id=0, exact_snippet=""
                ),
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
        async def run_balance_sheet(period_key: str, fn: str, content: str, is_q: bool):
            async with self.doc_sem:
                self.checkout_status(ticker, "balance_sheet", period=period_key)
                try:
                    res = await asyncio.to_thread(
                        run_balance_sheet_agent,
                        client=self.client,
                        filename=fn,
                        content=content,
                        company_metadata=state.metadata,
                        learnings=learnings,
                        is_quarterly=is_q,
                    )
                    self.checkin_status(
                        ticker,
                        "balance_sheet",
                        "completed",
                        period=period_key,
                        payload=res,
                    )

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

                    # Append to blackboard line items
                    cur_state = load_workspace_state(ticker)
                    cur_state.reports[period_key].financial_data.line_items.extend(
                        [convert_to_blackboard_line_item(x) for x in bs_items]
                    )
                    if fn not in cur_state.reports[period_key].source_files:
                        cur_state.reports[period_key].source_files.append(fn)
                    save_workspace_state(ticker, cur_state)
                    updated_periods.add(period_key)

                except Exception as e:
                    logger.error(f"Balance sheet agent failed for {fn}: {e}")
                    self.checkin_status(
                        ticker, "balance_sheet", "failed", period=period_key
                    )

        async def run_income_statement(
            period_key: str, fn: str, content: str, is_q: bool
        ):
            async with self.doc_sem:
                self.checkout_status(ticker, "income_statement", period=period_key)
                try:
                    res = await asyncio.to_thread(
                        run_income_statement_agent,
                        client=self.client,
                        filename=fn,
                        content=content,
                        company_metadata=state.metadata,
                        learnings=learnings,
                        is_quarterly=is_q,
                    )
                    self.checkin_status(
                        ticker,
                        "income_statement",
                        "completed",
                        period=period_key,
                        payload=res,
                    )

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

                    # Append to blackboard line items
                    cur_state = load_workspace_state(ticker)
                    cur_state.reports[period_key].financial_data.line_items.extend(
                        [convert_to_blackboard_line_item(x) for x in is_items]
                    )
                    if fn not in cur_state.reports[period_key].source_files:
                        cur_state.reports[period_key].source_files.append(fn)
                    save_workspace_state(ticker, cur_state)
                    updated_periods.add(period_key)

                except Exception as e:
                    logger.error(f"Income statement agent failed for {fn}: {e}")
                    self.checkin_status(
                        ticker, "income_statement", "failed", period=period_key
                    )

        async def run_analyst_report(period_key: str, fn: str, content: str):
            async with self.doc_sem:
                try:
                    res = await asyncio.to_thread(
                        run_analyst_report_agent,
                        client=self.client,
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

        async def run_other_doc(period_key: str, fn: str, content: str):
            async with self.doc_sem:
                try:
                    res = await asyncio.to_thread(
                        run_other_doc_agent,
                        client=self.client,
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

        # 2. Metrics Level 1 (Parallel) Tasks
        async def run_shares_task(period_key: str):
            async with self.phase_sem:
                cur_state = load_workspace_state(ticker)
                is_q = "Q" in period_key

                registry_rows = periods_docs.get(period_key, [])
                parsed_documents = {}
                for r in registry_rows:
                    fn = r["new_filename"]
                    doc_path = workspace / "2_parsed_data" / fn
                    if doc_path.exists():
                        parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

                self.checkout_status(ticker, "shares", period=period_key)
                try:
                    basic, diluted = await asyncio.to_thread(
                        run_diluted_shares_agent,
                        client=self.client,
                        parsed_documents=parsed_documents,
                        company_metadata=state.metadata,
                        workspace_state=cur_state,
                        period_key=period_key,
                        is_quarterly=is_q,
                        learnings=learnings,
                    )
                    self.checkin_status(
                        ticker,
                        "shares",
                        "completed",
                        period=period_key,
                        payload=(basic, diluted),
                    )
                    updated_periods.add(period_key)
                except Exception as e:
                    logger.error(f"SharesAgent failed for {period_key}: {e}")
                    self.checkin_status(ticker, "shares", "failed", period=period_key)

        async def run_organic_growth_task(period_key: str):
            async with self.phase_sem:
                cur_state = load_workspace_state(ticker)
                is_q = "Q" in period_key

                registry_rows = periods_docs.get(period_key, [])
                parsed_documents = {}
                for r in registry_rows:
                    fn = r["new_filename"]
                    doc_path = workspace / "2_parsed_data" / fn
                    if doc_path.exists():
                        parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

                self.checkout_status(ticker, "organic_growth", period=period_key)
                try:
                    (
                        simple_growth,
                        organic_growth,
                        revenue,
                    ) = await asyncio.to_thread(
                        run_organic_growth_agent,
                        client=self.client,
                        parsed_documents=parsed_documents,
                        company_metadata=state.metadata,
                        workspace_state=cur_state,
                        period_key=period_key,
                        is_quarterly=is_q,
                        learnings=learnings,
                    )
                    self.checkin_status(
                        ticker,
                        "organic_growth",
                        "completed",
                        period=period_key,
                        payload=(simple_growth, organic_growth, revenue),
                    )
                    updated_periods.add(period_key)
                except Exception as e:
                    logger.error(f"OrganicGrowthAgent failed for {period_key}: {e}")
                    self.checkin_status(
                        ticker, "organic_growth", "failed", period=period_key
                    )

        async def run_interpretation_task(period_key: str):
            async with self.phase_sem:
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
                            run_interpretation_agent,
                            client=self.client,
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
                            convert_to_blackboard_line_item(x)
                            for x in interpreted_items
                        ]
                        save_workspace_state(ticker, cur_state)
                        updated_periods.add(period_key)
                    except Exception as e:
                        logger.error(
                            f"InterpretationAgent failed for {period_key}: {e}"
                        )

        # 3. Metrics Level 2 (Parallel) Tasks
        async def run_ebita_task(period_key: str):
            async with self.phase_sem:
                cur_state = load_workspace_state(ticker)
                is_q = "Q" in period_key

                registry_rows = periods_docs.get(period_key, [])
                parsed_documents = {}
                for r in registry_rows:
                    fn = r["new_filename"]
                    doc_path = workspace / "2_parsed_data" / fn
                    if doc_path.exists():
                        parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

                self.checkout_status(ticker, "ebita", period=period_key)
                try:
                    op_inc, ebita, ebita_adjustments = await asyncio.to_thread(
                        run_ebita_agent,
                        client=self.client,
                        parsed_documents=parsed_documents,
                        company_metadata=state.metadata,
                        workspace_state=cur_state,
                        period_key=period_key,
                        is_quarterly=is_q,
                        learnings=learnings,
                    )
                    self.checkin_status(
                        ticker,
                        "ebita",
                        "completed",
                        period=period_key,
                        payload=(op_inc, ebita),
                    )

                    # Store adjustments in notes/metadata for next agent
                    cur_state = load_workspace_state(ticker)
                    cur_state.reports[
                        period_key
                    ].financial_data.raw_notes_markdown = json.dumps(ebita_adjustments)
                    save_workspace_state(ticker, cur_state)
                    updated_periods.add(period_key)
                except Exception as e:
                    logger.error(f"EbitaAgent failed for {period_key}: {e}")
                    self.checkin_status(ticker, "ebita", "failed", period=period_key)

        async def run_tax_task(period_key: str):
            async with self.phase_sem:
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

                self.checkout_status(ticker, "tax", period=period_key)
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
                        run_tax_agent,
                        client=self.client,
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
                    self.checkin_status(
                        ticker,
                        "tax",
                        "completed",
                        period=period_key,
                        payload=(inc_bt, rep_tax, adj_taxes),
                    )
                    updated_periods.add(period_key)
                except Exception as e:
                    logger.error(f"TaxAgent failed for {period_key}: {e}")
                    self.checkin_status(ticker, "tax", "failed", period=period_key)

        # ----------------------------------------------------
        # Execution Gating & Concurrency
        # ----------------------------------------------------

        # Setup Phase is Sequential and already completed (metadata_agent run is handled above).

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
                    if (
                        normalized_agent is None
                        or normalized_agent == "income_statement"
                    ):
                        if (
                            report.income_statement_status in ("pending", "failed")
                            or (is_formal and fn not in report.source_files)
                            or normalized_agent == "income_statement"
                        ):
                            extract_tasks.append(
                                run_income_statement(period_key, fn, content, is_q)
                            )

                    # Balance Sheet
                    if normalized_agent is None or normalized_agent == "balance_sheet":
                        if (
                            report.balance_sheet_status in ("pending", "failed")
                            or (is_formal and fn not in report.source_files)
                            or normalized_agent == "balance_sheet"
                        ):
                            extract_tasks.append(
                                run_balance_sheet(period_key, fn, content, is_q)
                            )
                else:
                    # Qualitative extractions
                    if doc_type == "analyst_report":
                        if (
                            normalized_agent is None
                            or normalized_agent == "analyst_report"
                        ):
                            if fn not in report.source_files:
                                extract_tasks.append(
                                    run_analyst_report(period_key, fn, content)
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
                                    run_other_doc(period_key, fn, content)
                                )

        if extract_tasks:
            await asyncio.gather(*extract_tasks)

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
                        metrics_l1_tasks.append(run_shares_task(period_key))

            # B. Organic Growth Agent
            if normalized_agent is None or normalized_agent == "organic_growth":
                if (
                    report.organic_growth_status in ("pending", "failed")
                    or normalized_agent == "organic_growth"
                ):
                    if report.income_statement_status == "completed":
                        metrics_l1_tasks.append(run_organic_growth_task(period_key))

            # C. Interpretation Agent
            if normalized_agent is None or normalized_agent == "interpretation":
                if (
                    report.balance_sheet_status == "completed"
                    and report.income_statement_status == "completed"
                ):
                    metrics_l1_tasks.append(run_interpretation_task(period_key))

        if metrics_l1_tasks:
            await asyncio.gather(*metrics_l1_tasks)

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
                        metrics_l2_tasks.append(run_ebita_task(period_key))

            # Run adjusted_taxes
            if normalized_agent is None or normalized_agent == "tax":
                if (
                    report.tax_status in ("pending", "failed")
                    or normalized_agent == "tax"
                ):
                    if report.income_statement_status == "completed":
                        metrics_l2_tasks.append(run_tax_task(period_key))

        if metrics_l2_tasks:
            await asyncio.gather(*metrics_l2_tasks)

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

    async def _orchestrate_analyze(self, ticker: str) -> None:
        """Orchestrate analyze stage."""
        self.checkout_status(ticker, "analyzer")
        try:
            state = load_workspace_state(ticker)

            quarterly_financials_list = []
            yearly_financials_list = []
            historical_analyst_views_list = []

            # Populate quarterly and annual lists
            from src.core.blackboard import (
                HistoricalFinancialSummary,
                HistoricalAnalystView,
            )

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
            quarterly_financials_list.sort(
                key=lambda x: (x.fiscal_year, x.fiscal_period)
            )
            yearly_financials_list.sort(key=lambda x: x.fiscal_year)

            state.company_data.quarterly_financials = quarterly_financials_list
            state.company_data.yearly_financials = yearly_financials_list
            state.company_data.historical_analyst_views = historical_analyst_views_list

            save_workspace_state(ticker, state)
            self.checkin_status(ticker, "analyzer", "completed")

            # Curate learnings
            from src.agents.curator_agent import CuratorAgent

            CuratorAgent(self.settings).curate(
                ticker, "analyze", "Analyzed and synthesized trends."
            )

        except Exception as e:
            logger.error(f"Analysis orchestration failed: {e}")
            self.checkin_status(ticker, "analyzer", "failed")

    async def _orchestrate_model(
        self, ticker: str, agent: Optional[str] = None, non_interactive: bool = False
    ) -> None:
        """Orchestrate model stage."""
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
            Path(self.settings.active_workspace_path) / f"{ticker}_model_learning.md"
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
                        async with self.phase_sem:
                            self.checkout_status(
                                ticker, "wacc_agent", period=latest_period
                            )
                            try:
                                wacc_res = await asyncio.to_thread(
                                    run_wacc_agent,
                                    client=self.client,
                                    company_metadata=state.metadata,
                                    workspace_state=state,
                                    period_key=latest_period,
                                    learnings=learning_context,
                                )
                                self.checkin_status(
                                    ticker,
                                    "wacc_agent",
                                    "completed",
                                    period=latest_period,
                                    payload=wacc_res,
                                )
                            except Exception as e:
                                logger.error(f"WACC Agent failed: {e}")
                                self.checkin_status(
                                    ticker, "wacc_agent", "failed", period=latest_period
                                )

                    tasks.append(run_wacc())

            # B. Growth Agent
            if normalized_agent is None or normalized_agent == "growth_agent":
                if (
                    report.growth_agent_status in ("pending", "failed")
                    or normalized_agent == "growth_agent"
                ):

                    async def run_growth():
                        async with self.phase_sem:
                            self.checkout_status(
                                ticker, "growth_agent", period=latest_period
                            )
                            try:
                                growth_res = await asyncio.to_thread(
                                    run_growth_agent,
                                    client=self.client,
                                    company_metadata=state.metadata,
                                    workspace_state=state,
                                    period_key=latest_period,
                                    learnings=learning_context,
                                )
                                self.checkin_status(
                                    ticker,
                                    "growth_agent",
                                    "completed",
                                    period=latest_period,
                                    payload=growth_res,
                                )
                            except Exception as e:
                                logger.error(f"Growth Agent failed: {e}")
                                self.checkin_status(
                                    ticker,
                                    "growth_agent",
                                    "failed",
                                    period=latest_period,
                                )

                    tasks.append(run_growth())

            # C. Margin Agent
            if normalized_agent is None or normalized_agent == "margin_agent":
                if (
                    report.margin_agent_status in ("pending", "failed")
                    or normalized_agent == "margin_agent"
                ):

                    async def run_margin():
                        async with self.phase_sem:
                            self.checkout_status(
                                ticker, "margin_agent", period=latest_period
                            )
                            try:
                                margin_res = await asyncio.to_thread(
                                    run_margin_agent,
                                    client=self.client,
                                    company_metadata=state.metadata,
                                    workspace_state=state,
                                    period_key=latest_period,
                                    learnings=learning_context,
                                )
                                self.checkin_status(
                                    ticker,
                                    "margin_agent",
                                    "completed",
                                    period=latest_period,
                                    payload=margin_res,
                                )
                            except Exception as e:
                                logger.error(f"Margin Agent failed: {e}")
                                self.checkin_status(
                                    ticker,
                                    "margin_agent",
                                    "failed",
                                    period=latest_period,
                                )

                    tasks.append(run_margin())

            # D. Non-Operating Agent
            if normalized_agent is None or normalized_agent == "non_operating_agent":
                if (
                    report.non_operating_agent_status in ("pending", "failed")
                    or normalized_agent == "non_operating_agent"
                ):

                    async def run_non_operating():
                        async with self.phase_sem:
                            self.checkout_status(
                                ticker, "non_operating_agent", period=latest_period
                            )
                            try:
                                non_op_res = await asyncio.to_thread(
                                    run_non_operating_agent,
                                    client=self.client,
                                    company_metadata=state.metadata,
                                    workspace_state=state,
                                    period_key=latest_period,
                                    learnings=learning_context,
                                )
                                self.checkin_status(
                                    ticker,
                                    "non_operating_agent",
                                    "completed",
                                    period=latest_period,
                                    payload=non_op_res,
                                )
                            except Exception as e:
                                logger.error(f"Non-Operating Agent failed: {e}")
                                self.checkin_status(
                                    ticker,
                                    "non_operating_agent",
                                    "failed",
                                    period=latest_period,
                                )

                    tasks.append(run_non_operating())

            if tasks:
                await asyncio.gather(*tasks)

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
            # Load default assumptions from modeler_orchestrator
            from src.agents.modeler_orchestrator import Modeler

            modeler = Modeler()

            workspace = Path(self.settings.active_workspace_path)
            base_assumptions = modeler.calculate_default_assumptions(
                ticker, workspace, learning_context
            )

            # Run curator initial model run recommendation
            from src.agents.curator_agent import CuratorAgent

            try:
                sub_agent_logs = (
                    f"WACC explanation: {base_assumptions.get('wacc_explanation', '')}\n"
                    f"Growth explanation: {base_assumptions.get('growth_explanation', '')}\n"
                    f"Margin explanation: {base_assumptions.get('margin_explanation', '')}\n"
                    f"Non-Operating explanation: {base_assumptions.get('non_operating_explanation', '')}"
                )
                CuratorAgent(self.settings).curate(
                    ticker, "model", sub_agent_logs, update_wiki=False
                )
            except Exception as e:
                logger.error(f"Curator initial model curation failed: {e}")

            # Reload updated model learning context after curation
            curated_learning_context = ""
            if learnings_path.exists():
                try:
                    curated_learning_context = learnings_path.read_text(
                        encoding="utf-8"
                    )
                except Exception:
                    pass

            # Level 2 (Sequential): Run dcf_modeling_agent
            self.checkout_status(ticker, "dcf_modeling", period=latest_period)
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

                self.checkin_status(
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
                CuratorAgent(self.settings).curate(
                    ticker, "model", dcf_agent_logs, update_wiki=True
                )

            except Exception as e:
                logger.error(f"DCF Modeling Agent failed: {e}")
                self.checkin_status(
                    ticker, "dcf_modeling", "failed", period=latest_period
                )
