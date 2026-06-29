import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch

from src.agents.blackboard_orchestrator import BlackboardOrchestrator
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    CompanyMetadata,
    TemporalBlackboard,
)
from src.core.exceptions import WorkspaceError


@pytest.fixture(autouse=True)
def setup_dummy_parsed_file(temp_workspace_env):
    workspace = Path(temp_workspace_env.active_workspace_path)
    parsed_dir = workspace / "2_parsed_data"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    dummy_file = parsed_dir / "dummy_doc.md"
    dummy_file.write_text("Dummy content for testing", encoding="utf-8")


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

    with patch(
        "src.agents.orchestrator_pipelines.ingest.Ingester.load_parsed_registry"
    ) as mock_registry:
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

    with pytest.raises(WorkspaceError):
        asyncio.run(orchestrator.run_pipeline(ticker, stage="extract"))

    mock_run_bs.assert_not_called()


@patch("src.agents.blackboard_orchestrator.run_metadata_agent")
def test_extract_metadata_renaming(mock_run_metadata, temp_workspace_env):
    from src.agents.extractor_agents.metadata_agent import MetadataAgentResult
    from src.agents.orchestrator_pipelines.ingest import Ingester
    from src.core.blackboard import RawDocumentState

    ticker = "AAPL"
    workspace = Path(temp_workspace_env.active_workspace_path)

    # 1. Setup mock result
    mock_run_metadata.return_value = MetadataAgentResult(
        company_metadata=CompanyMetadata(
            ticker=ticker,
            company_name="Mock Apple Inc.",
            description="Mock Apple Description",
        ),
        documents_metadata={
            "dummy_doc.md": {
                "document_date": "2024-10-31",
                "document_type": "quarterly_filing",
                "fiscal_quarter": "Q3",
                "fiscal_year": "2024",
                "period_end_date": "2024-09-30",
            }
        },
    )

    # 2. Setup the registry
    ingester_inst = Ingester()
    registry = {
        "hash123": {
            "file_hash": "hash123",
            "original_filename": "dummy_doc.pdf",
            "new_filename": "dummy_doc.md",
            "document_type": "N/A",
            "document_date": "N/A",
            "fiscal_quarter": "N/A",
            "fiscal_year": "N/A",
            "period_end_date": "N/A",
        }
    }
    ingester_inst.save_parsed_registry(registry)

    # 3. Setup workspace state to track the raw document
    state = load_workspace_state(ticker)
    state.raw_documents = [
        RawDocumentState(
            file_name="dummy_doc.pdf",
            sha256="hash123",
            ingestion_status="completed",
        )
    ]
    save_workspace_state(ticker, state)

    # 4. Setup mock files on disk
    parsed_dir = workspace / "2_parsed_data"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    dummy_parsed = parsed_dir / "dummy_doc.md"
    dummy_parsed.write_text("dummy parsed content", encoding="utf-8")

    archive_dir = workspace / "3_archived_data"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dummy_archived = archive_dir / "dummy_doc.pdf"
    dummy_archived.write_text("dummy archived content", encoding="utf-8")

    # 5. Run metadata extraction pipeline
    orchestrator = BlackboardOrchestrator()
    asyncio.run(orchestrator.run_pipeline(ticker, stage="extract", agent="metadata"))

    # 6. Verify files renamed
    new_parsed = parsed_dir / "20241031_10Q_parsed.md"
    new_archived = archive_dir / "20241031_10Q_parsed.pdf"

    assert not dummy_parsed.exists()
    assert new_parsed.exists()
    assert new_parsed.read_text(encoding="utf-8") == "dummy parsed content"

    assert not dummy_archived.exists()
    assert new_archived.exists()
    assert new_archived.read_text(encoding="utf-8") == "dummy archived content"

    # 7. Verify registry updated
    updated_reg = ingester_inst.load_parsed_registry()
    row = updated_reg["hash123"]
    assert row["new_filename"] == "20241031_10Q_parsed.md"
    assert row["original_filename"] == "20241031_10Q_parsed.pdf"
    assert row["document_date"] == "2024-10-31"
    assert row["document_type"] == "quarterly_filing"
    assert row["fiscal_quarter"] == "Q3"
    assert row["fiscal_year"] == "2024"
    assert row["period_end_date"] == "2024-09-30"

    # 8. Verify workspace state updated
    updated_state = load_workspace_state(ticker)
    assert updated_state.raw_documents[0].file_name == "20241031_10Q_parsed.pdf"


@patch("src.agents.blackboard_orchestrator.run_organic_growth_agent")
def test_extract_target_files_scopes_metric_agents(
    mock_run_org_growth, temp_workspace_env
):
    ticker = "AAPL"
    workspace = Path(temp_workspace_env.active_workspace_path)
    parsed_dir = workspace / "2_parsed_data"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    (parsed_dir / "20240501_10-Q.md").write_text("dummy content", encoding="utf-8")
    (parsed_dir / "20240801_10-Q.md").write_text("dummy content", encoding="utf-8")

    state = load_workspace_state(ticker)
    state.metadata_status = "completed"
    state.metadata = CompanyMetadata(ticker=ticker, company_name="Mock Apple Inc.")

    state.reports["2024_Q2"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q2",
        is_quarterly=True,
        income_statement_status="completed",
    )
    state.reports["2024_Q3"] = TemporalBlackboard(
        fiscal_year=2024,
        fiscal_period="Q3",
        is_quarterly=True,
        income_statement_status="completed",
    )
    save_workspace_state(ticker, state)

    orchestrator = BlackboardOrchestrator()
    mock_run_org_growth.return_value = (0.05, 0.06, 1000.0)

    with patch(
        "src.agents.orchestrator_pipelines.ingest.Ingester.load_parsed_registry"
    ) as mock_registry:
        mock_registry.return_value = {
            "h1": {
                "new_filename": "20240501_10-Q.md",
                "fiscal_year": 2024,
                "fiscal_quarter": "Q2",
                "document_type": "quarterly_filing",
            },
            "h2": {
                "new_filename": "20240801_10-Q.md",
                "fiscal_year": 2024,
                "fiscal_quarter": "Q3",
                "document_type": "quarterly_filing",
            },
        }

        asyncio.run(
            orchestrator.run_pipeline(
                ticker,
                stage="extract",
                agent="organic_growth",
                target_files=["20240501_10-Q.md"],
            )
        )

    assert mock_run_org_growth.call_count == 1
    # Check that it was called for Q2, not Q3
    _, kwargs = mock_run_org_growth.call_args
    assert kwargs.get("period_key") == "2024_Q2"
