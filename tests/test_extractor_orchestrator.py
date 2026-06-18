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
import src.utils.math as rust_core


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


@patch("src.pipeline.extractor_orchestrator.load_config")
@patch("src.pipeline.extractor_orchestrator.Extractor.extract_single_file")
@patch("src.pipeline.curator_agent.CuratorAgent")
def test_extractor_limit(mock_curator, mock_extract, mock_load_config, tmp_path):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "2_parsed_data").mkdir()
    (workspace / "4_extracted_data").mkdir()

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_settings.active_ticker = "AAPL"
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
@patch("src.pipeline.curator_agent.CuratorAgent")
def test_extractor_ignores_readme_and_hidden(
    mock_curator, mock_extract, mock_load_config, tmp_path
):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "2_parsed_data").mkdir()
    (workspace / "4_extracted_data").mkdir()

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_settings.active_ticker = "AAPL"
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
@patch("src.pipeline.curator_agent.CuratorAgent")
@patch("src.pipeline.extractor_orchestrator.LLMClient")
def test_extract_different_document_types(
    mock_llm_class, mock_curator, mock_load_config, tmp_path
):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "2_parsed_data").mkdir()
    (workspace / "4_extracted_data").mkdir()
    (workspace / "AAPL_extract_learning.md").write_text(
        "# Extract Learning\n", encoding="utf-8"
    )

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
@patch("src.pipeline.curator_agent.CuratorAgent")
@patch("src.pipeline.extractor_orchestrator.LLMClient")
def test_extract_financials_stages(
    mock_llm_class, mock_curator, mock_load_config, tmp_path
):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "2_parsed_data").mkdir()
    (workspace / "4_extracted_data").mkdir()
    (workspace / "AAPL_extract_learning.md").write_text(
        "# Extract Learning\n", encoding="utf-8"
    )

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
        if "extract all financial statement line items" in sys_lower:
            if "revenue" in p_lower:
                return '{"line_items": [{"line_name": "Revenue", "value": "1000", "category": "income_statement", "exact_snippet": "Revenue 1000"}]}'
            else:
                return '{"line_items": [{"line_name": "Cash", "value": "500", "category": "current_assets", "exact_snippet": "Cash 500"}]}'
        if "basic and diluted shares" in sys_lower:
            return '{"thought": "Finalizing", "tool": "finalize", "arguments": {"basic_shares": "100.0", "diluted_shares": "110.0"}}'
        if (
            "simple revenue growth, organic revenue growth, and total revenue"
            in sys_lower
        ):
            return '{"thought": "Finalizing", "tool": "finalize", "arguments": {"simple_growth": "10%", "organic_growth": "8%", "revenue": "1000.0"}}'
        if "statement interpretation agent" in sys_lower:
            return '{"line_items": [{"line_name": "Revenue", "value": 1000.0, "category": "income_statement", "operating": true, "calculated": false}, {"line_name": "Cash", "value": 500.0, "category": "current_assets", "operating": true, "calculated": false}]}'
        if "ebita adjustments" in sys_lower:
            return '{"thought": "Finalizing", "tool": "finalize", "arguments": {"operating_income": 1000.0, "operating_ebita": 1000.0, "ebita_adjustments": []}}'
        if "tax provisions and adjustments" in sys_lower:
            return '{"thought": "Finalizing", "tool": "finalize", "arguments": {"income_before_taxes": 1200.0, "reported_tax_provision": -250.0, "adjusted_taxes": -250.0, "tax_adjustments": []}}'
        if "income statement" in sys_lower:
            if "observation from check_income_statement_quality" in p_lower:
                return '{"thought": "Quality check passed. Finalizing.", "tool": "finalize", "arguments": {}}'
            if "observation from append_markdown" in p_lower:
                return '{"thought": "Let me run a quality check.", "tool": "check_income_statement_quality", "arguments": {}}'
            if "observation from get_chunk_by_id" in p_lower:
                return '{"thought": "Let me write the income statement content.", "tool": "append_markdown", "arguments": {"text": "Revenue: 1000"}}'
            if "observation from find_keyword_contexts" in p_lower:
                return '{"thought": "Let me fetch chunk 1.", "tool": "get_chunk_by_id", "arguments": {"chunk_id": 1}}'
            return '{"thought": "Let me search for keyword context.", "tool": "find_keyword_contexts", "arguments": {"keywords": ["Revenue"]}}'
        if "balance sheet" in sys_lower:
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

    from src.utils.tools import find_keyword_contexts
    from src.pipeline.extractor_agents.extractor_financials import (
        extract_financial_statements,
        run_diluted_shares_agent,
        run_organic_growth_agent,
        run_interpretation_agent,
        calculate_deterministic_metrics,
    )
    from src.pipeline.extractor_agents.extractor_financials_agents.ebita_agent import (
        run_ebita_agent,
    )
    from src.pipeline.extractor_agents.extractor_financials_agents.tax_agent import (
        run_tax_agent,
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
        line_items, Path("20240901_annual_filing.md"), extractor, is_quarterly=False
    )
    assert len(interpreted) == 2
    assert interpreted[0].operating is True

    # 4. Test run_diluted_shares_agent & run_organic_growth_agent
    basic_shares, diluted_shares = run_diluted_shares_agent(
        content, extractor, is_quarterly=False
    )
    assert basic_shares == 100.0
    assert diluted_shares == 110.0

    simple_growth, organic_growth, revenue_val = run_organic_growth_agent(
        content, extractor, is_quarterly=False
    )
    assert simple_growth == 0.10
    assert organic_growth == 0.08
    assert revenue_val == 1000.0

    # 5. Test calculate_deterministic_metrics
    op_inc, ebita, ebita_adjustments = run_ebita_agent(
        content, extractor, is_quarterly=False
    )
    inc_bt, rep_tax, adj_taxes, tax_adjustments = run_tax_agent(
        content,
        extractor,
        operating_income=op_inc,
        operating_ebita=ebita,
        ebita_adjustments=ebita_adjustments,
        is_quarterly=False,
    )
    success = calculate_deterministic_metrics(
        file_path=Path("20240901_annual_filing.md"),
        content=content,
        extracted_line_items=interpreted,
        basic_shares=basic_shares,
        diluted_shares=diluted_shares,
        simple_growth=simple_growth,
        organic_growth=organic_growth,
        op_inc=op_inc,
        inc_bt=inc_bt,
        rep_tax=rep_tax,
        ebita=ebita,
        adj_taxes=adj_taxes,
        ebita_adjustments=ebita_adjustments,
        tax_adjustments=tax_adjustments,
        extractor=extractor,
        summaries=summaries,
        revenue=revenue_val,
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


def test_deterministic_metrics_variations():
    from src.pipeline.extractor_orchestrator import LineItem, AuditLinkage
    from src.pipeline.extractor_agents.extractor_financials import (
        calculate_deterministic_metrics,
    )

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
        # We also patch Path.mkdir so it doesn't try to create directories
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


@patch("src.pipeline.extractor_orchestrator.load_config")
@patch("src.pipeline.extractor_orchestrator.Extractor.extract_single_file")
@patch("src.pipeline.curator_agent.CuratorAgent")
def test_extractor_files_to_process(
    mock_curator, mock_extract, mock_load_config, tmp_path
):
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    (workspace / "2_parsed_data").mkdir()
    (workspace / "4_extracted_data").mkdir()

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)
    mock_settings.active_ticker = "AAPL"
    mock_load_config.return_value = mock_settings

    # Create 3 parsed files
    parsed_dir = workspace / "2_parsed_data"
    f0 = parsed_dir / "20230920_annual_filing.md"
    f0.write_text("dummy0", encoding="utf-8")
    f1 = parsed_dir / "20230921_annual_filing.md"
    f1.write_text("dummy1", encoding="utf-8")
    f2 = parsed_dir / "20230922_annual_filing.md"
    f2.write_text("dummy2", encoding="utf-8")

    # Add f1 to extracted_registry to check if it's bypassed
    registry_file = workspace / "4_extracted_data" / "extracted_data.csv"
    registry_file.write_text(
        "source_file,extracted_at\n20230921_annual_filing.md,1234.5\n", encoding="utf-8"
    )

    extractor = Extractor()
    mock_extract.__name__ = "extract_single_file"

    # Explicitly run extraction on f1 (which is in the registry) and f0
    extractor.run_extraction(files_to_process=[f1, f0])

    # Should process exactly f1 and f0
    assert mock_extract.call_count == 2
    called_paths = [args[0] for args, _ in mock_extract.call_args_list]
    assert f1 in called_paths
    assert f0 in called_paths
    assert f2 not in called_paths


