import pytest
from src.cli.commands.query import query_summary
from unittest.mock import patch

def test_query_import():
    assert query_summary is not None
