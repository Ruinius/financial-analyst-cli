import time
from typing import Optional, List, Dict

def parse_markdown_table_fastest(
    text: str, table_name: Optional[str] = None
) -> List[Dict[str, str]]:

    # ⚡ Bolt Optimization: Fast string search to isolate the relevant section
    # This prevents splitting massive markdown files and iterating over every single line
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
        # We find the start index of the first header containing the target name
        search_idx = 0
        found = False
        while True:
            h_idx = text_lower.find(target_name, search_idx)
            if h_idx == -1:
                break

            # Backtrack to find the start of this line and check if it's a header
            line_start = text_lower.rfind("\n", 0, h_idx)
            if line_start == -1:
                line_start = 0
            else:
                line_start += 1 # move past \n

            # Check if line starts with #
            if text_lower[line_start] == '#':
                start_idx = line_start
                found = True
                break

            search_idx = h_idx + 1

        if not found:
            return []

    # Split only the remaining portion (or full text if no table_name)
    lines = text[start_idx:end_idx].split("\n")

    headers = []
    rows = []
    in_target_table = table_name is None
    in_table = False

    for i, line in enumerate(lines):
        if line.startswith(("# ", "## ", "### ")):
            if target_name:
                cleaned_line = line.lower().replace("#", "").strip()
                if target_name in cleaned_line:
                    in_target_table = True
                elif in_target_table:
                    in_target_table = False

        if in_target_table and "|" in line:
            if not in_table:
                # possible header
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

def parse_markdown_table_original(
    text: str, table_name: Optional[str] = None
) -> List[Dict[str, str]]:
    lines = text.split("\n")
    headers = []
    rows = []
    in_target_table = table_name is None
    in_table = False

    target_name = None
    if table_name:
        target_name = table_name.lower().replace("#", "").strip()

    for i, line in enumerate(lines):
        if line.startswith("## ") or line.startswith("### ") or line.startswith("# "):
            if target_name:
                cleaned_line = line.lower().replace("#", "").strip()
                if target_name in cleaned_line:
                    in_target_table = True
                elif in_target_table:
                    in_target_table = False

        if in_target_table and "|" in line:
            if not in_table:
                # possible header
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

text = "# Some header\n" + "Some text\n" * 1000 + "## Target Table\n" + "| Col1 | Col2 |\n| --- | --- |\n| Val1 | Val2 |\n" + "## Other Header\n" + "Text\n" * 1000

start = time.time()
for _ in range(1000):
    parse_markdown_table_fastest(text, "Target Table")
end = time.time()
print(f"Fastest: {end-start:.4f}s")

start = time.time()
for _ in range(1000):
    parse_markdown_table_original(text, "Target Table")
end = time.time()
print(f"Original: {end-start:.4f}s")

r1 = parse_markdown_table_original(text, "Target Table")
r2 = parse_markdown_table_fastest(text, "Target Table")
print(r1 == r2)

text2 = """## Target Table
| A | B |
|---|---|
| 1 | 2 |
| 3 | 4 |

## Target Table 2
| 5 | 6 |
"""
r1 = parse_markdown_table_original(text2, "Target Table")
r2 = parse_markdown_table_fastest(text2, "Target Table")
print("Multiple tables test:", r1 == r2)
