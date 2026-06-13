import re
import json
import logging
from pathlib import Path

from src.utils.tools import (
    find_keyword_contexts,
    append_markdown,
    edit_markdown,
    validate_markdown_table_syntax,
)

logger = logging.getLogger(__name__)


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
    # Initialize target output file
    target_output_path.parent.mkdir(parents=True, exist_ok=True)
    target_output_path.write_text("# Extracted Balance Sheet\n\n", encoding="utf-8")

    # Load extraction learnings
    learning_context = ""
    ticker = extractor.settings.active_ticker
    if ticker:
        learning_path = (
            Path(extractor.settings.active_workspace_path)
            / f"{ticker}_extract_learning.md"
        )
        if learning_path.exists():
            try:
                learning_context = learning_path.read_text(encoding="utf-8")
            except Exception:
                pass

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    history = []
    initial_prompt = (
        f"You are the Balance Sheet Agent. Your goal is to extract the complete statement and save it to the target file. "
        f"The source file name is '{file_path.name}'. The document is split into chunks with IDs: {sorted_chunk_ids}.\n"
        f"Note: The chunk IDs are sorted in descending order of number frequency (digit count). "
        f"Since financial statements (tables) contain many digits, the chunks containing financial statements "
        f"are highly likely to be near the beginning of this list.\n\n"
        f"IMPORTANT: We are focused on the {focus_period} time period. Please locate and extract the data specifically corresponding to this focused period.\n\n"
        f"You do not have the document content in your initial context. You MUST first call the tool `find_keyword_contexts` "
        f"to locate where the statement is, and then call `get_chunk_by_id` to inspect the contents. "
        f"Target output path to write to: '{target_output_path.as_posix()}'.\n"
        f"Once you write/append the content and verify its quality using the quality check tool, call the `finalize` tool to complete."
    )

    if learning_context:
        initial_prompt += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learning_context}\n"""'

    history.append({"role": "user", "content": initial_prompt})

    system_prompt = (
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

    max_turns = 10
    for turn in range(max_turns):
        prompt = ""
        for h in history:
            prompt += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        try:
            resp = extractor.llm.generate(
                prompt, system_prompt=system_prompt, stream_thinking=True
            ).strip()
        except Exception as e:
            logger.exception(
                f"Agent Balance Sheet failed to generate response at turn {turn}: {e}"
            )
            break

        history.append({"role": "assistant", "content": resp})

        # Try to parse JSON tool call from assistant response
        json_match = re.search(r"\{.*\}", resp, re.DOTALL)
        if not json_match:
            history.append(
                {
                    "role": "user",
                    "content": "Error: Your response did not contain a valid JSON tool call. Please respond using the specified JSON schema.",
                }
            )
            continue

        try:
            action = json.loads(json_match.group(0))
        except Exception as e:
            history.append(
                {
                    "role": "user",
                    "content": f"Error: Failed to parse JSON tool call: {e}. Please respond using a valid JSON schema.",
                }
            )
            continue

        tool = action.get("tool")
        args = action.get("arguments", {})

        if tool == "finalize":
            logger.info("Agent Balance Sheet finalized extraction successfully.")
            break

        # Execute tool
        result = ""
        if tool == "find_keyword_contexts":
            keywords = args.get("keywords", [])
            window = args.get("window", 200)
            result = str(find_keyword_contexts(content, keywords, window))
        elif tool == "get_chunk_by_id":
            try:
                chunk_id = int(args.get("chunk_id", 0))
                from src.pipeline.extractor_orchestrator import (
                    get_chunk_by_id as orchestrator_get_chunk,
                )

                result = orchestrator_get_chunk(content, chunk_id)
                if not result:
                    result = f"Chunk {chunk_id} not found or empty."
            except Exception as e:
                result = f"Error: {e}"
        elif tool == "append_markdown":
            result = append_markdown(
                target_output_path.as_posix(), args.get("text", "")
            )
        elif tool == "edit_markdown":
            result = edit_markdown(
                target_output_path.as_posix(),
                args.get("target_text", ""),
                args.get("replacement_text", ""),
            )
        elif tool == "check_balance_sheet_quality":
            result = check_balance_sheet_quality(
                target_output_path.as_posix(), extractor, is_quarterly=is_quarterly
            )
        else:
            result = f"Error: Unknown tool '{tool}'."

        history.append(
            {"role": "user", "content": f"Observation from {tool}:\n{result}"}
        )

    # After the loop finishes:
    try:
        from src.pipeline.curator_agent import CuratorAgent

        ticker = extractor.settings.active_ticker or "UNK"
        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(extractor.settings)
        curator.curate_agent(ticker, "balance_sheet", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for agent Balance Sheet: {e}")
