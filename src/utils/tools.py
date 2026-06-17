import re
from pathlib import Path


def find_keyword_contexts(content: str, keywords: list, window: int = 200) -> list:
    """Find occurrences of keywords in content and return snippets of 200 chars before and after, along with the chunk ID they were found in."""
    if window < 100:
        window = 100

    # Parse chunk spans
    chunk_spans = []  # list of tuples: (chunk_id, start_idx, end_idx)
    starts = {}
    for m in re.finditer(r"<!--\s*CHUNK_START:\s*(\d+)\s*-->", content):
        cid = int(m.group(1))
        starts[cid] = m.end()

    ends = {}
    for m in re.finditer(r"<!--\s*CHUNK_END:\s*(\d+)\s*-->", content):
        cid = int(m.group(1))
        ends[cid] = m.start()

    for cid, start in starts.items():
        if cid in ends:
            chunk_spans.append((cid, start, ends[cid]))

    chunk_spans.sort(key=lambda x: x[1])

    first_start = min(starts.values()) if starts else len(content)
    chunk_spans.insert(0, (0, 0, first_start))

    import bisect

    chunk_starts = [x[1] for x in chunk_spans]

    def get_chunk_for_pos(pos: int) -> int:
        if not chunk_spans:
            return 0
        idx = bisect.bisect_right(chunk_starts, pos) - 1
        if idx >= 0:
            cid, start, end = chunk_spans[idx]
            if start <= pos <= end:
                return cid
            # If not strictly within, return the closest previous chunk (or 0)
            return cid
        return 0

    snippets = []
    seen = set()
    content_lower = content.lower()
    for kw in keywords:
        kw_lower = kw.lower()
        start = 0
        while True:
            pos = content_lower.find(kw_lower, start)
            if pos == -1:
                break
            start_idx = max(0, pos - window)
            end_idx = min(len(content), pos + len(kw) + window)
            snippet = content[start_idx:end_idx].strip()

            chunk_id = get_chunk_for_pos(pos)
            # Use tuple for O(1) set lookup instead of O(N) dict list lookup
            seen_key = (chunk_id, snippet)
            if seen_key not in seen:
                seen.add(seen_key)
                snippets.append({"chunk_id": chunk_id, "snippet": snippet})

            start = pos + len(kw)
            if start >= len(content):
                break
    return snippets


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
