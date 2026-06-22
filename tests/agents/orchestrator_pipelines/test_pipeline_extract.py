import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.agents.extractor_orchestrator import Extractor
from src.agents.blackboard_orchestrator import BlackboardOrchestrator
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    CompanyMetadata,
    TemporalBlackboard,
    WorkspaceContext,
)
from src.core.exceptions import WorkspaceError


@patch("src.agents.extractor_orchestrator.load_config")
@patch("src.agents.extractor_orchestrator.Extractor.extract_single_file")
@patch("src.agents.curator_agent.CuratorAgent")
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


@patch("src.agents.extractor_orchestrator.load_config")
@patch("src.agents.extractor_orchestrator.Extractor.extract_single_file")
@patch("src.agents.curator_agent.CuratorAgent")
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


@patch("src.agents.extractor_orchestrator.load_config")
@patch("src.agents.curator_agent.CuratorAgent")
@patch("src.agents.extractor_orchestrator.get_llm_client")
def test_extract_different_document_types(
    mock_get_llm, mock_curator, mock_load_config, tmp_path
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
    mock_chat = MagicMock()
    mock_chat.send_message.return_value = '{"thought": "Finalizing", "tool": "finalize", "arguments": {"economic_moat": "Wide", "economic_moat_rationale": "Strong moat", "margin_outlook": "Stable", "margin_magnitude": "0 pp", "margin_rationale": "...", "growth_outlook": "Stable", "growth_magnitude": "0 pp", "growth_rationale": "..."}}'
    mock_chat.get_history.return_value = []
    mock_llm.create_chat.return_value = mock_chat
    mock_llm.generate.return_value = mock_chat.send_message.return_value
    mock_get_llm.return_value = mock_llm

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

    assert "Economic Moat" in content
    assert "EBITA Margin Outlook" in content
    assert "Rating: **Wide**" in content
    assert "## EBITA\n" not in content
    assert "## Invested Capital\n" not in content


@patch("src.agents.extractor_orchestrator.load_config")
@patch("src.agents.curator_agent.CuratorAgent")
@patch("src.agents.extractor_orchestrator.get_llm_client")
def test_extract_financials_stages(
    mock_get_llm, mock_curator, mock_load_config, tmp_path
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
    mock_get_llm.return_value = mock_llm

    mock_chat = MagicMock()
    mock_chat.get_history.return_value = []
    current_sys_prompt = ""

    def mock_send_message(message, tool_responses=None):
        prompt_content = message or ""
        if tool_responses:
            prompt_content += "\n".join(
                f"observation from {r['name']}: {r['content']}" for r in tool_responses
            )
        return mock_generate(prompt_content, system_prompt=current_sys_prompt)

    mock_chat.send_message.side_effect = mock_send_message

    def mock_create_chat(system_prompt=None, tools=None, model=None, temperature=0.1):
        nonlocal current_sys_prompt
        current_sys_prompt = system_prompt
        return mock_chat

    mock_llm.create_chat.side_effect = mock_create_chat

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
            return '{"thought": "Finalizing", "tool": "finalize", "arguments": {"line_items": [{"line_name": "Revenue", "value": 1000.0, "category": "income_statement", "operating": true, "calculated": false}, {"line_name": "Cash", "value": 500.0, "category": "current_assets", "operating": true, "calculated": false}]}}'
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

    extractor = Extractor()

    from src.tools.keyword_search import find_keyword_contexts
    from src.agents.extractor_agents.extractor_financials import (
        extract_financial_statements,
        run_diluted_shares_agent,
        run_organic_growth_agent,
        run_interpretation_agent,
        calculate_deterministic_metrics,
    )
    from src.agents.extractor_agents.extractor_financials_agents.ebita_agent import (
        run_ebita_agent,
    )
    from src.agents.extractor_agents.extractor_financials_agents.tax_agent import (
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
    company_metadata = CompanyMetadata(ticker="TEST")
    workspace_state = WorkspaceContext(metadata=company_metadata)
    parsed_documents = {"20240901_annual_filing.md": content}
    period_key = "2024_FY"

    report = TemporalBlackboard(
        fiscal_year=2024, fiscal_period="FY", is_quarterly=False
    )
    report.financial_data.raw_income_statement_markdown = "| Revenue | 500 |"
    report.financial_data.raw_balance_sheet_markdown = "| Assets | 100 |"
    workspace_state.reports[period_key] = report

    interpreted = run_interpretation_agent(
        client=extractor.llm,
        extracted_line_items=line_items,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key=period_key,
        is_quarterly=False,
    )
    assert len(interpreted) == 2
    assert interpreted[0].operating is True

    # 4. Test run_diluted_shares_agent & run_organic_growth_agent
    basic_shares, diluted_shares = run_diluted_shares_agent(
        client=extractor.llm,
        parsed_documents=parsed_documents,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key=period_key,
        is_quarterly=False,
    )
    assert basic_shares == 100.0
    assert diluted_shares == 110.0

    simple_growth, organic_growth, revenue_val = run_organic_growth_agent(
        client=extractor.llm,
        parsed_documents=parsed_documents,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key=period_key,
        is_quarterly=False,
    )
    assert simple_growth == 0.10
    assert organic_growth == 0.08
    assert revenue_val == 1000.0

    # 5. Test calculate_deterministic_metrics
    op_inc, ebita, ebita_adjustments = run_ebita_agent(
        client=extractor.llm,
        parsed_documents=parsed_documents,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key=period_key,
        is_quarterly=False,
    )
    inc_bt, rep_tax, adj_taxes, tax_adjustments = run_tax_agent(
        client=extractor.llm,
        parsed_documents=parsed_documents,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key=period_key,
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


@patch("src.agents.extractor_orchestrator.load_config")
@patch("src.agents.extractor_orchestrator.Extractor.extract_single_file")
@patch("src.agents.curator_agent.CuratorAgent")
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


@patch("src.agents.blackboard_orchestrator.run_metadata_agent")
def test_single_agent_extract_metadata(mock_run_metadata, temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()

    mock_run_metadata.return_value = CompanyMetadata(
        ticker=ticker, company_name="Mock Apple Inc."
    )

    asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="metadata"))

    mock_run_metadata.assert_called_once()
    state = load_workspace_state(ticker)
    assert state.metadata_status == "completed"
    assert state.metadata.company_name == "Mock Apple Inc."


def test_single_agent_extract_missing_metadata(temp_workspace_env):
    ticker = "AAPL"
    orchestrator = BlackboardOrchestrator()

    with pytest.raises(WorkspaceError) as exc_info:
        asyncio.run(
            orchestrator.run_pipeline(ticker, stage="extract", agent="balance_sheet")
        )

    assert "Company metadata extraction must be completed first" in str(exc_info.value)


def test_single_agent_extract_shares_missing_prereq(temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker=ticker, company_name="Mock Apple Inc.")
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()

    with pytest.raises(WorkspaceError) as exc_info:
        asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="shares"))

    assert (
        "Income statement must be completed for at least one period before running shares agent"
        in str(exc_info.value)
    )


@patch("src.agents.blackboard_orchestrator.run_diluted_shares_agent")
def test_single_agent_extract_shares_success(mock_run_shares, temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker=ticker, company_name="Mock Apple Inc.")

    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
        income_statement_status="completed",
    )
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()
    mock_run_shares.return_value = (1000.0, 1020.0)

    with patch("src.agents.ingester.Ingester.load_parsed_registry") as mock_registry:
        mock_registry.return_value = {
            "h1": {
                "new_filename": "20240801_10-Q.md",
                "fiscal_year": 2024,
                "fiscal_quarter": "Q3",
                "document_type": "quarterly_filing",
            }
        }

        asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="shares"))

    mock_run_shares.assert_called_once()
    updated_state = load_workspace_state(ticker)
    assert updated_state.reports["2024_Q3"].shares_status == "completed"
    assert updated_state.reports["2024_Q3"].financial_data.basic_shares == 1000.0
    assert updated_state.reports["2024_Q3"].financial_data.diluted_shares == 1020.0


@patch("src.agents.blackboard_orchestrator.run_balance_sheet_agent")
def test_pipeline_metadata_gating(mock_run_bs, temp_workspace_env):
    ticker = "AAPL"
    state = load_workspace_state(ticker)
    state.metadata_status = "failed"
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()

    asyncio.run(orchestrator.run_pipeline(ticker, stage="extract"))

    mock_run_bs.assert_not_called()
