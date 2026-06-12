import re
import json
import logging
from pathlib import Path

from src.utils.tools import find_keyword_contexts, append_markdown, edit_markdown

logger = logging.getLogger(__name__)


def run_extraction_agent(
    agent_name: str,
    system_prompt: str,
    file_path: Path,
    target_output_path: Path,
    extractor,
    content: str,
    sorted_chunk_ids: list,
    is_quarterly: bool = True,
) -> None:
    # Initialize target output file
    target_output_path.parent.mkdir(parents=True, exist_ok=True)
    target_output_path.write_text(f"# Extracted {agent_name}\n\n", encoding="utf-8")

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
        f"You are the {agent_name} Agent. Your goal is to extract the complete statement and save it to the target file. "
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
                f"Agent {agent_name} failed to generate response at turn {turn}: {e}"
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
            logger.info(f"Agent {agent_name} finalized extraction successfully.")
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
        elif tool == "check_income_statement_quality":
            from src.pipeline.extractor_agents.extractor_financials_agents.income_statement_agent import (
                check_income_statement_quality,
            )

            result = check_income_statement_quality(
                target_output_path.as_posix(), extractor, is_quarterly=is_quarterly
            )
        elif tool == "check_balance_sheet_quality":
            from src.pipeline.extractor_agents.extractor_financials_agents.balance_sheet_agent import (
                check_balance_sheet_quality,
            )

            result = check_balance_sheet_quality(
                target_output_path.as_posix(), extractor, is_quarterly=is_quarterly
            )
        else:
            result = f"Error: Unknown tool '{tool}'."

        history.append(
            {"role": "user", "content": f"Observation from {tool}:\n{result}"}
        )


def parse_markdown_to_line_items(
    file_path: Path,
    target_statement_path: Path,
    extractor,
    category_default: str,
) -> list:
    from src.pipeline.extractor_orchestrator import LineItem, AuditLinkage, clean_val

    if not target_statement_path.exists():
        return []

    content = target_statement_path.read_text(encoding="utf-8")

    dict_guidance = ""
    if category_default == "income_statement":
        is_dict_path = Path("src/resources/dictionary/income_statement.md")
        if is_dict_path.exists():
            dict_guidance = f"\n\nUse the following Income Statement Dictionary as a guide for classifications and expense/revenue sign mapping:\n{is_dict_path.read_text(encoding='utf-8')}\n"

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. "
        "Extract all financial statement line items from the provided markdown statement. "
        "For every line item, record the exact_snippet (exact text match from the markdown statement) for audit trial. "
        "Ensure you extract standard items: revenue, operating income, cash_and_equivalents, debt, etc."
    )
    if category_default == "income_statement":
        sys_prompt += (
            "\n\nStandardize positive/negative signs for the Income Statement:\n"
            "- Any number that subtracts from the revenue is an expense, cost, or loss, and MUST be expressed as a negative number.\n"
            "- Any number that effectively increases profit (e.g. revenue, interest income, tax benefits, gains) MUST be expressed as a positive number.\n"
            "- If an item is an expense but listed as a positive number in the source markdown, you MUST convert it to a negative number.\n"
            "- Be careful with ambiguous items like 'Net Interest Income' or 'Other Income/Expense Net'. Check their context: if they represent a net expense or loss, express them as negative. If they represent net income or gain, express them as positive."
        )

    prompt = f"""
Markdown statement content:
\"\"\"
{content}
\"\"\"
{dict_guidance}
Extract all financial statement line items (Line Name, Value, Category (current_assets | current_liabilities | noncurrent_assets | noncurrent_liabilities | income_statement | other), exact_snippet).
Return a valid JSON object matching this structure:
{{
  "line_items": [
     {{
       "line_name": "Cash and cash equivalents",
       "value": "12,345",
       "category": "{category_default}",
       "exact_snippet": "Cash and cash equivalents $ 12,345"
     }}
  ]
}}
"""
    extracted_items = []
    try:
        resp = extractor.llm.generate(
            prompt, system_prompt=sys_prompt, stream_thinking=True
        )
        json_match = re.search(r"\{.*\}", resp, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            for item in data.get("line_items", []):
                val_float = clean_val(str(item.get("value", "0")))
                if val_float == 0.0 and str(item.get("value")) not in ["0", "0.0"]:
                    continue
                line_item = LineItem(
                    line_name=item.get("line_name"),
                    value=val_float,
                    category=item.get("category", "other"),
                    audit=AuditLinkage(
                        source_file=file_path.name,
                        chunk_id=0,  # Consolidated from agent-derived markdown
                        exact_snippet=item.get("exact_snippet", ""),
                    ),
                )
                extracted_items.append(line_item)
    except Exception as e:
        logger.error(
            f"Failed to parse line items from markdown statement {target_statement_path.name}: {e}"
        )

    return extracted_items
