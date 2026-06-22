from unittest.mock import patch, MagicMock

from src.core.config import Settings
from src.services.edgar_client import EdgarClient


@patch("src.services.edgar_client.load_config")
@patch("httpx.Client.get")
def test_download_filings_path_traversal(mock_get, mock_load_config, tmp_path):
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
    mock_load_config.return_value = settings

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
                "accessionNumber": ["../../../etc/passwd"],
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

    mock_get.side_effect = [mock_tickers_resp, mock_submissions_resp, mock_doc_resp]

    client = EdgarClient()
    downloaded = client.download_filings("AAPL", years=5)

    assert len(downloaded) == 1
    # Check that it removed the slashes
    assert downloaded[0].name == "etcpasswd_aapl-20230930.htm"
    assert ".." not in downloaded[0].name
    assert "/" not in downloaded[0].name
