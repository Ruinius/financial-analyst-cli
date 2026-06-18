def get_chunk_by_id(content: str, chunk_id: int) -> str:
    """Extract chunk content between comments."""
    if chunk_id == 0:
        # Extract everything before the first chunk start comment
        start_idx = content.find("<!-- CHUNK_START:")
        if start_idx != -1:
            return content[:start_idx].strip()
        return content.strip()

    start_marker = f"<!-- CHUNK_START: {chunk_id} -->"
    end_marker = f"<!-- CHUNK_END: {chunk_id} -->"

    start_idx = content.find(start_marker)
    if start_idx == -1:
        return ""
    start_idx += len(start_marker)

    end_idx = content.find(end_marker, start_idx)
    if end_idx == -1:
        return ""

    return content[start_idx:end_idx].strip()
