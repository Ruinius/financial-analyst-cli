import asyncio
import logging
from typing import Any, Optional, Literal, List

from src.core.config import load_config
from src.core.exceptions import WorkspaceError
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
)
from src.services.llm_client import get_llm_client

# Extractor agents
from src.agents.extractor_agents.metadata_agent import (
    run_metadata_agent as run_metadata_agent,
)  # noqa: F401
from src.agents.extractor_agents.extractor_financials_agents.balance_sheet_agent import (
    run_balance_sheet_agent as run_balance_sheet_agent,  # noqa: F401
)
from src.agents.extractor_agents.extractor_financials_agents.income_statement_agent import (
    run_income_statement_agent as run_income_statement_agent,  # noqa: F401
)
from src.agents.extractor_agents.extractor_financials_agents.interpretation_agent import (
    run_interpretation_agent as run_interpretation_agent,  # noqa: F401
)
from src.agents.extractor_agents.extractor_financials_agents.diluted_shares_agent import (
    run_diluted_shares_agent as run_diluted_shares_agent,  # noqa: F401
)
from src.agents.extractor_agents.extractor_financials_agents.organic_growth_agent import (
    run_organic_growth_agent as run_organic_growth_agent,  # noqa: F401
)
from src.agents.extractor_agents.extractor_financials_agents.ebita_agent import (
    run_ebita_agent as run_ebita_agent,  # noqa: F401
)
from src.agents.extractor_agents.extractor_financials_agents.tax_agent import (
    run_tax_agent as run_tax_agent,  # noqa: F401
)
from src.agents.extractor_agents.extractor_analyst_report import (
    run_analyst_report_agent as run_analyst_report_agent,  # noqa: F401
)
from src.agents.extractor_agents.extractor_other import (
    run_other_doc_agent as run_other_doc_agent,
)  # noqa: F401

# Modeler agents
from src.agents.modeler_agents.wacc_agent import run_wacc_agent as run_wacc_agent  # noqa: F401
from src.agents.modeler_agents.growth_agent import run_growth_agent as run_growth_agent  # noqa: F401
from src.agents.modeler_agents.margin_agent import run_margin_agent as run_margin_agent  # noqa: F401
from src.agents.modeler_agents.non_operating_agent import (
    run_non_operating_agent as run_non_operating_agent,
)  # noqa: F401

logger = logging.getLogger(__name__)


