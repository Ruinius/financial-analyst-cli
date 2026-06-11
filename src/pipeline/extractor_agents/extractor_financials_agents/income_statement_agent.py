from pathlib import Path

from src.pipeline.extractor_agents.extractor_financials_agents.agent_runner import (
    run_extraction_agent,
)


def check_income_statement_quality(filepath: str, extractor) -> str:
    path = Path(filepath)
    if not path.exists():
        return "Error: File does not exist."
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    # Programmatic check for markdown table formatting syntax
    from src.utils.tools import validate_markdown_table_syntax

    syntax_error = validate_markdown_table_syntax(content)
    if syntax_error:
        return syntax_error

    sys_prompt = (
        "You are a senior financial auditor. Perform a quality check on the following extracted Income Statement. "
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
) -> None:
    system_prompt_is = (
        "You are Sir Pennyworth, a senior financial analyst. Your task is to locate and extract the COMPLETE Income Statement from the financial filing.\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int}\n"
        "- 'get_chunk_by_id': arguments: {'chunk_id': int}\n"
        "- 'append_markdown': arguments: {'text': str}\n"
        "- 'edit_markdown': arguments: {'target_text': str, 'replacement_text': str}\n"
        "- 'check_income_statement_quality': arguments: {}\n"
        "- 'finalize': arguments: {}\n\n"
        "Example format:\n"
        "{\n"
        '  "thought": "First, I need to search for keywords related to the income statement to find relevant chunks.",\n'
        '  "tool": "find_keyword_contexts",\n'
        '  "arguments": {"keywords": ["Income Statement", "Operations", "Earnings"]}\n'
        "}\n\n"
        "Rules:\n"
        "1. You start with only file name and chunk IDs. You must find relevant chunks using keywords first.\n"
        "2. Fetch chunk content using get_chunk_by_id.\n"
        "3. Append statements to the output file using append_markdown. The statement MUST be written as a valid, well-formed markdown table. Ensure that the table has a header row, followed immediately by a separator row (e.g., '| --- | --- | ...'), and all subsequent rows have the exact same number of columns.\n"
        "4. Always call check_income_statement_quality before finalizing. If it returns errors (including markdown table syntax formatting errors), use edit_markdown to fix them.\n"
        "5. When everything is correct and quality check passes, call the tool 'finalize' to exit.\n"
        "6. Sign standardization: Ensure the extracted statement structure and numbers are formatted so that any number that subtracts from the revenue is an expense (expressed as negative), and any number that increases profit (such as interest income) is expressed as positive. Access resources/dictionary/income_statement.md (if available) as a guide. Note that ambiguous items like net interest income may be positive or negative depending on context."
    )
    run_extraction_agent(
        agent_name="Income Statement",
        system_prompt=system_prompt_is,
        file_path=file_path,
        target_output_path=target_output_path,
        extractor=extractor,
        content=content,
        sorted_chunk_ids=sorted_chunk_ids,
    )
