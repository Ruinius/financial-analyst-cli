import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError
from pathlib import Path

from src.pipeline.extractor_orchestrator import (
    AuditLinkage,
    LineItem,
    Extractor,
    clean_val,
    FinancialStatementsExtraction,
    QualitativeAssessment,
    TranscriptExtraction,
    GeneralSummary,
)
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
        audit=audit,
    )
    assert item.line_name == "Revenue"
    assert item.value == 100.0
    assert item.audit.chunk_id == 1

    # Invalid schema (missing fields)
    with pytest.raises(ValidationError):
        LineItem(line_name="Revenue", value=100.0)

    # Test document-specific extraction schemas
    fin_extraction = FinancialStatementsExtraction(line_items=[item])
    assert len(fin_extraction.line_items) == 1

    qual_assessment = QualitativeAssessment(
        economic_moat="Wide",
        economic_moat_rationale="High switching costs",
        margin_outlook="Stable",
        margin_magnitude="0 pp",
        margin_rationale="Stable raw material costs",
        growth_outlook="Stable",
        growth_magnitude="0 pp",
        growth_rationale="Steady demand",
    )
    assert qual_assessment.economic_moat == "Wide"

    transcript_ex = TranscriptExtraction(
        tone="Optimistic",
        inconsistency="None noted",
        summary="Q4 was strong with record sales",
    )
    assert transcript_ex.tone == "Optimistic"

    gen_summary = GeneralSummary(summary="General company updates")
    assert gen_summary.summary == "General company updates"


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


@patch("src.pipeline.extractor_orchestrator.load_config")
@patch("src.pipeline.extractor_orchestrator.Extractor.extract_single_file")
def test_extractor_limit(mock_extract, mock_load_config, tmp_path):
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


@patch("src.pipeline.extractor_orchestrator.load_config")
@patch("src.pipeline.extractor_orchestrator.Extractor.extract_single_file")
def test_extractor_ignores_readme_and_hidden(mock_extract, mock_load_config, tmp_path):
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


def test_get_chunk_by_id():
    from src.pipeline.extractor_orchestrator import get_chunk_by_id

    content = """# Metadata Table
Some headers here

---
<!-- CHUNK_START: 1 -->
This is chunk 1 content
<!-- CHUNK_END: 1 -->
---
<!-- CHUNK_START: 2 -->
This is chunk 2 content
<!-- CHUNK_END: 2 -->
"""
    # Test chunk 0 (everything before chunk 1 start)
    chunk_0 = get_chunk_by_id(content, 0)
    assert "# Metadata Table" in chunk_0
    assert "Some headers here" in chunk_0
    assert "CHUNK_START" not in chunk_0

    # Test chunk 1
    chunk_1 = get_chunk_by_id(content, 1)
    assert chunk_1 == "This is chunk 1 content"

    # Test chunk 2
    chunk_2 = get_chunk_by_id(content, 2)
    assert chunk_2 == "This is chunk 2 content"

    # Test non-existent chunk
    chunk_3 = get_chunk_by_id(content, 3)
    assert chunk_3 == ""


