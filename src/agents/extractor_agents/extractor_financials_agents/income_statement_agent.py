import logging
from pathlib import Path

from src.tools.keyword_search import (
    find_keyword_contexts as orchestrator_find_keyword_contexts,
)
from src.tools.find_chunk import get_chunk_by_id as orchestrator_get_chunk
from src.utils.tools import (
    append_markdown as orchestrator_append_markdown,
    edit_markdown as orchestrator_edit_markdown,
    validate_markdown_table_syntax,
)
from src.agents.agent_executor import run_agent_loop

logger = logging.getLogger(__name__)


def check_income_statement_quality_helper(
    filepath: str, extractor, is_quarterly: bool = True
) -> str:
    path = Path(filepath)
    if not path.exists():
        return "Error: File does not exist."
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    # Programmatic check for markdown table formatting syntax
    syntax_error = validate_markdown_table_syntax(content)
    if syntax_error:
        return syntax_error

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
    prompt = f'Income Statement Markdown:\n"""\n{content}\n"""'
    try:
        res = extractor.llm.generate(prompt, system_prompt=sys_prompt).strip()
        return res
    except Exception as e:
        return f"Quality check failed with exception: {e}"


def run_income_statement_agent(
    file_path: Path,
    content: str,
    sorted_chunk_ids: list,
    extractor,
    target_output_path: Path,
    is_quarterly: bool = True,
) -> None:
    # Initialize target output file
    target_output_path.parent.mkdir(parents=True, exist_ok=True)
    target_output_path.write_text("# Extracted Income Statement\n\n", encoding="utf-8")

    # Load extraction learnings
    learning_context = extractor.get_extract_context()

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )

    initial_prompt = (
        f"Starting extraction for source file: '{file_path.name}'.\n"
        f"Target output path: '{target_output_path.as_posix()}'\n"
        f"Available chunk IDs: {sorted_chunk_ids}\n"
        f"Note: The chunk IDs are sorted in descending order of number frequency (digit count). "
        f"The chunks containing financial tables are highly likely to be near the beginning of this list.\n\n"
        f"To locate where the statement is, please call `find_keyword_contexts` "
        f"(hint: try searching for keywords like 'revenue', 'profit', or 'tax'), "
        f"then fetch the content with `get_chunk_by_id`."
    )

    if learning_context:
        initial_prompt += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learning_context}\n"""'

    system_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the Income Statement Agent. Your task is to locate and extract the COMPLETE Income Statement.\n"
        f"Specifically, we are focused on the {focus_period} time period. Ensure you extract the statement for this focused period.\n"
        "Rules:\n"
        "1. You start with only file name and chunk IDs. You must find relevant chunks using keywords first.\n"
        "2. Fetch chunk content using get_chunk_by_id.\n"
        "3. Append statements to the output file using append_markdown. The statement MUST be written as a valid, well-formed markdown table. Ensure that the table has a header row, followed immediately by a separator row (e.g., '| --- | --- | ...'), and all subsequent rows have the exact same number of columns.\n"
        "4. Always call check_income_statement_quality before finalizing. If it returns errors (including markdown table syntax formatting errors), use edit_markdown to fix them.\n"
        "5. When everything is correct and quality check passes, call the tool 'finalize' to exit, providing the detected/preferred currency (e.g. 'JPY' or 'EUR') and unit (e.g. 'Millions', 'Billions', '10K') as arguments.\n"
        "6. Sign standardization: Ensure the extracted statement structure and numbers are formatted so that any number that subtracts from the revenue is an expense (expressed as negative), and any number that increases profit (such as interest income) is expressed as positive. Access resources/dictionary/income_statement.md (if available) as a guide. Note that ambiguous items like net interest income may be positive or negative depending on context.\n"
        "7. Currency & Unit detection: Identify the reporting currency and unit of the financial statements in the document. Prefer the local currency (e.g. CNY, JPY, EUR, GBP) and consistent units (ideally millions, but check if `Preferred Currency & Unit` is specified in the learning context). You MUST write `**Currency**: <Currency>` and `**Unit**: <Unit>` on separate lines at the very top of the output file (using append_markdown/edit_markdown) before any table or content. Ensure all extracted numerical values in your table match this currency and unit."
    )

    # Define tools as inner functions
    def find_keyword_contexts(keywords: list, window: int = 200) -> str:
        """Search the document content for occurrences of keywords within a window of characters."""
        return str(orchestrator_find_keyword_contexts(content, keywords, window))

    def get_chunk_by_id(chunk_id: int) -> str:
        """Fetch the exact text content of a specific chunk by its ID."""
        chunk_str = orchestrator_get_chunk(content, int(chunk_id))
        if not chunk_str:
            return f"Chunk {chunk_id} not found or empty."
        return chunk_str

    def append_markdown(text: str) -> str:
        """Append a markdown text segment or table to the income statement output file."""
        return orchestrator_append_markdown(target_output_path.as_posix(), text)

    def edit_markdown(target_text: str, replacement_text: str) -> str:
        """Replace target_text with replacement_text in the output file to fix formatting errors."""
        return orchestrator_edit_markdown(
            target_output_path.as_posix(), target_text, replacement_text
        )

    def check_income_statement_quality() -> str:
        """Run a quality check on the currently extracted income statement to verify mathematical consistency and formatting."""
        return check_income_statement_quality_helper(
            target_output_path.as_posix(), extractor, is_quarterly=is_quarterly
        )

    def finalize(currency: str, unit: str) -> str:
        """Finalize the income statement extraction, specifying the detected currency (e.g. 'USD', 'CNY') and unit (e.g. 'Millions')."""
        return "Income Statement extraction finalized."

    tools = [
        find_keyword_contexts,
        get_chunk_by_id,
        append_markdown,
        edit_markdown,
        check_income_statement_quality,
        finalize,
    ]

    finalized_args, history = run_agent_loop(
        client=extractor.llm,
        system_prompt=system_prompt,
        initial_prompt=initial_prompt,
        tools=tools,
        max_turns=10,
    )

    # After the loop finishes, run curation
    try:
        from src.agents.curator_agent import CuratorAgent

        ticker = extractor.settings.active_ticker or "UNK"
        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(extractor.settings)
        curator.curate_agent(ticker, "income_statement", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for agent Income Statement: {e}")
