import logging
from typing import Optional
from pydantic import BaseModel
from src.services.llm_client import LLMClient
from src.core.blackboard import CompanyMetadata
from src.agents.agent_executor import run_agent_loop
from src.tools.find_chunk import get_chunk_by_id
from src.tools.keyword_search import find_keyword_contexts

logger = logging.getLogger(__name__)


class IncomeStatementExtraction(BaseModel):
    raw_income_statement_markdown: str
    currency: str
    unit: str


def check_income_statement_quality_helper(
    markdown_content: str, client: LLMClient, is_quarterly: bool = True
) -> str:
    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    sys_prompt = (
        "You are a senior financial auditor. Perform a quality check on the following extracted Income Statement. "
        f"Verify that it corresponds to the focused time period: {focus_period}. "
        "Verify that it contains all essential lines (Revenue, Operating Income, Net Income) and that intermediate math is correct. "
        "Return 'PASSED' if everything is correct. If there are missing fields, incorrect values, or mathematical inconsistencies, "
        "return a list of specific errors so the agent can edit the file."
    )
    prompt = f'Income Statement Markdown:\n"""\n{markdown_content}\n"""'
    try:
        res = client.generate(prompt, system_prompt=sys_prompt).strip()
        return res
    except Exception as e:
        return f"Quality check failed with exception: {e}"


def run_income_statement_agent(
    client: LLMClient,
    filename: str,
    content: str,
    company_metadata: CompanyMetadata,
    learnings: Optional[str] = None,
    is_quarterly: bool = True,
) -> IncomeStatementExtraction:
    """
    Stateless agent that extracts the Income Statement statement from document content.
    Returns an IncomeStatementExtraction schema. Enforces a 20-turn limit and tool restrictions.
    """
    max_turns = 20

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )

    initial_prompt = (
        f"Starting extraction for source file: '{filename}'.\n"
        f"Please locate and extract the COMPLETE Income Statement statement.\n"
        f"Focus period: {focus_period}.\n\n"
        f"To locate where the statement is, call `keyword_search` first, "
        f"then fetch the content with `find_chunk`."
    )

    if learnings:
        initial_prompt += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learnings}\n"""'

    system_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the Income Statement Agent. Your task is to locate and extract the COMPLETE Income Statement.\n"
        f"Specifically, we are focused on the {focus_period} time period. Ensure you extract the statement for this focused period.\n"
        "Rules:\n"
        "1. You start with only file name. You must find relevant chunks using keywords first.\n"
        "2. Fetch chunk content using find_chunk.\n"
        "3. Always call check_income_statement_quality before finalizing. If it returns errors, correct your table before finalizing.\n"
        "4. When you have found the complete statement and quality check passes, call the tool 'finalize' to return the extracted markdown table, detected currency (e.g. 'USD', 'CNY'), and unit (e.g. 'Millions', 'Billions', '10K').\n"
        "5. The table MUST be written as a valid, well-formed markdown table. Ensure that the table has a header row, followed immediately by a separator row (e.g., '| --- | --- | ...'), and all subsequent rows have the exact same number of columns.\n"
        "6. Currency & Unit detection: Identify the reporting currency and unit of the financial statements in the document. Prefer the local currency (e.g. CNY, JPY, EUR, GBP) and consistent units (ideally millions, but check if preferred_unit is specified in the company metadata).\n"
        "7. Sign standardization: Ensure the extracted statement structure and numbers are formatted so that any number that subtracts from the revenue is an expense (expressed as negative), and any number that increases profit (such as interest income) is expressed as positive. Note that ambiguous items like net interest income may be positive or negative depending on context."
    )

    from src.core.exceptions import LLMError

    quality_errors = []

    # Define tools as inner functions closed over document content
    def find_chunk(chunk_id: int) -> str:
        """Fetch the exact text content of a specific chunk by its ID."""
        chunk_str = get_chunk_by_id(content, int(chunk_id))
        if not chunk_str:
            return f"Chunk {chunk_id} not found or empty."
        return chunk_str

    def keyword_search(keywords: list, window: int = 200) -> str:
        """Search the document content for occurrences of keywords within a window of characters."""
        return str(find_keyword_contexts(content, keywords, window))

    def check_income_statement_quality(markdown_content: str) -> str:
        """Perform a robust quality check on the current income statement markdown table using the LLM auditor."""
        res = check_income_statement_quality_helper(
            markdown_content, client, is_quarterly=is_quarterly
        )
        if res != "PASSED":
            logger.warning(f"Income Statement quality check warning/failure: {res}")
            quality_errors.append(res)
        return res

    def finalize(raw_income_statement_markdown: str, currency: str, unit: str) -> str:
        """Finalize the income statement extraction, providing the raw markdown table, detected currency (e.g. 'USD', 'CNY') and unit (e.g. 'Millions')."""
        return "Income Statement extraction finalized."

    tools = [find_chunk, keyword_search, check_income_statement_quality, finalize]

    try:
        finalized_args, history = run_agent_loop(
            client=client,
            system_prompt=system_prompt,
            initial_prompt=initial_prompt,
            tools=tools,
            max_turns=max_turns,
        )
    except LLMError as e:
        if quality_errors:
            raise LLMError(
                f"Agent failed to finalize execution. Quality audit failures: {quality_errors}"
            ) from e
        raise e

    if not finalized_args:
        finalized_args = {}

    return IncomeStatementExtraction(
        raw_income_statement_markdown=finalized_args.get(
            "raw_income_statement_markdown", ""
        ),
        currency=finalized_args.get("currency", "USD"),
        unit=finalized_args.get("unit", "Millions"),
    )