@patch("src.pipeline.extractor_orchestrator.load_config")
@patch("src.pipeline.extractor_orchestrator.LLMClient")
def test_extract_different_document_types(mock_llm_class, mock_load_config, tmp_path):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "2_parsed_data").mkdir()
    (workspace / "4_extracted_data").mkdir()
    (workspace / "6_company_context").mkdir()

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_settings.active_ticker = "AAPL"
    mock_load_config.return_value = mock_settings

    mock_llm = MagicMock()
    mock_llm.generate.return_value = '{"thought": "Finalizing", "tool": "finalize", "arguments": {"economic_moat": "Wide", "economic_moat_rationale": "Strong moat", "margin_outlook": "Stable", "margin_magnitude": "0 pp", "margin_rationale": "...", "growth_outlook": "Stable", "growth_magnitude": "0 pp", "growth_rationale": "..."}}'
    mock_llm_class.return_value = mock_llm

    extractor = Extractor()

    # Create dummy parsed file representing an analyst report
    parsed_file = workspace / "2_parsed_data" / "20240901_analyst_report.md"
    parsed_file.write_text(
        """# Document Metadata & Chunk Inventory (chunk_id=0)
| Metadata Key | Value |
| --- | --- |
| Document Type | analyst_report |

---
<!-- CHUNK_START: 1 -->
Analyst discussion of moat and growth
<!-- CHUNK_END: 1 -->
---""",
        encoding="utf-8",
    )

    extractor.extract_single_file(parsed_file)

    extracted_file = (
        workspace / "4_extracted_data" / "20240901_analyst_report_extracted.md"
    )
    assert extracted_file.exists()
    content = extracted_file.read_text(encoding="utf-8")

    # Verify analyst report specific formatting (contains moat, does not contain EBITA calculations)
    assert "Economic Moat" in content
    assert "EBITA Margin Outlook" in content
    assert "Rating: **Wide**" in content
    assert "## EBITA\n" not in content
    assert "## Invested Capital\n" not in content


