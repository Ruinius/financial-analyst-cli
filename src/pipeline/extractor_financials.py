import re
import logging
from pathlib import Path
import src.rust_core as rust_core

from src.utils.tools import find_keyword_contexts, append_markdown, edit_markdown

# Defer imports of schemas and helper functions to avoid circular import issues
# or import directly since they will be defined in extractor_orchestrator

logger = logging.getLogger(__name__)


def check_income_statement_quality(filepath: str, extractor) -> str:
    path = Path(filepath)
    if not path.exists():
        return "Error: File does not exist."
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

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


def check_balance_sheet_quality(filepath: str, extractor) -> str:
    path = Path(filepath)
    if not path.exists():
        return "Error: File does not exist."
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    sys_prompt = (
        "You are a senior financial auditor. Perform a quality check on the following extracted Balance Sheet. "
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


def run_extraction_agent(
    agent_name: str,
    system_prompt: str,
    file_path: Path,
    target_output_path: Path,
    extractor,
    content: str,
    sorted_chunk_ids: list,
) -> None:
    import json
    import re

    # Initialize target output file
    target_output_path.parent.mkdir(parents=True, exist_ok=True)
    target_output_path.write_text(f"# Extracted {agent_name}\n\n", encoding="utf-8")

    history = []
    initial_prompt = (
        f"You are the {agent_name} Agent. Your goal is to extract the complete statement and save it to the target file. "
        f"The source file name is '{file_path.name}'. The document is split into chunks with IDs: {sorted_chunk_ids}.\n\n"
        f"You do not have the document content in your initial context. You MUST first call the tool `find_keyword_contexts` "
        f"to locate where the statement is, and then call `get_chunk_by_id` to inspect the contents. "
        f"Target output path to write to: '{target_output_path.as_posix()}'.\n"
        f"Once you write/append the content and verify its quality using the quality check tool, call the `finalize` tool to complete."
    )

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
            result = check_income_statement_quality(
                target_output_path.as_posix(), extractor
            )
        elif tool == "check_balance_sheet_quality":
            result = check_balance_sheet_quality(
                target_output_path.as_posix(), extractor
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
    import json
    import re
    from src.pipeline.extractor_orchestrator import LineItem, AuditLinkage, clean_val

    if not target_statement_path.exists():
        return []

    content = target_statement_path.read_text(encoding="utf-8")

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. "
        "Extract all financial statement line items from the provided markdown statement. "
        "For every line item, record the exact_snippet (exact text match from the markdown statement) for audit trial. "
        "Ensure you extract standard items: revenue, operating income, cash_and_equivalents, debt, etc."
    )
    prompt = f"""
Markdown statement content:
\"\"\"
{content}
\"\"\"

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


def extract_financial_statements(
    file_path: Path,
    content: str,
    sorted_chunk_ids: list,
    extractor,
    summaries: list,
) -> list:
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    extracted_dir.mkdir(parents=True, exist_ok=True)

    is_path = extracted_dir / f"{file_path.stem}_income_statement.md"
    bs_path = extracted_dir / f"{file_path.stem}_balance_sheet.md"

    # Income Statement Agent
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
        "3. Append statements to the output file using append_markdown.\n"
        "4. Always call check_income_statement_quality before finalizing. If it returns errors, use edit_markdown to fix them.\n"
        "5. When everything is correct and quality check passes, call the tool 'finalize' to exit."
    )
    run_extraction_agent(
        agent_name="Income Statement",
        system_prompt=system_prompt_is,
        file_path=file_path,
        target_output_path=is_path,
        extractor=extractor,
        content=content,
        sorted_chunk_ids=sorted_chunk_ids,
    )

    # Balance Sheet Agent
    system_prompt_bs = (
        "You are Sir Pennyworth, a senior financial analyst. Your task is to locate and extract the COMPLETE Balance Sheet from the financial filing.\n"
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
        "3. Append statements to the output file using append_markdown.\n"
        "4. Always call check_balance_sheet_quality before finalizing. If it returns errors, use edit_markdown to fix them.\n"
        "5. When everything is correct and quality check passes, call the tool 'finalize' to exit."
    )
    run_extraction_agent(
        agent_name="Balance Sheet",
        system_prompt=system_prompt_bs,
        file_path=file_path,
        target_output_path=bs_path,
        extractor=extractor,
        content=content,
        sorted_chunk_ids=sorted_chunk_ids,
    )

    # Parse and consolidate line items
    is_items = parse_markdown_to_line_items(
        file_path, is_path, extractor, "income_statement"
    )
    bs_items = parse_markdown_to_line_items(
        file_path, bs_path, extractor, "current_assets"
    )

    # Add summaries update
    summaries.append(
        f"- **Agentic Extraction Completed**: Income Statement generated at `{is_path.name}`, Balance Sheet generated at `{bs_path.name}`."
    )

    return is_items + bs_items


def run_diluted_shares_agent(
    content: str, extractor, income_statement_content: str = ""
) -> tuple[float, float]:
    import json
    import re
    from src.pipeline.extractor_orchestrator import clean_val

    basic_shares = 0.0
    diluted_shares = 0.0

    sys_prompt = (
        "You are Sir Pennyworth, a precise financial analyst. Your goal is to find the exact basic and diluted shares outstanding in the document.\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int}\n"
        "- 'finalize': arguments: {'basic_shares': str, 'diluted_shares': str}\n\n"
        "Example format:\n"
        "{\n"
        '  "thought": "I will search for keyword contexts to locate shares outstanding.",\n'
        '  "tool": "find_keyword_contexts",\n'
        '  "arguments": {"keywords": ["shares outstanding", "weighted average shares"]}\n'
        "}\n\n"
        "Rules:\n"
        "1. You have a maximum of 4 turns. Search for keyword contexts first.\n"
        "2. When you find the values, call 'finalize' with the basic and diluted shares."
    )

    user_content = "Start searching for basic and diluted shares outstanding. Remember, you have up to 4 turns."
    if income_statement_content:
        user_content += f'\n\nHere is the already extracted Income Statement for your reference:\n"""\n{income_statement_content}\n"""'

    history = [
        {
            "role": "user",
            "content": user_content,
        }
    ]

    for turn in range(4):
        if turn == 3:
            # We are on the last turn, append a strict instruction to finalize
            history[-1]["content"] += (
                "\n\nCRITICAL: This is your final turn (turn 4 of 4). You must call the 'finalize' tool immediately with your current best estimates. Do not call find_keyword_contexts again."
            )

        prompt = ""
        for h in history:
            prompt += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"
        try:
            resp = extractor.llm.generate(prompt, system_prompt=sys_prompt).strip()
        except Exception as e:
            logger.error(f"Diluted Shares Agent failed at turn {turn}: {e}")
            break

        history.append({"role": "assistant", "content": resp})

        json_match = re.search(r"\{.*\}", resp, re.DOTALL)
        if not json_match:
            history.append(
                {
                    "role": "user",
                    "content": "Error: Your response did not contain a valid JSON tool call.",
                }
            )
            continue
        try:
            action = json.loads(json_match.group(0))
        except Exception as e:
            history.append({"role": "user", "content": f"Error parsing JSON: {e}"})
            continue

        tool = action.get("tool")
        args = action.get("arguments", {})

        if tool == "finalize":
            basic_shares = clean_val(str(args.get("basic_shares", "0")))
            diluted_shares = clean_val(str(args.get("diluted_shares", "0")))
            break
        elif tool == "find_keyword_contexts":
            kw = args.get("keywords", [])
            window = args.get("window", 200)
            res = str(find_keyword_contexts(content, kw, window))
            history.append(
                {
                    "role": "user",
                    "content": f"Observation from find_keyword_contexts:\n{res[:4000]}",
                }
            )
        else:
            history.append({"role": "user", "content": f"Error: Unknown tool {tool}"})

    return basic_shares, diluted_shares


def run_organic_growth_agent(
    content: str, revenue: float, extractor, income_statement_content: str = ""
) -> tuple[float, float]:
    import json
    import re
    from src.pipeline.extractor_orchestrator import clean_val

    simple_growth = 0.0
    organic_growth = 0.0

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. Your goal is to determine the simple revenue growth and organic revenue growth.\n"
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int}\n"
        "- 'finalize': arguments: {'simple_growth': str, 'organic_growth': str}\n\n"
        "Rules:\n"
        "1. Search the document for organic growth, constant currency adjustments, acquisitions, and revenue growth using find_keyword_contexts.\n"
        "2. If organic growth or constant currency growth is explicitly reported, extract it. Check if there are M&A contributions that should be backed out.\n"
        "3. If organic growth is NOT explicitly reported, compute it: e.g. Organic Growth = Constant Currency Growth (if reported, otherwise simple growth) - (Acquisition revenue / Total revenue).\n"
        "4. Call 'finalize' with your final extracted/calculated growth percentages."
    )

    user_content = f"Find simple and organic revenue growth. The reported revenue is {revenue}. You have up to 4 turns."
    if income_statement_content:
        user_content += f'\n\nHere is the already extracted Income Statement for your reference:\n"""\n{income_statement_content}\n"""'

    history = [
        {
            "role": "user",
            "content": user_content,
        }
    ]

    for turn in range(4):
        if turn == 3:
            # We are on the last turn, append a strict instruction to finalize
            history[-1]["content"] += (
                "\n\nCRITICAL: This is your final turn (turn 4 of 4). You must call the 'finalize' tool immediately with your current best estimates. Do not call find_keyword_contexts again."
            )

        prompt = ""
        for h in history:
            prompt += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"
        try:
            resp = extractor.llm.generate(prompt, system_prompt=sys_prompt).strip()
        except Exception as e:
            logger.error(f"Organic Growth Agent failed at turn {turn}: {e}")
            break

        history.append({"role": "assistant", "content": resp})

        json_match = re.search(r"\{.*\}", resp, re.DOTALL)
        if not json_match:
            history.append(
                {
                    "role": "user",
                    "content": "Error: Your response did not contain a valid JSON tool call.",
                }
            )
            continue
        try:
            action = json.loads(json_match.group(0))
        except Exception as e:
            history.append({"role": "user", "content": f"Error parsing JSON: {e}"})
            continue

        tool = action.get("tool")
        args = action.get("arguments", {})

        if tool == "finalize":

            def clean_growth_val(val: str) -> float:
                parsed = clean_val(val)
                if abs(parsed) > 1.0:
                    parsed /= 100.0
                return parsed

            simple_growth = clean_growth_val(str(args.get("simple_growth", "0")))
            organic_growth = clean_growth_val(str(args.get("organic_growth", "0")))
            break
        elif tool == "find_keyword_contexts":
            kw = args.get("keywords", [])
            window = args.get("window", 200)
            res = str(find_keyword_contexts(content, kw, window))
            history.append(
                {
                    "role": "user",
                    "content": f"Observation from find_keyword_contexts:\n{res[:4000]}",
                }
            )
        else:
            history.append({"role": "user", "content": f"Error: Unknown tool {tool}"})

    if organic_growth == 0.0 and simple_growth != 0.0:
        organic_growth = simple_growth
    return simple_growth, organic_growth


def run_interpretation_agent(
    extracted_line_items: list,
    file_path: Path,
    extractor,
) -> list:
    import json
    import re
    from src.pipeline.extractor_orchestrator import LineItem, AuditLinkage

    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    is_path = extracted_dir / f"{file_path.stem}_income_statement.md"
    bs_path = extracted_dir / f"{file_path.stem}_balance_sheet.md"

    is_md = is_path.read_text(encoding="utf-8") if is_path.exists() else ""
    bs_md = bs_path.read_text(encoding="utf-8") if bs_path.exists() else ""

    # Check local dictionary classifications to pass as guidance/override
    is_dict_path = Path("src/resources/dictionary/income_statement.md")
    bs_dict_path = Path("src/resources/dictionary/balance_sheet.md")
    local_dict_guidance = ""
    if is_dict_path.exists():
        local_dict_guidance += f"--- Income Statement Dictionary ---\n{is_dict_path.read_text(encoding='utf-8')}\n"
    if bs_dict_path.exists():
        local_dict_guidance += f"--- Balance Sheet Dictionary ---\n{bs_dict_path.read_text(encoding='utf-8')}\n"

    # Check company context classifications
    context_content = get_extract_context(extractor)
    company_context_guidance = {}
    if context_content:
        for item in extracted_line_items:
            rule_match = re.search(
                rf"-\s*{re.escape(item.line_name)}\s*:\s*(operating|non-operating)",
                context_content,
                re.IGNORECASE,
            )
            if rule_match:
                company_context_guidance[item.line_name] = (
                    rule_match.group(1).lower() == "operating"
                )

    # Serialize items for LLM
    items_data = []
    for item in extracted_line_items:
        items_data.append(
            {
                "line_name": item.line_name,
                "value": item.value,
                "category": item.category,
                "operating": item.operating,
                "calculated": item.calculated,
            }
        )

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial auditor and statement interpretation agent.\n"
        "Your task is to analyze the raw financial statements and classify/verify all extracted line items.\n"
        "Specifically, you must:\n"
        "1. Identify whether each line item is a raw transaction/primitive line or a subtotal/total ('calculated' = true/false).\n"
        "   - 'calculated' = true indicates the line is a subtotal or total (e.g., Gross Profit, Operating Income, Total Assets).\n"
        "   - Sometimes subtotals/totals are explicitly called out as such (e.g., 'Total Assets', 'Subtotal'). Other times, they are not explicitly labeled and must be inferred based on the surrounding numbers, line items, mathematical relationships, indentation, or placement.\n"
        "2. Classify each item as operating (true) or non-operating (false). Respect the provided local dictionary or company context rules if they exist.\n"
        "   - Operating items (operating = true) represent activities central to the core business operations (e.g., Revenues, Cost of Sales, R&D, SG&A, operating leases).\n"
        "   - Non-operating items (operating = false) represent financing, investing, tax, or one-off activities not part of core operations (e.g., Interest Expense, Interest Income, investment gains/losses, tax provision, discontinued operations).\n"
        "   - This classification is used to calculate clean Operating EBITA and to isolate operating assets/liabilities for calculating Invested Capital and Return on Invested Capital (ROIC).\n"
        "3. Interpret any unnamed, generic (e.g. 'Other', 'Reconciliation adjustment') or ambiguous line items using their indentation, surrounding context, or placement.\n"
        "4. Perform cross-statement mathematical checks. Verify that subtotals match the sum of constituent line items (e.g. total assets = current assets + non-current assets; assets = liabilities + equity; net income = operating income + non-operating income - tax provision). If there are discrepancies, make adjustments or flag them.\n\n"
        "Return a valid JSON object with the key 'line_items' containing the updated/verified line items."
    )

    prompt = f"""
Income Statement Markdown:
\"\"\"
{is_md}
\"\"\"

Balance Sheet Markdown:
\"\"\"
{bs_md}
\"\"\"

Currently Extracted Line Items:
{json.dumps(items_data, indent=2)}

Local Dictionary Guidance:
{local_dict_guidance}

Company Context Rules:
{json.dumps(company_context_guidance, indent=2)}

Please review, verify, correct, and return the final list of verified line items in this structure:
{{
  "line_items": [
    {{
      "line_name": "Line Item Name",
      "value": 12345.0,
      "category": "current_assets | current_liabilities | noncurrent_assets | noncurrent_liabilities | income_statement | other",
      "operating": true/false,
      "calculated": true/false
    }}
  ]
}}
"""
    try:
        resp = extractor.llm.generate(
            prompt, system_prompt=sys_prompt, stream_thinking=True
        )
        json_match = re.search(r"\{.*\}", resp, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            updated_items = []
            # Match back to original line items to preserve audit trails
            for up_item in data.get("line_items", []):
                matching_orig = None
                for orig in extracted_line_items:
                    if orig.line_name.lower() == up_item.get("line_name", "").lower():
                        matching_orig = orig
                        break

                if matching_orig:
                    matching_orig.operating = up_item.get(
                        "operating", matching_orig.operating
                    )
                    matching_orig.calculated = up_item.get(
                        "calculated", matching_orig.calculated
                    )
                    matching_orig.category = up_item.get(
                        "category", matching_orig.category
                    )
                    matching_orig.value = up_item.get("value", matching_orig.value)
                    updated_items.append(matching_orig)
                    update_extract_context(extractor, matching_orig)
                else:
                    new_item = LineItem(
                        line_name=up_item.get("line_name"),
                        value=up_item.get("value", 0.0),
                        operating=up_item.get("operating", True),
                        calculated=up_item.get("calculated", False),
                        category=up_item.get("category", "other"),
                        audit=AuditLinkage(
                            source_file=file_path.name,
                            chunk_id=0,
                            exact_snippet="Agent-interpreted item",
                        ),
                    )
                    updated_items.append(new_item)
                    update_extract_context(extractor, new_item)
            return updated_items
    except Exception as e:
        logger.error(f"Interpretation agent failed: {e}. Falling back to default list.")

    return extracted_line_items


def run_ebita_and_tax_agent(
    content: str,
    extracted_line_items: list,
    extractor,
    income_statement_content: str = "",
) -> tuple[float, float, list, list]:
    import json
    import re

    operating_income = 0.0
    for item in extracted_line_items:
        n = item.line_name.lower()
        if (
            "operating_income" in n or "operating income" in n or "ebit" in n
        ) and not item.calculated:
            operating_income = item.value
            break
    else:
        for item in extracted_line_items:
            n = item.line_name.lower()
            if "income before tax" in n or "income_before_taxes" in n:
                operating_income = item.value
                break

    reported_tax = 0.0
    income_before_taxes = 0.0
    net_income = 0.0
    for item in extracted_line_items:
        n = item.line_name.lower()
        if "provision" in n or "tax expense" in n or "tax provision" in n:
            reported_tax = item.value
        elif "income before tax" in n or "income_before_taxes" in n:
            income_before_taxes = item.value
        elif "net income" in n or "net_income" in n:
            net_income = item.value

    keywords = [
        "restructuring",
        "amortization",
        "impairment",
        "write-off",
        "non-recurring",
        "one-time",
        "tax benefit",
        "tax adjustment",
    ]
    snippets = find_keyword_contexts(content, keywords, window=250)
    snippets_text = "\n---\n".join(snippets)[:6000]

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst specializing in EBITA adjustments and tax provisions.\n"
        "Your task is to identify non-operating/non-recurring adjustments and non-recurring tax benefits from footnotes, "
        "and calculate adjusted tax rate.\n"
        "Rules:\n"
        "1. Identify any non-recurring adjustments (e.g. restructuring, asset impairments, amortization of intangibles).\n"
        "2. Back out the tax effect of non-operating adjustments at a statutory rate of 25% (21% federal, 4% state/local).\n"
        "3. Identify any non-recurring tax benefits/credits in the footnotes.\n"
        "4. Calculate clean Operating EBITA = Operating Income + Non-Operating/Non-recurring adjustments.\n"
        "5. Calculate Adjusted Taxes = Reported Tax + Tax effect of adjustments - non-recurring tax benefits.\n\n"
        "Please identify adjustments and return a JSON object with:\n"
        "{\n"
        '  "operating_ebita": 150.0,\n'
        '  "adjusted_taxes": 32.5,\n'
        '  "ebita_adjustments": [\n'
        '    {"name": "Amortization of acquired technology", "value": 44.0},\n'
        '    {"name": "Amortization of other acquired intangible assets", "value": 121.0}\n'
        "  ],\n"
        '  "tax_adjustments": [\n'
        '    {"name": "Tax effect of non-operating adjustments", "value": 41.25}\n'
        "  ]\n"
        "}"
    )

    prompt = f"""
Reported Operating Income: {operating_income}
Reported Income Before Taxes: {income_before_taxes}
Reported Tax Provision: {reported_tax}
Reported Net Income: {net_income}
"""
    if income_statement_content:
        prompt += (
            f'\nExtracted Income Statement:\n"""\n{income_statement_content}\n"""\n'
        )

    prompt += f"""
Footnote Snippets:
\"\"\"
{snippets_text}
\"\"\"

Please identify adjustments and return a JSON object with:
{{
  "operating_ebita": 150.0,
  "adjusted_taxes": 32.5,
  "ebita_adjustments": [
    {{"name": "Adjustment Name", "value": 12.3}}
  ],
  "tax_adjustments": [
    {{"name": "Adjustment Name", "value": 4.5}}
  ]
}}
"""
    try:
        resp = extractor.llm.generate(
            prompt, system_prompt=sys_prompt, stream_thinking=True
        )
        json_match = re.search(r"\{.*\}", resp, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            ebita = data.get("operating_ebita", operating_income)
            adj_taxes = data.get("adjusted_taxes", reported_tax)
            ebita_adjustments = data.get("ebita_adjustments", [])
            tax_adjustments = data.get("tax_adjustments", [])
            return ebita, adj_taxes, ebita_adjustments, tax_adjustments
    except Exception as e:
        logger.error(f"Operating EBITA / Tax Agent failed: {e}")

    ebita_adjustments = []
    for item in extracted_line_items:
        n = item.line_name.lower()
        if "amortization" in n or "depreciation" in n:
            ebita_adjustments.append({"name": item.line_name, "value": item.value})
        elif (
            item.category == "income_statement"
            and not item.operating
            and not item.calculated
        ):
            ebita_adjustments.append(
                {"name": f"Back out {item.line_name}", "value": -item.value}
            )

    non_operating_sum = sum(adj["value"] for adj in ebita_adjustments)
    ebita = operating_income + non_operating_sum
    tax_effect = non_operating_sum * 0.25
    adj_taxes = reported_tax + tax_effect
    tax_adjustments = []
    if tax_effect != 0.0:
        tax_adjustments.append(
            {
                "name": "Tax effect of adjustments (25% statutory rate)",
                "value": tax_effect,
            }
        )
    return ebita, adj_taxes, ebita_adjustments, tax_adjustments


def calculate_deterministic_metrics(
    file_path: Path,
    content: str,
    extracted_line_items: list,
    basic_shares: float,
    diluted_shares: float,
    simple_growth: float,
    organic_growth: float,
    extractor,
    summaries: list,
    income_statement_content: str = "",
) -> bool:
    # Check time period and multiplier
    metadata = extractor.get_document_metadata(file_path.name)
    doc_type = metadata.get("document_type", "")
    if not doc_type:
        from src.pipeline.extractor_orchestrator import get_chunk_by_id

        chunk_0 = get_chunk_by_id(content, 0) or content[:4000]
        meta_match = re.search(r"\|\s*Document Type\s*\|\s*([^|]+?)\s*\|", chunk_0)
        if meta_match:
            doc_type = meta_match.group(1).strip()

    is_quarterly = (
        "10-Q" in file_path.name
        or "10Q" in file_path.name
        or "earnings_announcement" in file_path.name
        or doc_type == "quarterly_filing"
        or doc_type == "earnings_announcement"
    )
    time_period = "Q" if is_quarterly else "FY"
    multiplier = 4.0 if time_period == "Q" else 1.0

    # Calculations
    revenue = 0.0
    for item in extracted_line_items:
        n = item.line_name.lower()
        if "revenue" in n or "sales" in n:
            revenue = item.value
            break

    # EBITA & Taxes via Agent
    ebita, adj_taxes, ebita_adjustments, tax_adjustments = run_ebita_and_tax_agent(
        content,
        extracted_line_items,
        extractor,
        income_statement_content=income_statement_content,
    )
    ebita_margin = (ebita / revenue) * 100.0 if revenue > 0.0 else 0.0

    # Starting Point (for display only)
    starting_val = 0.0
    starting_name = "Operating Income"
    for item in extracted_line_items:
        n = item.line_name.lower()
        if "operating_income" in n or "operating income" in n or "ebit" in n:
            starting_val = item.value
            break
    else:
        for item in extracted_line_items:
            n = item.line_name.lower()
            if "income before tax" in n or "income_before_taxes" in n:
                starting_val = item.value
                starting_name = "Income Before Taxes"
                break

    # Invested Capital
    oca_items = [
        item
        for item in extracted_line_items
        if item.category == "current_assets" and item.operating
    ]
    ocl_items = [
        item
        for item in extracted_line_items
        if item.category == "current_liabilities" and item.operating
    ]
    onca_items = [
        item
        for item in extracted_line_items
        if item.category == "noncurrent_assets" and item.operating
    ]
    oncl_items = [
        item
        for item in extracted_line_items
        if item.category == "noncurrent_liabilities" and item.operating
    ]

    oca = sum(item.value for item in oca_items)
    ocl = sum(item.value for item in ocl_items)
    onca = sum(item.value for item in onca_items)
    oncl = sum(item.value for item in oncl_items)

    ann_rev = revenue * multiplier
    nwc, nltoa, ic, turnover = rust_core.calculate_invested_capital(
        oca, ocl, onca, oncl, ann_rev
    )

    # Taxes
    income_before_taxes = starting_val
    income_tax_expense = 0.0
    for item in extracted_line_items:
        n = item.line_name.lower()
        if "income before tax" in n or "income_before_taxes" in n:
            income_before_taxes = item.value
        elif "tax provision" in n or "income tax provision" in n or "tax expense" in n:
            income_tax_expense = item.value

    # Compute effective rate using standard formula
    effective_rate = (
        -(income_tax_expense / income_before_taxes)
        if income_before_taxes != 0.0
        else 0.21
    )
    adjusted_rate = -(adj_taxes / ebita) if ebita != 0.0 else 0.0

    chosen_tax_rate = adjusted_rate if adjusted_rate != 0.0 else effective_rate
    nopat, annualized_nopat, roic = rust_core.calculate_roic(
        ebita, chosen_tax_rate, ic, multiplier
    )

    # Format output
    output_lines = []
    output_lines.append(f"# Extracted Financial Report: {file_path.name}\n")
    output_lines.append("## Chunk Summaries\n")
    output_lines.extend(summaries)
    output_lines.append("\n---\n")

    output_lines.append("## EBITA\n")
    output_lines.append("| Field | Value |")
    output_lines.append("|---|---|")
    output_lines.append(f"| Starting Point | {starting_name} |")
    output_lines.append(f"| Starting Value | {starting_val} |")
    output_lines.append(f"| EBITA | {ebita} |")
    output_lines.append(f"| EBITA Margin | {ebita_margin:.2f}% |")
    output_lines.append("\n### EBITA Reconciliation Bridge\n")
    output_lines.append("| Adjustment / Step | Value |")
    output_lines.append("|---|---|")
    output_lines.append(f"| {starting_name} | {starting_val} |")
    for adj in ebita_adjustments:
        name = adj.get("name", "Adjustment")
        val = adj.get("value", 0.0)
        sign = "+" if val >= 0 else ""
        output_lines.append(f"| {name} | {sign}{val} |")
    output_lines.append(f"| **EBITA** | **{ebita}** |")
    output_lines.append("\n---\n")

    output_lines.append("## Invested Capital\n")
    output_lines.append("| Field | Value |")
    output_lines.append("|---|---|")
    output_lines.append(f"| Net Working Capital | {nwc} |")
    output_lines.append(f"| Net Long-Term Operating Assets | {nltoa} |")
    output_lines.append(f"| Invested Capital | {ic} |")
    output_lines.append(f"| Capital Turnover | {turnover:.2f}x |")

    output_lines.append("\n### Invested Capital Components Breakdown\n")
    output_lines.append("#### Operating Current Assets (OCA)\n")
    output_lines.append("| Line Item | Value |")
    output_lines.append("|---|---|")
    for item in oca_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total OCA** | **{oca}** |")

    output_lines.append("\n#### Operating Current Liabilities (OCL)\n")
    output_lines.append("| Line Item | Value |")
    output_lines.append("|---|---|")
    for item in ocl_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total OCL** | **{ocl}** |")

    output_lines.append(
        f"\n**Net Working Capital (NWC) = OCA - OCL = {oca} - {ocl} = {nwc}**\n"
    )

    output_lines.append("\n#### Operating Non-Current Assets (ONCA)\n")
    output_lines.append("| Line Item | Value |")
    output_lines.append("|---|---|")
    for item in onca_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total ONCA** | **{onca}** |")

    output_lines.append("\n#### Operating Non-Current Liabilities (ONCL)\n")
    output_lines.append("| Line Item | Value |")
    output_lines.append("|---|---|")
    for item in oncl_items:
        output_lines.append(f"| {item.line_name} | {item.value} |")
    output_lines.append(f"| **Total ONCL** | **{oncl}** |")

    output_lines.append(
        f"\n**Net Long-Term Operating Assets (NLTOA) = ONCA - ONCL = {onca} - {oncl} = {nltoa}**\n"
    )
    output_lines.append(
        f"\n**Invested Capital = NWC + NLTOA = {nwc} + {nltoa} = {ic}**\n"
    )
    output_lines.append("\n---\n")

    output_lines.append("## Tax Rates\n")
    output_lines.append("| Field | Value |")
    output_lines.append("|---|---|")
    output_lines.append(f"| Effective Tax Rate | {effective_rate * 100:.2f}% |")
    output_lines.append(f"| Adjusted Tax Rate | {adjusted_rate * 100:.2f}% |")

    output_lines.append("\n### Tax Rates Reconciliation Bridge\n")
    output_lines.append("| Component | Value | Description |")
    output_lines.append("|---|---|---|")
    output_lines.append(
        f"| Income Before Taxes | {income_before_taxes} | Starting Point for Effective Tax Rate |"
    )
    output_lines.append(f"| Reported Tax Provision | {income_tax_expense} | |")
    output_lines.append(
        f"| **Effective Tax Rate** | **{effective_rate * 100:.2f}%** | -(Reported Tax Provision / Income Before Taxes) |"
    )
    output_lines.append(f"| EBITA | {ebita} | Starting Point for Adjusted Tax Rate |")
    output_lines.append(f"| Reported Tax Provision | {income_tax_expense} | |")
    for adj in tax_adjustments:
        name = adj.get("name", "Adjustment")
        val = adj.get("value", 0.0)
        sign = "+" if val >= 0 else ""
        output_lines.append(f"| {name} | {sign}{val} | |")
    output_lines.append(f"| **Adjusted Taxes** | **{adj_taxes}** | |")
    output_lines.append(
        f"| **Adjusted Tax Rate** | **{adjusted_rate * 100:.2f}%** | -(Adjusted Taxes / EBITA) |"
    )
    output_lines.append("\n---\n")

    output_lines.append("## Financial Summary\n")
    output_lines.append("| Metric | Value | Notes |")
    output_lines.append("|---|---|---|")
    output_lines.append(f"| **Revenue** | {revenue} | |")
    output_lines.append(f"| **EBITA** | {ebita} | |")
    output_lines.append(f"| **EBITA Margin** | {ebita_margin:.2f}% | |")
    output_lines.append(f"| **NOPAT** | {nopat:.2f} | |")
    output_lines.append(f"| **Invested Capital** | {ic} | |")
    output_lines.append(f"| **Capital Turnover** | {turnover:.2f}x | |")
    output_lines.append(f"| **ROIC** | {roic:.2f}% | |")
    output_lines.append(f"| **Basic Shares Outstanding** | {basic_shares} | |")
    output_lines.append(f"| **Diluted Shares Outstanding** | {diluted_shares} | |")
    output_lines.append(f"| **Simple Revenue Growth** | {simple_growth * 100:.2f}% | |")
    output_lines.append(
        f"| **Organic Revenue Growth** | {organic_growth * 100:.2f}% | |"
    )
    output_lines.append("\n---\n")

    output_lines.append("## Shares Outstanding\n")
    output_lines.append(f"Basic Shares Outstanding: **{basic_shares}**\n")
    output_lines.append(f"Diluted Shares Outstanding: **{diluted_shares}**\n")

    output_lines.append("## Organic Growth\n")
    output_lines.append(f"Simple Growth (%): **{simple_growth * 100}**\n")
    output_lines.append(f"Final Growth (%): **{organic_growth * 100}**\n")

    output_lines.append("\n## Extracted Line Items & Audit Lineage\n")
    output_lines.append(
        "| Line Name | Value | Operating | Calculated | Category | Source File | Chunk ID | Exact Snippet |"
    )
    output_lines.append("|---|---|---|---|---|---|---|---|")
    for item in extracted_line_items:
        clean_snippet = item.audit.exact_snippet.replace("\n", " ").replace("|", "\\|")
        output_lines.append(
            f"| {item.line_name} | {item.value} | {item.operating} | {item.calculated} | {item.category} | "
            f"{item.audit.source_file} | {item.audit.chunk_id} | {clean_snippet} |"
        )

    # Write output file to 4_extracted_data/
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    out_file_path = extracted_dir / f"{file_path.stem}_extracted.md"

    with open(out_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    import src.utils.formatting as formatting

    formatting.print_success(f"Extracted: {file_path.name} -> {out_file_path.name}")
    return True


def extract_financials(
    file_path: Path,
    content: str,
    chunk_ids: list,
    extractor,
    summaries: list,
) -> bool:
    from src.pipeline.extractor_orchestrator import get_chunk_by_id

    # 1. Rank order the chunks by number frequency
    chunk_frequencies = []
    for cid in chunk_ids:
        body = get_chunk_by_id(content, cid)
        if body:
            num_digits = sum(1 for c in body if c.isdigit())
            frequency = num_digits
        else:
            frequency = 0
        chunk_frequencies.append((cid, frequency))
    chunk_frequencies.sort(key=lambda x: x[1], reverse=True)
    sorted_chunk_ids = [x[0] for x in chunk_frequencies]

    # Phase 1: Extract complete balance sheet and income statement
    extracted_line_items = extract_financial_statements(
        file_path=file_path,
        content=content,
        sorted_chunk_ids=sorted_chunk_ids,
        extractor=extractor,
        summaries=summaries,
    )

    # Phase 2: Financial Statement Interpretation Agent
    extracted_line_items = run_interpretation_agent(
        extracted_line_items=extracted_line_items,
        file_path=file_path,
        extractor=extractor,
    )

    # Read the extracted income statement content if available
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    is_path = extracted_dir / f"{file_path.stem}_income_statement.md"
    income_statement_content = ""
    if is_path.exists():
        income_statement_content = is_path.read_text(encoding="utf-8")

    # Find revenue to supply to organic growth agent
    revenue = 0.0
    for item in extracted_line_items:
        n = item.line_name.lower()
        if "revenue" in n or "sales" in n:
            revenue = item.value
            break

    # Phase 3: Diluted Shares and Organic Growth Agents
    basic_shares, diluted_shares = run_diluted_shares_agent(
        content, extractor, income_statement_content=income_statement_content
    )
    simple_growth, organic_growth = run_organic_growth_agent(
        content, revenue, extractor, income_statement_content=income_statement_content
    )

    # Phase 4: Deterministic calculations
    success = calculate_deterministic_metrics(
        file_path=file_path,
        content=content,
        extracted_line_items=extracted_line_items,
        basic_shares=basic_shares,
        diluted_shares=diluted_shares,
        simple_growth=simple_growth,
        organic_growth=organic_growth,
        extractor=extractor,
        summaries=summaries,
        income_statement_content=income_statement_content,
    )

    return success


def update_extract_context(extractor, line_item) -> None:
    """Append classification to 6_company_context/extract_context.md."""
    context_dir = Path(extractor.settings.active_workspace_path) / "6_company_context"
    context_dir.mkdir(parents=True, exist_ok=True)
    context_file = context_dir / "extract_context.md"

    op_str = "operating" if line_item.operating else "non-operating"
    line_rule = f"- {line_item.line_name}: {op_str}\n"

    existing = get_extract_context(extractor)

    if not context_file.exists():
        header = f"# Extraction Context: {extractor.settings.active_ticker or 'UNK'}\n\n## Custom Line Item Classifications\n"
        full_content = header + line_rule
        with open(context_file, "w", encoding="utf-8") as f:
            f.write(full_content)
        extractor._extract_context_cache = full_content
    else:
        if line_item.line_name not in existing:
            with open(context_file, "a", encoding="utf-8") as f:
                f.write(line_rule)
            extractor._extract_context_cache = existing + line_rule


def get_extract_context(extractor) -> str:
    if extractor._extract_context_cache is None:
        context_path = (
            Path(extractor.settings.active_workspace_path)
            / "6_company_context"
            / "extract_context.md"
        )
        if context_path.exists():
            try:
                with open(context_path, "r", encoding="utf-8") as f:
                    extractor._extract_context_cache = f.read()
            except Exception:
                extractor._extract_context_cache = ""
        else:
            extractor._extract_context_cache = ""
    return extractor._extract_context_cache
