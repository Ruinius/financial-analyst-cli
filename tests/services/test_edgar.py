from unittest.mock import patch, MagicMock
import pytest

from src.core.config import Settings
from src.services.edgar_client import EdgarClient


@pytest.fixture
def mock_settings(tmp_path):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    settings = Settings(
        full_name="Test User",
        email="test@example.com",
        project_name="TestProject",
        primary_llm_api_key="sk-testkey",
        base_workspace_dir=str(tmp_path),
        active_ticker="AAPL",
        active_workspace_path=str(workspace),
    )
    return settings


@patch("src.services.edgar_client.load_config")
@patch("httpx.Client.get")
def test_get_cik(mock_get, mock_load_config, mock_settings):
    mock_load_config.return_value = mock_settings

    # Mock ticker json response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp."},
    }
    mock_get.return_value = mock_response

    client = EdgarClient()
    cik = client.get_cik("AAPL")
    assert cik == "320193"

    # Case-insensitive
    cik_lower = client.get_cik("aapl")
    assert cik_lower == "320193"

    with pytest.raises(ValueError):
        client.get_cik("UNKNOWN")


@patch("src.services.edgar_client.load_config")
@patch("httpx.Client.get")
def test_download_filings(mock_get, mock_load_config, mock_settings):
    mock_load_config.return_value = mock_settings

    # Configure mock responses for CIK query, submissions, and filing download
    mock_tickers_resp = MagicMock()
    mock_tickers_resp.status_code = 200
    mock_tickers_resp.json.return_value = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
    }

    mock_submissions_resp = MagicMock()
    mock_submissions_resp.status_code = 200
    mock_submissions_resp.json.return_value = {
        "cik": "320193",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-23-000106"],
                "filingDate": ["2023-11-03"],
                "reportDate": ["2023-09-30"],
                "form": ["10-K"],
                "primaryDocument": ["aapl-20230930.htm"],
            }
        },
    }

    mock_doc_resp = MagicMock()
    mock_doc_resp.status_code = 200
    mock_doc_resp.content = b"Mock HTML Content"

    # Define side effect to return responses in order
    mock_get.side_effect = [mock_tickers_resp, mock_submissions_resp, mock_doc_resp]

    client = EdgarClient()
    downloaded = client.download_filings("AAPL", years=5)

    assert len(downloaded) == 1
    assert downloaded[0].name == "0000320193-23-000106_aapl-20230930.htm"
    assert downloaded[0].exists()
    assert downloaded[0].read_bytes() == b"Mock HTML Content"