@patch("src.pipeline.extractor_orchestrator.load_config")
@patch("src.pipeline.extractor_orchestrator.LLMClient")
def test_extract_financials_stages(mock_llm_class, mock_load_config, tmp_path):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "2_parsed_data").mkdir()
    (workspace / "4_extracted_data").mkdir()
    (workspace / "6_company_context").mkdir()

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_settings.active_ticker = "AAPL"
    mock_load_config.return_value = mock_settings

    mock_llm = MagicMock()

    def mock_generate(prompt, system_prompt=None, stream_thinking=True):
        p_lower = prompt.lower()
        sys_lower = (system_prompt or "").lower()
        if (
            "perform a quality check on the following extracted income statement"
            in sys_lower
        ):
            return "PASSED"
        if (
            "perform a quality check on the following extracted balance sheet"
            in sys_lower
        ):
            return "PASSED"
        if (
            "extract all financial statement line items from the provided markdown statement"
            in sys_lower
            or "extract all financial statement line items from the provided markdown statement"
            in p_lower
        ):
            if "revenue" in p_lower:
                return '{"line_items": [{"line_name": "Revenue", "value": "1000", "category": "income_statement", "exact_snippet": "Revenue 1000"}]}'
            else:
                return '{"line_items": [{"line_name": "Cash", "value": "500", "category": "current_assets", "exact_snippet": "Cash 500"}]}'
        if "basic and diluted shares" in p_lower:
            return '{"thought": "Finalizing", "tool": "finalize", "arguments": {"basic_shares": "100.0", "diluted_shares": "110.0"}}'
        if "simple and organic revenue growth" in p_lower:
            return '{"thought": "Finalizing", "tool": "finalize", "arguments": {"simple_growth": "10%", "organic_growth": "8%"}}'
        if (
            "statement interpretation agent" in sys_lower
            or "currently extracted line items" in p_lower
        ):
            return '{"line_items": [{"line_name": "Revenue", "value": 1000.0, "category": "income_statement", "operating": true, "calculated": false}, {"line_name": "Cash", "value": 500.0, "category": "current_assets", "operating": true, "calculated": false}]}'
        if (
            "ebita adjustments and tax provisions" in sys_lower
            or "reported operating income" in p_lower
        ):
            return '{"operating_ebita": 1000.0, "adjusted_taxes": 250.0}'
        if "income statement" in sys_lower or "income statement" in p_lower:
            if "observation from check_income_statement_quality" in p_lower:
                return '{"thought": "Quality check passed. Finalizing.", "tool": "finalize", "arguments": {}}'
            if "observation from append_markdown" in p_lower:
                return '{"thought": "Let me run a quality check.", "tool": "check_income_statement_quality", "arguments": {}}'
            if "observation from get_chunk_by_id" in p_lower:
                return '{"thought": "Let me write the income statement content.", "tool": "append_markdown", "arguments": {"text": "Revenue: 1000"}}'
            if "observation from find_keyword_contexts" in p_lower:
                return '{"thought": "Let me fetch chunk 1.", "tool": "get_chunk_by_id", "arguments": {"chunk_id": 1}}'
            return '{"thought": "Let me search for keyword context.", "tool": "find_keyword_contexts", "arguments": {"keywords": ["Revenue"]}}'
        if "balance sheet" in sys_lower or "balance sheet" in p_lower:
            if "observation from check_balance_sheet_quality" in p_lower:
                return '{"thought": "Quality check passed. Finalizing.", "tool": "finalize", "arguments": {}}'
            if "observation from append_markdown" in p_lower:
                return '{"thought": "Let me run a quality check.", "tool": "check_balance_sheet_quality", "arguments": {}}'
            if "observation from get_chunk_by_id" in p_lower:
                return '{"thought": "Let me write the balance sheet content.", "tool": "append_markdown", "arguments": {"text": "Cash: 500"}}'
            if "observation from find_keyword_contexts" in p_lower:
                return '{"thought": "Let me fetch chunk 1.", "tool": "get_chunk_by_id", "arguments": {"chunk_id": 1}}'
            return '{"thought": "Let me search for keyword context.", "tool": "find_keyword_contexts", "arguments": {"keywords": ["Balance Sheet"]}}'
        return (
            '{"thought": "No match. Finalizing.", "tool": "finalize", "arguments": {}}'
        )

    mock_llm.generate.side_effect = mock_generate
    mock_llm_class.return_value = mock_llm

    extractor = Extractor()

    from src.pipeline.extractor_financials import (
        find_keyword_contexts,
        extract_financial_statements,
        run_diluted_shares_agent,
        run_organic_growth_agent,
        run_interpretation_agent,
        calculate_deterministic_metrics,
    )

    content = """<!-- CHUNK_START: 1 -->
Revenue of $1000. Cash of $500. Shares outstanding basic shares diluted shares organic growth.
<!-- CHUNK_END: 1 -->"""

    # 1. Test find_keyword_contexts
    snippets = find_keyword_contexts(content, ["shares", "revenue"], window=20)
    assert len(snippets) > 0
    assert any(
        "shares" in sn["snippet"].lower() or "revenue" in sn["snippet"].lower()
        for sn in snippets
    )

    # 2. Test extract_financial_statements
    summaries = []
    line_items = extract_financial_statements(
        file_path=Path("20240901_annual_filing.md"),
        content=content,
        sorted_chunk_ids=[1],
        extractor=extractor,
        summaries=summaries,
    )
    assert len(line_items) == 2
    assert line_items[0].line_name == "Revenue"
    assert line_items[1].line_name == "Cash"

    # 3. Test run_interpretation_agent
    interpreted = run_interpretation_agent(
        line_items, Path("20240901_annual_filing.md"), extractor
    )
    assert len(interpreted) == 2
    assert interpreted[0].operating is True

    # 4. Test run_diluted_shares_agent & run_organic_growth_agent
    basic_shares, diluted_shares = run_diluted_shares_agent(content, extractor)
    assert basic_shares == 100.0
    assert diluted_shares == 110.0

    simple_growth, organic_growth = run_organic_growth_agent(content, 1000.0, extractor)
    assert simple_growth == 0.10
    assert organic_growth == 0.08

    # 5. Test calculate_deterministic_metrics
    success = calculate_deterministic_metrics(
        file_path=Path("20240901_annual_filing.md"),
        content=content,
        extracted_line_items=interpreted,
        basic_shares=basic_shares,
        diluted_shares=diluted_shares,
        simple_growth=simple_growth,
        organic_growth=organic_growth,
        extractor=extractor,
        summaries=summaries,
    )
    assert success is True

    # Check that output file is written
    out_file = workspace / "4_extracted_data" / "20240901_annual_filing_extracted.md"
    assert out_file.exists()
    out_content = out_file.read_text(encoding="utf-8")
    assert "Revenue" in out_content
    assert "EBITA" in out_content
    assert "100.0" in out_content
    assert "110.0" in out_content
