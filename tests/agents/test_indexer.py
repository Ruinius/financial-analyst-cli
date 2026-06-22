import pytest
from unittest.mock import patch, MagicMock

from src.agents.indexer_agent import IndexerAgent


@pytest.fixture
def mock_workspace(tmp_path):
    """Set up a mock workspace with extract, analysis, and model folders."""
    ticker = "TEST_IND"
    workspace = tmp_path / ticker
    workspace.mkdir()

    # Create directories
    (workspace / "4_extracted_data").mkdir()
    (workspace / "5_historical_analysis").mkdir()
    (workspace / "6_financial_model").mkdir()

    # Create dummy files in 4_extracted_data
    (workspace / "4_extracted_data" / "20240101_10-Q_extracted.md").write_text(
        "# Extracted Financial Report: 20240101_10-Q.md\n"
        "| Metadata Key | Value |\n"
        "| --- | --- |\n"
        "| Document Type | quarterly_filing |\n"
        "| Fiscal Quarter | Q1 |\n"
        "| Fiscal Year | 2024 |\n",
        encoding="utf-8",
    )
    (workspace / "4_extracted_data" / "README.md").write_text(
        "# Readme", encoding="utf-8"
    )
    (workspace / "4_extracted_data" / ".hidden_file").write_text(
        "hidden", encoding="utf-8"
    )

    # Create dummy file in 5_historical_analysis
    (workspace / "5_historical_analysis" / "financials_quarter.md").write_text(
        "# Historical Financials - Quarterly\n", encoding="utf-8"
    )

    # Create dummy file in 6_financial_model
    (workspace / "6_financial_model" / "20240101_TEST_IND_model.md").write_text(
        "# DCF Projections for TEST_IND\n", encoding="utf-8"
    )

    return workspace


@patch("src.agents.indexer_agent.load_config")
@patch("src.agents.indexer_agent.get_llm_client")
def test_indexer_llm_success(mock_get_llm, mock_load_config, mock_workspace):
    """Test indexer when LLM returns a valid response."""
    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(mock_workspace)
    mock_settings.active_ticker = "TEST_IND"
    mock_load_config.return_value = mock_settings

    # LLM returns a markdown response
    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm
    mock_llm.generate.return_value = "# LLM Generated Folder Index\nSome details here that are slightly longer to satisfy the minimum length check."

    agent = IndexerAgent()
    agent.run_indexing("TEST_IND")

    index_file = mock_workspace / "TEST_IND_folder_index.md"
    assert index_file.exists()
    content = index_file.read_text(encoding="utf-8")
    assert "LLM Generated Folder Index" in content


@patch("src.agents.indexer_agent.load_config")
@patch("src.agents.indexer_agent.get_llm_client")
def test_indexer_fallback_on_llm_failure(
    mock_get_llm, mock_load_config, mock_workspace
):
    """Test indexer programmatic fallback when LLM fails or raises exception."""
    mock_settings = MagicMock()
    mock_settings.active_workspace_path = str(mock_workspace)
    mock_settings.active_ticker = "TEST_IND"
    mock_load_config.return_value = mock_settings

    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm
    # Simulate LLM failure
    mock_llm.generate.side_effect = RuntimeError("LLM Unavailable")

    agent = IndexerAgent()
    agent.run_indexing("TEST_IND")

    index_file = mock_workspace / "TEST_IND_folder_index.md"
    assert index_file.exists()
    content = index_file.read_text(encoding="utf-8")

    # Verify fallback cataloging
    assert "# Folder Index: TEST_IND" in content
    assert "4_extracted_data" in content
    assert "5_historical_analysis" in content
    assert "6_financial_model" in content

    # Check relative links exist for files
    assert (
        "[20240101_10-Q_extracted.md](4_extracted_data/20240101_10-Q_extracted.md)"
        in content
    )
    assert (
        "[financials_quarter.md](5_historical_analysis/financials_quarter.md)"
        in content
    )
    assert (
        "[20240101_TEST_IND_model.md](6_financial_model/20240101_TEST_IND_model.md)"
        in content
    )

    # Check ignored files (README.md, .hidden_file) are not listed
    assert "README.md" not in content
    assert ".hidden_file" not in content

    # Check extracted metadata detail
    assert "Period: 2024-Q1" in content
    assert "Type: quarterly_filing" in content
