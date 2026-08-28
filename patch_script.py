with open('src/tools/keyword_search.py', 'r') as f:
    content = f.read()

import re
old_block = r'''    # ⚡ Bolt Optimization: Replace regex finditer with native str.find for chunk bounds \(~15x speedup\)
    chunk_spans = \[\]  # list of tuples: \(chunk_id, start_idx, end_idx\)
    starts = \{\}.*?    def get_chunk_for_pos\(pos: int\) -> int:
        if not chunk_spans:
            return 0
        idx = bisect\.bisect_right\(chunk_starts, pos\) - 1
        if idx >= 0:
            cid, start, end = chunk_spans\[idx\]
            if start <= pos <= end:
                return cid
            # If not strictly within, return the closest previous chunk \(or 0\)
            return cid
        return 0'''

new_block = '''    # ⚡ Bolt Optimization: Lazily resolve positional boundaries using native reverse search to bypass O(N) full-document parse overhead
    def get_chunk_for_pos(pos: int) -> int:
        start_idx = content.rfind("<!-- CHUNK_START:", 0, pos)
        if start_idx == -1:
            return 0
        end_idx = content.find("-->", start_idx)
        if end_idx != -1:
            try:
                return int(content[start_idx + 17 : end_idx].strip())
            except ValueError:
                return 0
        return 0'''

content = re.sub(old_block, new_block, content, flags=re.DOTALL)
with open('src/tools/keyword_search.py', 'w') as f:
    f.write(content)
