from src.cli.commands.query import query_summary


def test_query_import():
    assert query_summary is not None
