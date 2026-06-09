import pytest
from src.viewer.server import DCFViewerHandler
from unittest.mock import MagicMock, patch

def test_server_import():
    assert DCFViewerHandler is not None
