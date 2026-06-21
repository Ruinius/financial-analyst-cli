from src.utils.markdown_helper import validate_markdown_table_syntax


def test_valid_markdown_table():
    content = """# Extracted Statements

| Header 1 | Header 2 |
| --- | --- |
| Row 1 Col 1 | Row 1 Col 2 |
| Row 2 Col 1 | Row 2 Col 2 |
"""
    assert validate_markdown_table_syntax(content) is None


def test_missing_table():
    content = """# Extracted Statements

Some random text with no table.
"""
    err = validate_markdown_table_syntax(content)
    assert err is not None
    assert "No markdown table found" in err


def test_table_too_short():
    content = """# Extracted Statements

| Header 1 | Header 2 |
| Row 1 Col 1 | Row 1 Col 2 |
"""
    err = validate_markdown_table_syntax(content)
    assert err is not None
    assert "fewer than 3 lines" in err


def test_missing_separator():
    content = """# Extracted Statements

| Header 1 | Header 2 |
| Row 1 Col 1 | Row 1 Col 2 |
| Row 2 Col 1 | Row 2 Col 2 |
"""
    err = validate_markdown_table_syntax(content)
    assert err is not None
    assert "Invalid markdown table separator row" in err


def test_column_count_mismatch():
    content = """# Extracted Statements

| Header 1 | Header 2 |
| --- | --- |
| Row 1 Col 1 | Row 1 Col 2 | Row 1 Col 3 |
"""
    err = validate_markdown_table_syntax(content)
    assert err is not None
    assert "Column count mismatch" in err
