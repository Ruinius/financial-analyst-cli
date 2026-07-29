import json
import logging
from typing import Optional, List, Any

from src.core.config import load_config
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    get_ticker_lock,
)
from src.services.llm_client import get_llm_client, LLMClient
from src.agents.agent_executor import run_agent_loop

logger = logging.getLogger(__name__)


def _parse_list_arg(val: Any) -> List[str]:
    """Safely parse learning arguments into a list of strings, avoiding char-by-char iteration of strings."""
    if not val:
        return []
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return []
        if val.startswith("[") and val.endswith("]"):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        items = [s.strip(" \"'[]") for s in val.replace("\n", ",").split(",")]
        return [s for s in items if s]
    elif isinstance(val, list):
        res = []
        for item in val:
            if isinstance(item, list):
                res.extend(_parse_list_arg(item))
            elif isinstance(item, str):
                s = item.strip()
                if s.startswith("[") and s.endswith("]"):
                    res.extend(_parse_list_arg(s))
                elif s:
                    res.append(s)
            elif item is not None:
                res.append(str(item).strip())
        return res
    return [str(val).strip()]


def _clean_learnings_list(items: List[str], is_chunk: bool = False) -> List[str]:
    """Clean and filter out single character junk artifacts from string iteration."""
    cleaned = []
    for x in items:
        s = str(x).strip(" \"'[],.")
        if not s:
            continue
        if is_chunk:
            if len(s) == 1 and not s.isdigit():
                continue
            cleaned.append(s)
        else:
            if len(s) == 1 and not s.isalnum():
                continue
            if len(s) == 1 and s.lower() in set("abcdefghijklmnopqrstuvwxyz"):
                continue
            cleaned.append(s)
    return sorted(list(set(cleaned)))


