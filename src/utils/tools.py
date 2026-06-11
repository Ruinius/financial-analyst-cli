from pathlib import Path


def find_keyword_contexts(content: str, keywords: list, window: int = 200) -> list:
    """Find occurrences of keywords in content and return snippets of 200 chars before and after."""
    if window < 100:
        window = 100
    snippets = []
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
            if snippet not in snippets:
                snippets.append(snippet)
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
