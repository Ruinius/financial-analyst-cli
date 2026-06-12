from pathlib import Path

from src.pipeline.extractor_agents.extractor_financials_agents.agent_runner import (
    run_extraction_agent,
)


def check_balance_sheet_quality(
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
    from src.utils.tools import validate_markdown_table_syntax

    syntax_error = validate_markdown_table_syntax(content)
    if syntax_error:
        return syntax_error

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    sys_prompt = (
        "You are a senior financial auditor. Perform a quality check on the following extracted Balance Sheet. "
        f"Verify that we are focused on the {focus_period} time period. "
        "Verify that Assets = Liabilities + Equity. Return 'PASSED' if everything is correct. "
        "If there are missing fields, incorrect values, or mathematical inconsistencies (like total assets not matching total liabilities + equity), "
        "return a list of specific errors so the agent can edit the file."
    )
    prompt = f'Balance Sheet Markdown:\n"""\n{content}\n"""'
    try:
        res = extractor.llm.generate(prompt, system_prompt=sys_prompt).strip()
        return res
    except Exception as e:
        return f"Quality check failed with exception: {e}"


def run_balance_sheet_agent(
    file_path: Path,
    content: str,
    sorted_chunk_ids: list,
    extractor,
    target_output_path: Path,
    is_quarterly: bool = True,
) -> None:
    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    system_prompt_bs = (
        "You are Sir Pennyworth, a senior financial analyst. Your task is to locate and extract the COMPLETE Balance Sheet from the financial filing.\n"
        f"Specifically, we are focused on the {focus_period} time period. Ensure you extract the Balance Sheet for this focused period (e.g. the end of this period).\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int}\n"
        "- 'get_chunk_by_id': arguments: {'chunk_id': int}\n"
        "- 'append_markdown': arguments: {'text': str}\n"
        "- 'edit_markdown': arguments: {'target_text': str, 'replacement_text': str}\n"
        "- 'check_balance_sheet_quality': arguments: {}\n"
        "- 'finalize': arguments: {}\n\n"
        "Example format:\n"
        "{\n"
        '  "thought": "First, I need to search for keywords related to the balance sheet to find relevant chunks.",\n'
        '  "tool": "find_keyword_contexts",\n'
        '  "arguments": {"keywords": ["Balance Sheet", "Financial Position"]}\n'
        "}\n\n"
        "Rules:\n"
        "1. You start with only file name and chunk IDs. You must find relevant chunks using keywords first.\n"
        "2. Fetch chunk content using get_chunk_by_id.\n"
        "3. Append statements to the output file using append_markdown. The statement MUST be written as a valid, well-formed markdown table. Ensure that the table has a header row, followed immediately by a separator row (e.g., '| --- | --- | ...'), and all subsequent rows have the exact same number of columns.\n"
        "4. Always call check_balance_sheet_quality before finalizing. If it returns errors (including markdown table syntax formatting errors), use edit_markdown to fix them.\n"
        "5. When everything is correct and quality check passes, call the tool 'finalize' to exit."
    )
    run_extraction_agent(
        agent_name="Balance Sheet",
        system_prompt=system_prompt_bs,
        file_path=file_path,
        target_output_path=target_output_path,
        extractor=extractor,
        content=content,
        sorted_chunk_ids=sorted_chunk_ids,
        is_quarterly=is_quarterly,
    )
