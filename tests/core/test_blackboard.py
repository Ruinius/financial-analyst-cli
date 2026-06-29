import tempfile
from pathlib import Path
import pytest

from src.core.config import Settings, save_config
from src.core.exceptions import WorkspaceError
from src.core.blackboard import (
    LineItem,
    CompanyMetadata,
    HistoricalFinancialSummary,
    TemporalBlackboard,
    WorkspaceContext,
    load_workspace_state,
    save_workspace_state,
)


@pytest.fixture
def temp_workspace_env(monkeypatch):
    """Fixture to isolate environment settings and paths during blackboard tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        fake_config_path = tmp_path / ".env"
        # Mock CONFIG_FILE_PATH so load_config / save_config read/write here
        monkeypatch.setattr("src.core.config.CONFIG_FILE_PATH", fake_config_path)

        # Set up active settings with base_workspace_dir inside the temp dir
        settings = Settings(
            full_name="Test Developer",
            email="developer@example.com",
            project_name="TestProject",
            base_workspace_dir=str(tmp_path / "workspace"),
        )
        save_config(settings)
        yield settings


def test_line_item_validation():
    # Valid line item
    item = LineItem(
        line_name="Cash",
        value=1500000.0,
        operating=True,
        calculated=False,
        category="current_assets",
    )
    assert item.line_name == "Cash"
    assert item.value == 1500000.0
    assert item.operating is True

    # Invalid category
    with pytest.raises(ValueError):
        LineItem(
            line_name="Cash",
            value=1500000.0,
            category="invalid_category",  # type: ignore
        )

    # 'other' category sanitization
    item_other = LineItem(
        line_name="Misc Expense",
        value=500.0,
        category="other",  # type: ignore
    )
    assert item_other.category == "income_statement"


def test_fiscal_year_validation():
    # Valid years
    for yr in [1000, 2026, 9999]:
        summary = HistoricalFinancialSummary(
            fiscal_year=yr,
            fiscal_period="Q1",
            revenue=100.0,
            operating_income=10.0,
            ebita=10.0,
            reported_tax_provision=2.0,
            adjusted_taxes=2.0,
            adjusted_tax_rate=0.2,
            basic_shares=10.0,
            diluted_shares=10.0,
            simple_growth=0.05,
            organic_growth=0.05,
            net_working_capital=50.0,
            net_long_term_operating_assets=200.0,
            invested_capital=250.0,
            capital_turnover=0.4,
            nopat=8.0,
            roic=0.032,
        )
        assert summary.fiscal_year == yr

        report = TemporalBlackboard(
            fiscal_year=yr,
            fiscal_period="FY",
            is_quarterly=False,
        )
        assert report.fiscal_year == yr

    # Invalid years (non 4-digit)
    for yr in [999, 10000, -2026]:
        with pytest.raises(ValueError):
            HistoricalFinancialSummary(
                fiscal_year=yr,
                fiscal_period="Q1",
                revenue=100.0,
                operating_income=10.0,
                ebita=10.0,
                reported_tax_provision=2.0,
                adjusted_taxes=2.0,
                adjusted_tax_rate=0.2,
                basic_shares=10.0,
                diluted_shares=10.0,
                simple_growth=0.05,
                organic_growth=0.05,
                net_working_capital=50.0,
                net_long_term_operating_assets=200.0,
                invested_capital=250.0,
                capital_turnover=0.4,
                nopat=8.0,
                roic=0.032,
            )

        with pytest.raises(ValueError):
            TemporalBlackboard(
                fiscal_year=yr,
                fiscal_period="Q1",
                is_quarterly=True,
            )


def test_blackboard_serialization_deserialization():
    metadata = CompanyMetadata(
        ticker="AAPL",
        company_name="Apple Inc.",
        description="Consumer electronics company",
    )
    context = WorkspaceContext(metadata=metadata)

    # Add a report
    report = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
    )
    report.financial_data.revenue = 90750000000.0
    item = LineItem(
        line_name="Cash and Cash Equivalents",
        value=29912000000.0,
        operating=True,
        calculated=False,
        category="current_assets",
    )
    report.financial_data.line_items.append(item)
    context.reports["2024_Q3"] = report

    # Test round-trip serialization/deserialization
    serialized = context.model_dump_json()
    deserialized = WorkspaceContext.model_validate_json(serialized)

    assert deserialized.metadata.ticker == "AAPL"
    assert deserialized.metadata.company_name == "Apple Inc."
    assert "2024_Q3" in deserialized.reports
    assert deserialized.reports["2024_Q3"].financial_data.revenue == 90750000000.0
    assert len(deserialized.reports["2024_Q3"].financial_data.line_items) == 1
    assert (
        deserialized.reports["2024_Q3"].financial_data.line_items[0].line_name
        == "Cash and Cash Equivalents"
    )


def test_load_workspace_state_defaults(temp_workspace_env):
    # Ticker doesn't have an existing file, should return a default WorkspaceContext
    state = load_workspace_state("AAPL")
    assert isinstance(state, WorkspaceContext)
    assert state.metadata.ticker == "AAPL"
    assert state.reports == {}
    assert state.company_data.quarterly_financials == []


def test_save_and_load_workspace_state(temp_workspace_env):
    ticker = "MSFT"
    state = load_workspace_state(ticker)
    state.metadata.company_name = "Microsoft Corporation"

    # Add a report to the state
    report = TemporalBlackboard(
        fiscal_year=2025,
        fiscal_period="FY",
        is_quarterly=False,
    )
    report.financial_data.revenue = 245000000000.0
    state.reports["2025_FY"] = report

    # Save state
    save_workspace_state(ticker, state)

    # Check that file exists in the temp workspace directory
    base_dir = Path(temp_workspace_env.base_workspace_dir)
    state_file = base_dir / ticker / "workspace_state.json"
    assert state_file.exists()

    # Load and verify contents
    loaded = load_workspace_state(ticker)
    assert loaded.metadata.ticker == "MSFT"
    assert loaded.metadata.company_name == "Microsoft Corporation"
    assert "2025_FY" in loaded.reports
    assert loaded.reports["2025_FY"].financial_data.revenue == 245000000000.0


def test_atomic_file_swap_on_crash(temp_workspace_env, monkeypatch):
    ticker = "TSLA"
    state = WorkspaceContext(metadata=CompanyMetadata(ticker=ticker))

    # Mock os.replace to raise an error and check if tmp file is created but original is untouched

    replace_called = False

    def faulty_replace(src, dst):
        nonlocal replace_called
        replace_called = True
        raise OSError("Simulated atomic swap disk error")

    monkeypatch.setattr("os.replace", faulty_replace)

    # Save should raise WorkspaceError because of replace failure
    with pytest.raises(WorkspaceError):
        save_workspace_state(ticker, state)

    base_dir = Path(temp_workspace_env.base_workspace_dir)
    state_file = base_dir / ticker / "workspace_state.json"
    tmp_file = base_dir / ticker / "workspace_state.json.tmp"

    assert replace_called is True
    # The actual file should not have been updated, but the temp file remains (or got written)
    assert not state_file.exists()
    assert tmp_file.exists()


def test_load_workspace_state_corrupt_json(temp_workspace_env):
    ticker = "NVDA"
    base_dir = Path(temp_workspace_env.base_workspace_dir)
    workspace_dir = base_dir / ticker
    workspace_dir.mkdir(parents=True, exist_ok=True)
    state_file = workspace_dir / "workspace_state.json"

    # Write corrupt JSON
    with open(state_file, "w", encoding="utf-8") as f:
        f.write("{invalid json state data")

    # Loading should raise WorkspaceError
    with pytest.raises(WorkspaceError) as exc_info:
        load_workspace_state(ticker)
    assert "Failed to load" in str(exc_info.value)
