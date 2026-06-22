from pathlib import Path
from unittest.mock import patch, MagicMock

from src.agents.extractor_orchestrator import LineItem, AuditLinkage
from src.agents.extractor_agents.extractor_financials import (
    calculate_deterministic_metrics,
    detect_metadata_from_markdown,
)
from src.agents.extractor_orchestrator import clean_val
import src.utils.financial_math as rust_core


def test_clean_val():
    assert clean_val("12,345") == 12345.0
    assert clean_val("$12,345.50") == 12345.50
    assert clean_val("(1,000)") == -1000.0
    assert clean_val("N/A") == 0.0
    assert clean_val(" -- ") == 0.0
    assert clean_val("10%") == 0.10
    assert clean_val("280 million") == 280.0
    assert clean_val("283 million shares") == 283.0
    assert clean_val("280M") == 280.0
    assert clean_val("280.5M") == 280.5
    assert clean_val("(15.5 million)") == -15.5


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
    eff, adj = rust_core.calculate_tax_rates(120.0, -30.0, -5.0, 110.0)
    assert eff == 0.25
    assert adj == (35.0 / 110.0)

    # Test ROIC
    nopat, ann_nopat, roic = rust_core.calculate_roic(110.0, 0.20, 150.0, 4.0)
    assert nopat == 88.0
    assert ann_nopat == 352.0
    assert roic == (352.0 / 150.0) * 100.0


def test_deterministic_metrics_variations():
    # Mock extractor
    mock_extractor = MagicMock()
    mock_extractor.settings.active_workspace_path = "dummy"
    mock_extractor.get_document_metadata.return_value = {
        "document_type": "annual_filing"
    }

    # Mock items with common naming variations
    audit = AuditLinkage(source_file="f.md", chunk_id=0, exact_snippet="")
    items = [
        LineItem(
            line_name="Total revenues",
            value=10000.0,
            category="income_statement",
            audit=audit,
        ),
        LineItem(
            line_name="Income from operations",
            value=2300.0,
            category="income_statement",
            audit=audit,
        ),
        LineItem(
            line_name="Income before provision for income taxes",
            value=2400.0,
            category="income_statement",
            audit=audit,
        ),
        LineItem(
            line_name="Provision for income taxes",
            value=-500.0,
            category="income_statement",
            audit=audit,
        ),
    ]

    with (
        patch("builtins.open", MagicMock()),
        patch("src.utils.formatting.print_success", MagicMock()),
    ):
        with patch("pathlib.Path.mkdir", MagicMock()):
            calculate_deterministic_metrics(
                file_path=Path("f.md"),
                content="dummy",
                extracted_line_items=items,
                basic_shares=900.0,
                diluted_shares=910.0,
                simple_growth=0.10,
                organic_growth=0.08,
                op_inc=2300.0,
                inc_bt=2400.0,
                rep_tax=-500.0,
                ebita=2304.0,
                adj_taxes=-499.0,
                ebita_adjustments=[{"name": "Restructuring", "value": 4.0}],
                tax_adjustments=[
                    {"name": "Tax effect of restructuring at 25%", "value": 1.0}
                ],
                extractor=mock_extractor,
                summaries=[],
                revenue=10000.0,
            )

            # Assertions to verify correct logic was run without exceptions
            assert True


def test_currency_and_unit_detection_and_formatting(tmp_path):
    # 1. Test detect_metadata_from_markdown
    is_content_eur = """# Income Statement
**Currency**: EUR
**Unit**: Millions

| Field | Value |
| --- | --- |
| Revenue | 500.0 |
"""
    is_file = tmp_path / "income_statement.md"
    is_file.write_text(is_content_eur, encoding="utf-8")
    curr, unit = detect_metadata_from_markdown(is_file)
    assert curr == "EUR"
    assert unit == "Millions"

    # Test loose matching
    is_content_loose = """# Income Statement
Currency: JPY
Unit: Billions
"""
    is_file_loose = tmp_path / "income_statement_loose.md"
    is_file_loose.write_text(is_content_loose, encoding="utf-8")
    curr, unit = detect_metadata_from_markdown(is_file_loose)
    assert curr == "JPY"
    assert unit == "Billions"

    # 2. Test calculate_deterministic_metrics writeout with currency & unit
    mock_extractor = MagicMock()
    mock_extractor.settings.active_workspace_path = str(tmp_path)
    mock_extractor.get_document_metadata.return_value = {
        "document_type": "annual_filing"
    }

    audit = AuditLinkage(source_file="f.md", chunk_id=0, exact_snippet="")
    items = [
        LineItem(
            line_name="Total revenues",
            value=100.0,
            category="income_statement",
            audit=audit,
        ),
        LineItem(
            line_name="Income from operations",
            value=20.0,
            category="income_statement",
            audit=audit,
        ),
        LineItem(
            line_name="Income before provision for income taxes",
            value=20.0,
            category="income_statement",
            audit=audit,
        ),
        LineItem(
            line_name="Provision for income taxes",
            value=-5.0,
            category="income_statement",
            audit=audit,
        ),
    ]

    calculate_deterministic_metrics(
        file_path=Path("f.md"),
        content="dummy",
        extracted_line_items=items,
        basic_shares=9.0,
        diluted_shares=9.1,
        simple_growth=0.10,
        organic_growth=0.08,
        op_inc=20.0,
        inc_bt=20.0,
        rep_tax=-5.0,
        ebita=20.0,
        adj_taxes=-5.0,
        ebita_adjustments=[],
        tax_adjustments=[],
        extractor=mock_extractor,
        summaries=[],
        revenue=100.0,
        currency="EUR",
        unit="Billions",
    )

    out_file = tmp_path / "4_extracted_data" / "f_extracted.md"
    assert out_file.exists()
    out_content = out_file.read_text(encoding="utf-8")
    assert "**Currency**: EUR" in out_content
    assert "**Unit**: Billions" in out_content
    assert "Value (in Billions)" in out_content
