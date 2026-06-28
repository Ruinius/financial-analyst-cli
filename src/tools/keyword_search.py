import re
import bisect
from typing import List

CHUNK_START_RE = re.compile(r"<!--\s*CHUNK_START:\s*(\d+)\s*-->")
CHUNK_END_RE = re.compile(r"<!--\s*CHUNK_END:\s*(\d+)\s*-->")


def find_keyword_contexts(
    content: str, keywords: List[str], window: int = 200, max_matches: int = 15
) -> List[dict]:
    """Find occurrences of keywords in content and return snippets of 200 chars before and after, along with the chunk ID they were found in."""
    if window < 100:
        window = 100

    # Parse chunk spans
    chunk_spans = []  # list of tuples: (chunk_id, start_idx, end_idx)
    starts = {}
    for m in CHUNK_START_RE.finditer(content):
        cid = int(m.group(1))
        starts[cid] = m.end()

    ends = {}
    for m in CHUNK_END_RE.finditer(content):
        cid = int(m.group(1))
        ends[cid] = m.start()

    for cid, start in starts.items():
        if cid in ends:
            chunk_spans.append((cid, start, ends[cid]))

    chunk_spans.sort(key=lambda x: x[1])

    first_start = min(starts.values()) if starts else len(content)
    chunk_spans.insert(0, (0, 0, first_start))

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
        match_count = 0
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
                match_count += 1
                if match_count >= max_matches:
                    break

            start = pos + len(kw)
            if start >= len(content):
                break
    return snippets
