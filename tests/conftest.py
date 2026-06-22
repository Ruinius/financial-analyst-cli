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
def mock_workspace(tmp_path, monkeypatch):
    # Setup mock workspace
    workspace = tmp_path / "MOCK"
    workspace.mkdir(parents=True)

    fake_config_path = tmp_path / ".env"
    monkeypatch.setattr("src.core.config.CONFIG_FILE_PATH", fake_config_path)

    settings = Settings(
        full_name="Test Developer",
        email="developer@example.com",
        project_name="TestProject",
        base_workspace_dir=str(tmp_path),
        active_workspace_path=str(workspace),
        active_ticker="MOCK",
    )
    save_config(settings)

    # Write blackboard JSON state file directly to eliminate disk fallbacks
    state_file = workspace / "workspace_state.json"
    import json

    state_data = {
        "metadata": {
            "ticker": "MOCK",
            "company_name": "Mock Company",
            "preferred_unit": "Millions",
        },
        "metadata_status": "completed",
        "company_data": {
            "quarterly_financials": [
                {
                    "fiscal_year": 2023,
                    "fiscal_period": "Q1",
                    "revenue": 1000.0,
                    "operating_income": 200.0,
                    "ebita": 200.0,
                    "reported_tax_provision": 50.0,
                    "adjusted_taxes": 50.0,
                    "adjusted_tax_rate": 0.25,
                    "basic_shares": 10.0,
                    "diluted_shares": 10.0,
                    "simple_growth": 0.05,
                    "organic_growth": 0.05,
                    "net_working_capital": 100.0,
                    "net_long_term_operating_assets": 400.0,
                    "invested_capital": 500.0,
                    "capital_turnover": 2.0,
                    "nopat": 150.0,
                    "roic": 30.0,
                },
                {
                    "fiscal_year": 2023,
                    "fiscal_period": "Q2",
                    "revenue": 1100.0,
                    "operating_income": 220.0,
                    "ebita": 220.0,
                    "reported_tax_provision": 55.0,
                    "adjusted_taxes": 55.0,
                    "adjusted_tax_rate": 0.25,
                    "basic_shares": 10.0,
                    "diluted_shares": 10.0,
                    "simple_growth": 0.05,
                    "organic_growth": 0.05,
                    "net_working_capital": 110.0,
                    "net_long_term_operating_assets": 440.0,
                    "invested_capital": 550.0,
                    "capital_turnover": 2.0,
                    "nopat": 165.0,
                    "roic": 30.0,
                },
                {
                    "fiscal_year": 2023,
                    "fiscal_period": "Q3",
                    "revenue": 1200.0,
                    "operating_income": 240.0,
                    "ebita": 240.0,
                    "reported_tax_provision": 60.0,
                    "adjusted_taxes": 60.0,
                    "adjusted_tax_rate": 0.25,
                    "basic_shares": 10.0,
                    "diluted_shares": 10.0,
                    "simple_growth": 0.05,
                    "organic_growth": 0.05,
                    "net_working_capital": 120.0,
                    "net_long_term_operating_assets": 480.0,
                    "invested_capital": 600.0,
                    "capital_turnover": 2.0,
                    "nopat": 180.0,
                    "roic": 30.0,
                },
                {
                    "fiscal_year": 2023,
                    "fiscal_period": "Q4",
                    "revenue": 1300.0,
                    "operating_income": 260.0,
                    "ebita": 260.0,
                    "reported_tax_provision": 65.0,
                    "adjusted_taxes": 65.0,
                    "adjusted_tax_rate": 0.25,
                    "basic_shares": 10.0,
                    "diluted_shares": 10.0,
                    "simple_growth": 0.05,
                    "organic_growth": 0.05,
                    "net_working_capital": 130.0,
                    "net_long_term_operating_assets": 520.0,
                    "invested_capital": 650.0,
                    "capital_turnover": 2.0,
                    "nopat": 195.0,
                    "roic": 30.0,
                },
            ],
            "historical_analyst_views": [
                {
                    "report_date": "2023-12-31",
                    "source_file": "10-K",
                    "economic_moat": "Wide",
                    "economic_moat_rationale": "Strong brand",
                    "margin_outlook": "Expanding",
                    "margin_magnitude": "+2pp",
                    "margin_rationale": "Good",
                    "growth_outlook": "Expanding",
                    "growth_magnitude": "+3pp",
                    "growth_rationale": "Good",
                }
            ],
        },
    }
    state_file.write_text(json.dumps(state_data), encoding="utf-8")
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
