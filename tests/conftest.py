import socket
import pytest
from src.core.config import Settings, save_config


@pytest.fixture(autouse=True)
def block_network_calls(monkeypatch):
    """
    Globally block all socket-based network calls in the test suite to prevent accidental LLM or external API calls,
    while allowing local loopback connections needed by asyncio and local servers.
    """
    original_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0]
        if host not in ("localhost", "127.0.0.1", "::1"):
            raise RuntimeError(
                f"Accidental real network connection blocked in tests to prevent real LLM/API calls: {address}. "
                "Please mock the HTTP/API clients in your test."
            )
        return original_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture
def mock_workspace(tmp_path):
    # Setup mock workspace
    workspace = tmp_path / "MOCK"
    workspace.mkdir(parents=True)

    analysis_dir = workspace / "5_historical_analysis"
    analysis_dir.mkdir(parents=True)

    quarter_path = analysis_dir / "financials_quarter.md"
    quarter_path.write_text(
        "## Historical Financials\n"
        "| Time Period | Period End | Revenue | EBITA | EBITA Margin | Adj Tax Rate | NOPAT | Invested Capital | Capital Turnover | ROIC | Organic Growth | Source Document |\n"
        "|-------------|-----------|---------|-------|--------------|-------------|-------|-----------------|------------------|------|----------------|-----------------|\n"
        "| 2023-Q1     | 2023-03-31 | 1000    | 200   | 20.00%       | 25.00%      | 150   | 500             | 2.0x             | 30.0%| 5.00%          | 10-Q            |\n"
        "| 2023-Q2     | 2023-06-30 | 1100    | 220   | 20.00%       | 25.00%      | 165   | 550             | 2.0x             | 30.0%| 5.00%          | 10-Q            |\n"
        "| 2023-Q3     | 2023-09-30 | 1200    | 240   | 20.00%       | 25.00%      | 180   | 600             | 2.0x             | 30.0%| 5.00%          | 10-Q            |\n"
        "| 2023-Q4     | 2023-12-31 | 1300    | 260   | 20.00%       | 25.00%      | 195   | 650             | 2.0x             | 30.0%| 5.00%          | 10-K            |\n"
    )

    analyst_path = analysis_dir / "analyst_views.md"
    analyst_path.write_text(
        "## Analyst Views\n"
        "| Date | Document | Economic Moat | Moat Rationale | Margin Outlook | Margin Magnitude | Margin Rationale | Growth Outlook | Growth Magnitude | Growth Rationale |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        "| 2023-12-31 | 10-K | Wide | Strong brand | Expanding | +2pp | Good | Expanding | +3pp | Good |\n"
    )

    return workspace


@pytest.fixture
def temp_workspace_env(tmp_path, monkeypatch):
    fake_config_path = tmp_path / ".env"
    monkeypatch.setattr("src.core.config.CONFIG_FILE_PATH", fake_config_path)

    settings = Settings(
        full_name="Test Developer",
        email="developer@example.com",
        project_name="TestProject",
        base_workspace_dir=str(tmp_path / "workspace"),
        active_workspace_path=str(tmp_path / "workspace" / "AAPL"),
        active_ticker="AAPL",
    )
    save_config(settings)
    (tmp_path / "workspace" / "AAPL").mkdir(parents=True, exist_ok=True)
    return settings
