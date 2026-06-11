def parse_markdown_table(text, table_name=None):
    lines = text.split("\n")
    headers = []
    rows = []
    in_target_table = table_name is None
    in_table = False

    for i, line in enumerate(lines):
        if line.startswith("## ") or line.startswith("### "):
            if table_name and table_name.lower() in line.lower():
                in_target_table = True
            elif in_target_table and table_name:
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
            pass

    return rows


def parse_kv_table(text, section_name):
    rows = parse_markdown_table(text, section_name)
    result = {}
    for r in rows:
        keys = list(r.keys())
        if len(keys) >= 2:
            key = r[keys[0]].strip().replace("**", "")
            val = r[keys[1]].strip().replace("**", "")
            result[key] = val
    return result


def clean_value(val):
    if not val or val == "N/A":
        return 0
    val = val.replace(",", "")
    if val.startswith("("):
        val = "-" + val.strip("()")
    try:
        if "%" in val:
            return float(val.replace("%", "")) / 100.0
        return float(val)
    except (ValueError, TypeError):
        return 0
