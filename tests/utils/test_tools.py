def test_get_chunk_by_id():
    from src.tools.find_chunk import get_chunk_by_id

    content = """# Metadata Table
Some headers here

---
<!-- CHUNK_START: 1 -->
This is chunk 1 content
<!-- CHUNK_END: 1 -->
---
<!-- CHUNK_START: 2 -->
This is chunk 2 content
<!-- CHUNK_END: 2 -->
"""
    # Test chunk 0 (everything before chunk 1 start)
    chunk_0 = get_chunk_by_id(content, 0)
    assert "# Metadata Table" in chunk_0
    assert "Some headers here" in chunk_0
    assert "CHUNK_START" not in chunk_0

    # Test chunk 1
    chunk_1 = get_chunk_by_id(content, 1)
    assert chunk_1 == "This is chunk 1 content"

    # Test chunk 2
    chunk_2 = get_chunk_by_id(content, 2)
    assert chunk_2 == "This is chunk 2 content"

    # Test non-existent chunk
    chunk_3 = get_chunk_by_id(content, 3)
    assert chunk_3 == ""
