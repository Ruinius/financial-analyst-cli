import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError

from src.pipeline.extractor import AuditLinkage, LineItem, Extractor, clean_val
import src.rust_core as rust_core


def test_pydantic_schemas():
    # Valid schema
    audit = AuditLinkage(
        source_file="20230930_annual_filing.md",
        chunk_id=1,
        exact_snippet="Revenue of $100M",
    )
    item = LineItem(
        line_name="Revenue",
        value=100.0,
        operating=True,
        calculated=False,
        category="income_statement",
        standardized_name="revenue",
        audit=audit,
    )
    assert item.line_name == "Revenue"
    assert item.value == 100.0
    assert item.audit.chunk_id == 1

    # Invalid schema (missing fields)
    with pytest.raises(ValidationError):
        LineItem(line_name="Revenue", value=100.0)


def test_clean_val():
    assert clean_val("12,345") == 12345.0
    assert clean_val("$12,345.50") == 12345.50
    assert clean_val("(1,000)") == -1000.0
    assert clean_val("N/A") == 0.0
    assert clean_val(" -- ") == 0.0
    assert clean_val("10%") == 0.10


def test_calculations_logic():
    # Test EBITA
    ebita, margin = rust_core.calculate_ebita(100.0, 500.0, 10.0)
    assert ebita == 110.0
    assert margin == 22.0

    # Test Invested Capital
    nwc, nltoa, ic, turnover = rust_core.calculate_invested_capital(
        200.0, 150.0, 400.0, 300.0, 500.0
    )
    assert nwc == 50.0
    assert nltoa == 100.0
    assert ic == 150.0
    assert turnover == 500.0 / 150.0

    # Test Tax Rates
    eff, adj = rust_core.calculate_tax_rates(120.0, 30.0, 90.0, 5.0, 110.0)
    assert eff == -0.25
    assert adj == -(35.0 / 110.0)

    # Test ROIC
    nopat, ann_nopat, roic = rust_core.calculate_roic(110.0, 0.20, 150.0, 4.0)
    assert nopat == 88.0
    assert ann_nopat == 352.0
    assert roic == (352.0 / 150.0) * 100.0


@patch("src.pipeline.extractor.load_config")
@patch("src.pipeline.extractor.LLMClient")
@patch("src.pipeline.extractor.search_investopedia")
def test_classifier(mock_search, mock_llm_class, mock_load_config, tmp_path):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "6_company_context").mkdir()

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_settings.active_ticker = "AAPL"
    mock_load_config.return_value = mock_settings

    mock_llm = MagicMock()
    mock_llm.generate.return_value = "operating"
    mock_llm_class.return_value = mock_llm

    mock_search.return_value = "operating expenses are operating items"

    extractor = Extractor()

    # Test classification using LLM / Search fallback
    res = extractor.classify_line_item("Research and Development", "income_statement")
    assert res is True


@patch("src.pipeline.extractor.load_config")
@patch("src.pipeline.extractor.LLMClient")
@patch("src.pipeline.extractor.Extractor.extract_single_file")
def test_extractor_limit(mock_extract, mock_llm_client, mock_load_config, tmp_path):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "2_parsed_data").mkdir()
    (workspace / "4_extracted_data").mkdir()

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_load_config.return_value = mock_settings

    # Create 3 parsed files
    parsed_dir = workspace / "2_parsed_data"
    for i in range(3):
        f = parsed_dir / f"2023092{i}_annual_filing.md"
        f.write_text("dummy", encoding="utf-8")

    extractor = Extractor()

    mock_extract.__name__ = "extract_single_file"

    # Run with limit=2
    extractor.run_extraction(limit=2)

    # Verify extract_single_file was called exactly 2 times
    assert mock_extract.call_count == 2


@patch("src.pipeline.extractor.load_config")
@patch("src.pipeline.extractor.LLMClient")
@patch("src.pipeline.extractor.Extractor.extract_single_file")
def test_extractor_ignores_readme_and_hidden(
    mock_extract, mock_llm_client, mock_load_config, tmp_path
):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "2_parsed_data").mkdir()
    (workspace / "4_extracted_data").mkdir()

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_load_config.return_value = mock_settings

    parsed_dir = workspace / "2_parsed_data"
    (parsed_dir / "20230920_annual_filing.md").write_text("dummy", encoding="utf-8")
    (parsed_dir / "README.md").write_text("readme", encoding="utf-8")
    (parsed_dir / ".hidden_file").write_text("hidden", encoding="utf-8")
    (parsed_dir / "parsed_data.csv").write_text(
        "source_file,extracted_at\n", encoding="utf-8"
    )

    extractor = Extractor()
    mock_extract.__name__ = "extract_single_file"

    extractor.run_extraction()

    assert mock_extract.call_count == 1
    args, kwargs = mock_extract.call_args
    assert args[0].name == "20230920_annual_filing.md"