@patch("src.pipeline.curator_agent.LLMClient")
def test_curator_agent_curate_and_self_healing(mock_llm_class, tmp_path):
    # Setup paths
    workspace = tmp_path / "AAPL"
    workspace.mkdir()
    wiki = workspace / "AAPL_wiki.md"
    extract_learning = workspace / "AAPL_extract_learning.md"
    analyze_learning = workspace / "AAPL_analyze_learning.md"
    model_learning = workspace / "AAPL_model_learning.md"

    # 1. Test ensure_files_exist with a brand new workspace
    from src.pipeline.curator_agent import CuratorAgent

    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(workspace)

    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Updated mock learning file content"
    mock_llm_class.return_value = mock_llm

    curator = CuratorAgent(mock_settings)
    curator._ensure_files_exist(
        "AAPL", wiki, extract_learning, analyze_learning, model_learning
    )

    assert extract_learning.exists()
    content = extract_learning.read_text(encoding="utf-8")
    assert "## balance_sheet" in content
    assert "## income_statement" in content
    assert "## diluted_shares" in content
    assert "## organic growth" in content
    assert "## ebita" in content
    assert "## tax" in content
    assert "## analyst_report" in content
    assert "## transcript" in content
    assert "## other" in content

    # 2. Test self-healing on an old format file
    old_content = (
        "# Ingestion & Extraction Learning: AAPL\n\n"
        "## Fiscal Schedule Mappings\n- Q1: N/A\n\n"
        "## Lessons to Better Ingest & Extract\n- None\n\n"
        "## User Feedback\n<!-- feedback -->\n"
    )
    extract_learning.write_text(old_content, encoding="utf-8")

    # Run ensure_files_exist again which triggers self-healing
    curator._ensure_files_exist(
        "AAPL", wiki, extract_learning, analyze_learning, model_learning
    )

    healed_content = extract_learning.read_text(encoding="utf-8")
    assert "## Preferred Currency & Unit" in healed_content
    assert "## balance_sheet" in healed_content
    assert "## income_statement" in healed_content
    assert "## tax" in healed_content
    assert "## analyst_report" in healed_content
    assert "## transcript" in healed_content
    assert "## other" in healed_content
    assert "## User Feedback" in healed_content

    # 3. Test curate_agent method
    curator.curate_agent("AAPL", "diluted_shares", "Search keywords: weighted average")
    assert mock_llm.generate.call_count == 1
    assert (
        extract_learning.read_text(encoding="utf-8")
        == "Updated mock learning file content"
    )


def test_currency_and_unit_detection_and_formatting(tmp_path):
    from src.pipeline.extractor_agents.extractor_financials import (
        detect_metadata_from_markdown,
        calculate_deterministic_metrics,
    )
    from src.pipeline.extractor_orchestrator import LineItem, AuditLinkage

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
