import re
import time
from typing import Optional, List, Dict

def parse_markdown_table(
    text: str, table_name: Optional[str] = None
) -> List[Dict[str, str]]:
    start_idx = 0
    end_idx = len(text)
    target_name = None

    if table_name:
        target_name = table_name.lower().replace("#", "").strip()
        text_lower = text.lower()

        # 1. Fast check if the table even exists
        if target_name not in text_lower:
            return []

        # 2. Narrow down the text block to search in
        search_idx = 0
        found = False
        while True:
            h_idx = text_lower.find(target_name, search_idx)
            if h_idx == -1:
                break

            line_start = text_lower.rfind("\n", 0, h_idx)
            if line_start == -1:
                line_start = 0
            else:
                line_start += 1

            if text_lower[line_start] == '#':
                start_idx = line_start
                found = True
                break

            search_idx = h_idx + 1

        if not found:
            return []

        next_header_idx = text_lower.find("\n#", start_idx + len(target_name))
        if next_header_idx != -1:
            end_idx = next_header_idx

    lines = text[start_idx:end_idx].split("\n")

    headers = []
    rows = []
    in_table = False

    for i, line in enumerate(lines):
        if "|" in line:
            if not in_table:
                if i + 1 < len(lines) and "|---" in lines[i + 1].replace(" ", ""):
                    headers = [x.strip() for x in line.split("|")[1:-1]]
                    in_table = True
            elif "---" not in line:
                row_vals = [x.strip() for x in line.split("|")[1:-1]]
                if len(row_vals) == len(headers):
                    rows.append(dict(zip(headers, row_vals)))
        elif in_table and not line.strip():
            in_table = False

    return rows