class FailedTask:
    def __init__(
        self,
        task_type: str,
        coro_factory,
        period: Optional[str] = None,
        file_name: Optional[str] = None,
        exception: Optional[Exception] = None,
    ):
        self.task_type = task_type
        self.coro_factory = coro_factory
        self.period = period
        self.file_name = file_name
        self.exception = exception
        self.retry_count = 0


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

        self._failure_queue = []
        self._active_tasks = set()

    def _is_network_failure(self, exc: Exception) -> bool:
        """Differentiate network/API failures from validation/quality issues."""
        from pydantic import ValidationError
        from src.core.exceptions import LLMError
        import httpx

        if isinstance(exc, ValidationError):
            return False

        msg = str(exc).lower()

        # Validation/quality/turn-limit check failures are NOT network failures
        if any(
            term in msg
            for term in ["validation", "quality", "finalize", "turn limit", "max turns"]
        ):
            return False

        # Network/connection/rate-limit indicators
        network_indicators = [
            "timeout",
            "connection",
            "rate limit",
            "overloaded",
            "network",
            "http",
            "api error",
            "status code 429",
            "status code 5",
            "unavailable",
        ]
        if any(ind in msg for ind in network_indicators):
            return True

        if isinstance(
            exc, (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError)
        ):
            return True

        # Treat generic LLMError as network failure unless turn/quality/validation
        if isinstance(exc, LLMError):
            return True

        return False

    async def _process_failure_queue(self, ticker: str, non_interactive: bool) -> None:
        """Process failed tasks sequentially."""
        import sys
        import typer
        from src.utils import formatting

        while self._failure_queue:
            failed_task = self._failure_queue.pop(0)
            task_desc = f"{failed_task.task_type}"
            if failed_task.period:
                task_desc += f" for period {failed_task.period}"
            if failed_task.file_name:
                task_desc += f" (file: {failed_task.file_name})"

            formatting.print_error(f"Task failure detected: {task_desc}")
            formatting.print_error(f"Error detail: {failed_task.exception}")

            if non_interactive:
                # Non-Interactive Mode
                if self._is_network_failure(failed_task.exception):
                    if failed_task.retry_count < 3:
                        failed_task.retry_count += 1
                        formatting.print_info(
                            f"Retrying network failure (attempt {failed_task.retry_count}/3)..."
                        )
                        try:
                            # Re-submit the task
                            self.checkout_status(
                                ticker,
                                failed_task.task_type,
                                period=failed_task.period,
                                file_name=failed_task.file_name,
                            )
                            await failed_task.coro_factory()
                            formatting.print_success(
                                f"Retried task {task_desc} successfully."
                            )
                            continue
                        except Exception as e:
                            failed_task.exception = e
                            # Push back to queue to retry again or fail
                            self._failure_queue.insert(0, failed_task)
                            continue
                    else:
                        formatting.print_error(
                            f"Network failure retries exhausted for task {task_desc}."
                        )

                # Halts execution with exit code 1
                self.checkin_status(
                    ticker,
                    failed_task.task_type,
                    "failed",
                    period=failed_task.period,
                    file_name=failed_task.file_name,
                )
                formatting.print_error(
                    "Halting pipeline execution due to failure in non-interactive mode."
                )
                sys.exit(1)

            else:
                # Interactive Developer Mode
                formatting.print_info(
                    f"Please select a recovery strategy for failed task: {task_desc}"
                )
                choice = (
                    typer.prompt(
                        "Select recovery strategy (retry / dont-retry / stop-all)",
                        type=str,
                        default="retry",
                    )
                    .strip()
                    .lower()
                )

                if choice in ("retry", "r"):
                    try:
                        self.checkout_status(
                            ticker,
                            failed_task.task_type,
                            period=failed_task.period,
                            file_name=failed_task.file_name,
                        )
                        await failed_task.coro_factory()
                        formatting.print_success(
                            f"Task {task_desc} successfully recovered via Retry."
                        )
                        continue
                    except Exception as e:
                        failed_task.exception = e
                        # Put back to prompt again
                        self._failure_queue.insert(0, failed_task)
                        continue

                elif choice in ("dont-retry", "dont_retry", "d", "n"):
                    # Marks status 'failed' on the blackboard
                    self.checkin_status(
                        ticker,
                        failed_task.task_type,
                        "failed",
                        period=failed_task.period,
                        file_name=failed_task.file_name,
                    )
                    if failed_task.period:
                        state = load_workspace_state(ticker)
                        if failed_task.period in state.reports:
                            state.reports[failed_task.period].arithmetic_errors.append(
                                f"Task {failed_task.task_type} failed (user skipped retry): {failed_task.exception}"
                            )
                            save_workspace_state(ticker, state)
                    formatting.print_warning(
                        f"Skipping task {task_desc} and continuing pipeline."
                    )
                    continue

                elif choice in ("stop-all", "stop_all", "s"):
                    # Stop All: Marks status failed, cancels active futures, raises error
                    self.checkin_status(
                        ticker,
                        failed_task.task_type,
                        "failed",
                        period=failed_task.period,
                        file_name=failed_task.file_name,
                    )
                    formatting.print_error(
                        "Terminating all active futures and cancelling execution."
                    )
                    for t in list(self._active_tasks):
                        t.cancel()
                    if self._active_tasks:
                        await asyncio.gather(
                            *self._active_tasks, return_exceptions=True
                        )
                    raise WorkspaceError("Execution stopped by user.")
                else:
                    formatting.print_warning("Invalid choice. Re-prompting.")
                    self._failure_queue.insert(0, failed_task)

    async def wrap_task(
        self,
        task_type: str,
        period: Optional[str],
        file_name: Optional[str],
        coro_factory,
    ):
        try:
            active_task = asyncio.current_task()
            if active_task:
                self._active_tasks.add(active_task)
            await coro_factory()
        except Exception as e:
            failed_task = FailedTask(
                task_type=task_type,
                coro_factory=coro_factory,
                period=period,
                file_name=file_name,
                exception=e,
            )
            self._failure_queue.append(failed_task)
            raise e
        finally:
            active_task = asyncio.current_task()
            if active_task:
                self._active_tasks.discard(active_task)

    def recover_dangling_states(self, ticker: str) -> None:
        """Scan the blackboard for tasks stuck in 'running' state and reset them to 'failed'."""
        try:
            state = load_workspace_state(ticker)
        except Exception:
            return

        if state.recover_dangling_states():
            save_workspace_state(ticker, state)
            logger.info("Recovered dangling 'running' states on blackboard startup.")

    def _format_task_description(
        self,
        task_type: str,
        period: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> str:
        agent_names = {
            "metadata": "MetadataAgent",
            "balance_sheet": "BalanceSheetAgent",
            "income_statement": "IncomeStatementAgent",
            "shares": "DilutedSharesAgent",
            "organic_growth": "OrganicGrowthAgent",
            "ebita": "EBITAAgent",
            "tax": "TaxAgent",
            "interpretation": "InterpretationAgent",
            "analyst_report": "AnalystReportAgent",
            "other": "OtherDocAgent",
            "wacc": "WACCAgent",
            "wacc_agent": "WACCAgent",
            "growth": "GrowthAgent",
            "growth_agent": "GrowthAgent",
            "margin": "MarginAgent",
            "margin_agent": "MarginAgent",
            "non_operating": "NonOperatingAgent",
            "non_operating_agent": "NonOperatingAgent",
            "dcf_modeling": "DCFModelingAgent",
            "analyzer": "CuratorAgent",
            "ingestion": "IngestionAgent",
        }
        name = agent_names.get(
            task_type, task_type.replace("_", " ").title() + " Agent"
        )
        details = []
        if period:
            details.append(f"Period: {period}")
        if file_name:
            details.append(f"File: {file_name}")

        if details:
            return f"{name} ({', '.join(details)})"
        return name

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

        import src.utils.formatting as formatting

        desc = self._format_task_description(task_type, period, file_name)
        formatting.print_info(f"Starting sub-agent: {desc}...")

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

        import src.utils.formatting as formatting

        desc = self._format_task_description(task_type, period, file_name)
        if status == "completed":
            formatting.print_success(f"Sub-agent completed: {desc}")
        elif status == "failed":
            formatting.print_error(f"Sub-agent failed: {desc}")

    async def run_pipeline(
        self,
        ticker: str,
        stage: Optional[str] = None,
        agent: Optional[str] = None,
        non_interactive: bool = False,
        limit: Optional[int] = None,
        force: bool = False,
        target_files: Optional[List[str]] = None,
    ) -> None:
        """Executes full or stage-level execution of the blackboard coordinator."""
        self._failure_queue.clear()
        self._active_tasks.clear()
        async with self.company_sem:
            self.recover_dangling_states(ticker)

            if stage is None or stage == "ingest":
                from src.agents.orchestrator_pipelines.ingest import orchestrate_ingest

                await orchestrate_ingest(self, ticker, limit=limit)

            if stage is None or stage == "extract":
                from src.agents.orchestrator_pipelines.extract import (
                    orchestrate_extract,
                )

                await orchestrate_extract(
                    self,
                    ticker,
                    agent=agent,
                    non_interactive=non_interactive,
                    limit=limit,
                    force=force,
                    target_files=target_files,
                )

            if stage is None or stage == "analyze":
                from src.agents.orchestrator_pipelines.analyze import (
                    orchestrate_analyze,
                )

                await orchestrate_analyze(self, ticker)

            if stage is None or stage == "model":
                from src.agents.orchestrator_pipelines.model import orchestrate_model

                await orchestrate_model(self, ticker, agent, non_interactive)