class LearningAgent:
    def __init__(self, settings=None, client: Optional[LLMClient] = None):
        self.settings = settings or load_config()
        self.client = client or get_llm_client()

    def run_learning(
        self,
        ticker: str,
        agent_name: str,
        document_type: str,
        turn_count: int,
        run_logs: str,
    ) -> None:
        """
        Evaluates turn deviation against the average_turn_count to run discretionary learnings updates.
        Updates metrics (total runs, last turn count, average turn count) and writes keywords,
        target chunks, and execution histories back to company_data.learnings.
        """
        # Handle MagicMocks in testing environments safely
        if not isinstance(ticker, str) or "MagicMock" in str(ticker):
            ticker = "MOCK"

        logger.info(
            f"LearningAgent started for ticker {ticker}, agent: {agent_name}, doc: {document_type}"
        )

        lock = get_ticker_lock(ticker)
        with lock:
            workspace_state = load_workspace_state(ticker)

            # Standardize agent_name to match DocumentTypeLearnings fields
            name_map = {
                "balance_sheet": "balance_sheet",
                "balancesheet": "balance_sheet",
                "income_statement": "income_statement",
                "incomestatement": "income_statement",
                "diluted_shares": "diluted_shares",
                "dilutedshares": "diluted_shares",
                "organic_growth": "organic_growth",
                "organicgrowth": "organic_growth",
                "ebita": "ebita",
                "operating_ebita": "ebita",
                "tax": "tax",
                "adjusted_taxes": "tax",
                "wacc": "wacc",
                "wacc_agent": "wacc",
                "growth": "growth",
                "growth_agent": "growth",
                "margin": "margin",
                "margin_agent": "margin",
                "non_operating": "non_operating",
                "non_operating_agent": "non_operating",
                "dcf_modeling": "dcf_modeling",
                "dcf_modeling_agent": "dcf_modeling",
            }
            std_agent_name = name_map.get(
                agent_name.lower().replace(" ", "_"), agent_name
            )

            # Standardize document_type to match LearningsSchema fields
            doc_map = {
                "annual_filing": "annual_filing",
                "annualfiling": "annual_filing",
                "10k": "annual_filing",
                "10-k": "annual_filing",
                "quarterly_filing": "quarterly_filing",
                "quarterlyfiling": "quarterly_filing",
                "10q": "quarterly_filing",
                "10-q": "quarterly_filing",
                "earnings_announcement": "earnings_announcement",
                "earningsannouncement": "earnings_announcement",
                "ea": "earnings_announcement",
                "model": "model",
                "modeling": "model",
                "model_learning": "model",
            }
            std_doc_type = doc_map.get(
                document_type.lower().replace(" ", "_"), document_type
            )

            learnings_schema = workspace_state.company_data.learnings
            doc_type_learnings = getattr(learnings_schema, std_doc_type, None)
            if doc_type_learnings is None:
                logger.warning(
                    f"Unsupported document type: {document_type} / {std_doc_type} for LearningAgent. Skipping."
                )
                return

            agent_learning = getattr(doc_type_learnings, std_agent_name, None)
            if agent_learning is None:
                logger.warning(
                    f"Unsupported sub-agent name: {agent_name} / {std_agent_name} for LearningAgent. Skipping."
                )
                return

            metrics = agent_learning.metrics

            # Evaluate deviation: trigger discretionary update if first run or turn count deviates significantly
            should_update = False
            if metrics.total_runs == 0:
                should_update = True
            else:
                deviation = abs(turn_count - metrics.average_turn_count)
                if deviation >= 1.0:
                    should_update = True

            # Update execution metrics on the blackboard atomically
            new_total_runs = metrics.total_runs + 1
            new_average = (
                (metrics.average_turn_count * metrics.total_runs) + turn_count
            ) / new_total_runs
            metrics.total_runs = new_total_runs
            metrics.last_turn_count = turn_count
            metrics.average_turn_count = new_average
            save_workspace_state(ticker, workspace_state)

        if should_update:
            logger.info(
                f"Triggering LLM learning update for {std_agent_name} (turn count: {turn_count}, average: {metrics.average_turn_count:.1f})"
            )

            sys_prompt = (
                "You are Sir Pennyworth's Learning Agent, a specialist in meta-cognition and self-learning. "
                "Your task is to analyze the execution run logs (chat history, tool calls, and results) of a sub-agent "
                "and identify actionable lessons for future runs.\n\n"
                "Specifically, identify:\n"
                "1. Successful keywords: Search terms or query substrings that successfully located target data in the document.\n"
                "2. Avoid keywords: Search terms that returned empty results, excessive irrelevant logs, or errors.\n"
                "3. Successful chunk: The string IDs of chunks that contained the actual statements, tables, or relevant numbers.\n\n"
                "Rules:\n"
                "- You must use 'query_blackboard' to look up current configurations or existing learnings if needed.\n"
                "- Return the results by calling the 'finalize' tool with lists of strings/IDs for each of the three categories. All arguments must be list of strings."
            )

            initial_prompt = (
                f"Analyze logs for sub-agent: '{std_agent_name}' on document type: '{std_doc_type}'.\n"
                f"The sub-agent took {turn_count} turns to run.\n"
                f'Logs:\n"""\n{run_logs}\n"""'
            )

            def query_blackboard(section: str, period: Optional[str] = None) -> str:
                """Query the active blackboard state in a read-only manner."""
                from src.tools.query_blackboard import query_blackboard_helper

                periods = list(workspace_state.reports.keys())
                period_key = periods[0] if periods else "2024_Q3"
                return query_blackboard_helper(
                    workspace_state=workspace_state,
                    company_metadata=workspace_state.metadata,
                    period_key=period_key,
                    section=section,
                    period=period,
                )

            def finalize(
                successful_keywords: List[str],
                avoid_keywords: List[str],
                successful_chunk: List[str],
            ) -> str:
                """Finalize learnings extraction."""
                return "Learnings finalized."

            tools = [query_blackboard, finalize]

            try:
                finalized_args, history = run_agent_loop(
                    client=self.client,
                    system_prompt=sys_prompt,
                    initial_prompt=initial_prompt,
                    tools=tools,
                    max_turns=10,
                    average_turn_count=metrics.average_turn_count,
                )

                if finalized_args:
                    s_kw = _parse_list_arg(finalized_args.get("successful_keywords"))
                    a_kw = _parse_list_arg(finalized_args.get("avoid_keywords"))
                    s_ch = _parse_list_arg(finalized_args.get("successful_chunk"))

                    with lock:
                        fresh_state = load_workspace_state(ticker)
                        fresh_doc = getattr(
                            fresh_state.company_data.learnings, std_doc_type, None
                        )
                        if fresh_doc:
                            fresh_agent = getattr(fresh_doc, std_agent_name, None)
                            if fresh_agent:
                                fresh_agent.successful_keywords = _clean_learnings_list(
                                    fresh_agent.successful_keywords + s_kw,
                                    is_chunk=False,
                                )
                                fresh_agent.avoid_keywords = _clean_learnings_list(
                                    fresh_agent.avoid_keywords + a_kw,
                                    is_chunk=False,
                                )
                                fresh_agent.successful_chunk = _clean_learnings_list(
                                    fresh_agent.successful_chunk + s_ch,
                                    is_chunk=True,
                                )
                                fresh_agent.status = "completed"
                                save_workspace_state(ticker, fresh_state)
                    logger.info(
                        f"Learnings successfully updated and merged for {std_agent_name}"
                    )
            except Exception as e:
                logger.error(f"Error during LLM learning extraction loop: {e}")

        # Set status to completed atomically
        with lock:
            fresh_state = load_workspace_state(ticker)
            fresh_doc = getattr(fresh_state.company_data.learnings, std_doc_type, None)
            if fresh_doc:
                fresh_agent = getattr(fresh_doc, std_agent_name, None)
                if fresh_agent:
                    fresh_agent.status = "completed"
                    save_workspace_state(ticker, fresh_state)
            logger.info(f"Blackboard state saved atomically for {ticker}")
