from typing import List


def find_keyword_contexts(
    content: str, keywords: List[str], window: int = 200, max_matches: int = 15
) -> List[dict]:
    """Find occurrences of keywords in content and return snippets of 200 chars before and after, along with the chunk ID they were found in."""
    if window < 100:
        window = 100

    content_lower = content.lower()

    # ⚡ Bolt Optimization: Fast-fail empty searches before expensive regex chunk parsing
    active_keywords_with_pos = []
    for kw in keywords:
        kw_lower = kw.lower()
        pos = content_lower.find(kw_lower)
        if pos != -1:
            active_keywords_with_pos.append((kw, kw_lower, pos))
    if not active_keywords_with_pos:
        return []

    # ⚡ Bolt Optimization: Replace O(N) full-document chunk parsing with on-demand native reverse search
    def get_chunk_for_pos(pos: int) -> int:
        start_idx = content.rfind("<!-- CHUNK_START:", 0, pos)
        if start_idx != -1:
            end_idx = content.find("-->", start_idx)
            if end_idx != -1 and end_idx < pos:
                try:
                    return int(content[start_idx + 17 : end_idx].strip())
                except ValueError:
                    pass
        return 0

    snippets = []
    seen = set()
    for kw, kw_lower, first_pos in active_keywords_with_pos:
        pos = first_pos
        match_count = 0
        while True:
            start_idx = max(0, pos - window)
            end_idx = min(len(content), pos + len(kw) + window)
            snippet = content[start_idx:end_idx].strip()

            chunk_id = get_chunk_for_pos(pos)
            # Use tuple for O(1) set lookup instead of O(N) dict list lookup
            seen_key = (chunk_id, snippet)
            if seen_key not in seen:
                seen.add(seen_key)
                snippets.append({"chunk_id": chunk_id, "snippet": snippet})
                match_count += 1
                if match_count >= max_matches:
                    break

            start = pos + len(kw)
            pos = content_lower.find(kw_lower, start)
            if pos == -1:
                break
    return snippets
