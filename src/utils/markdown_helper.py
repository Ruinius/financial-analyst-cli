import re
from pathlib import Path


def clean_json_text(text: str) -> str:
    """Clean a JSON string by removing single-line and multi-line comments,
    and trailing commas before closing braces/brackets.
    """
    if not text:
        return ""
    # Strip comments safely without affecting string literals
    cleaned = re.sub(
        r'("(?:\\.|[^"\\])*")|/\*.*?\*/|//[^\r\n]*',
        lambda m: m.group(1) or "",
        text,
        flags=re.DOTALL,
    )
    # Strip trailing commas before closing braces/brackets
    cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)
    return cleaned


def extract_json_from_text(text: str) -> str | None:
    """Extract a JSON object from text by finding the first '{' and last '}' and cleansing it."""
    if not text:
        return None
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        raw_json = text[start_idx : end_idx + 1]
        return clean_json_text(raw_json)
    return None


def append_markdown(filepath: str, text: str) -> str:
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
        return "Success: Appended content."
    except Exception as e:
        return f"Error appending content: {e}"


def edit_markdown(filepath: str, target_text: str, replacement_text: str) -> str:
    try:
        path = Path(filepath)
        if not path.exists():
            return "Error: File does not exist."
        content = path.read_text(encoding="utf-8")
        if target_text not in content:
            return "Error: Target text to replace was not found in the file."
        updated = content.replace(target_text, replacement_text)
        path.write_text(updated, encoding="utf-8")
        return "Success: Content replaced."
    except Exception as e:
        return f"Error replacing content: {e}"


def validate_markdown_table_syntax(content: str) -> str | None:
    """Validate that the markdown table(s) in content are formatted correctly.

    A valid markdown table:
    1. Must exist (at least one row starting/ending with | after stripping).
    2. Any block of adjacent rows starting/ending with | is considered a table.
    3. Each table block must have at least 3 rows (headers, separator, and data).
    4. The second row of each table block must be a valid separator row (containing only dashes, colons, spaces, and pipes).
    5. Every row in a table block must have the same number of columns (delimited by |).
    """
    lines = content.splitlines()

    # 1. Group consecutive table lines
    table_blocks = []
    current_block = []
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            current_block.append((line_idx + 1, stripped))
        else:
            if current_block:
                table_blocks.append(current_block)
                current_block = []
    if current_block:
        table_blocks.append(current_block)

    if not table_blocks:
        return "Error: No markdown table found. The extracted statement must be formatted as a valid markdown table (with columns separated by '|')."

    # 2. Validate each table block
    for block in table_blocks:
        if len(block) < 3:
            line_num, text = block[0]
            return f"Error: Table starting at line {line_num} has fewer than 3 lines. A markdown table must contain a header row, a separator row, and at least one data row."

        # Validate separator row (second row of the block)
        sep_line_num, sep_text = block[1]
        # Split separator row into cells, excluding outer empty cells
        sep_cells = [c.strip() for c in sep_text.split("|")[1:-1]]

        if not sep_cells:
            return (
                f"Error: Markdown table separator row at line {sep_line_num} is empty."
            )

        for cell in sep_cells:
            # Separator cells must match e.g. '---', ':---', '---:', ':---:' or even just '-'
            if not re.match(r"^:?-+:?$", cell):
                return (
                    f"Error: Invalid markdown table separator row at line {sep_line_num}. "
                    f"Found: '{sep_text}'. The second row must only contain dashes and optional colons to separate column headers (e.g. '| --- | --- |')."
                )

        # Validate column count consistency across all rows in the block
        sep_col_count = len(sep_cells)
        for idx, (line_num, text) in enumerate(block):
            row_cells = [c.strip() for c in text.split("|")[1:-1]]
            if len(row_cells) != sep_col_count:
                return (
                    f"Error: Column count mismatch in table row at line {line_num}. "
                    f"Expected {sep_col_count} columns (based on the separator row at line {sep_line_num}), but found {len(row_cells)} columns. "
                    f"Line: '{text}'"
                )

    return None
