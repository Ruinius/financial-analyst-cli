import json
from unittest.mock import MagicMock

from src.agents.extractor_agents.metadata_agent import (
    run_metadata_agent,
    MetadataAgentResult,
)
from src.core.blackboard import CompanyMetadata


def test_stateless_metadata_agent():
    mock_llm = MagicMock()
    mock_chat = MagicMock()
    mock_chat.get_history.return_value = []
    mock_chat.send_message.return_value = json.dumps(
        {
            "thought": "Finalizing",
            "tool": "finalize",
            "arguments": {
                "company_name": "Test Company",
                "description": "A test business",
                "fiscal_q4_date": "2024-12-31",
                "reporting_currency": "EUR",
                "preferred_unit": "Millions",
                "documents_metadata": json.dumps(
                    {
                        "file1.md": {
                            "document_date": "2024-12-31",
                            "period_end_date": "2024-12-31",
                            "document_type": "annual_filing",
                            "fiscal_quarter": "FY",
                            "fiscal_year": "2024",
                        }
                    }
                ),
            },
        }
    )
    mock_llm.create_chat.return_value = mock_chat
    mock_llm.generate.return_value = mock_chat.send_message.return_value

    parsed_docs = {
        "file1.md": "header info Test Company",
        "file2.md": "more detail EUR Millions",
    }

    result = run_metadata_agent(mock_llm, "TEST", parsed_docs)
    assert isinstance(result, MetadataAgentResult)
    assert isinstance(result.company_metadata, CompanyMetadata)
    assert result.company_metadata.ticker == "TEST"
    assert result.company_metadata.company_name == "Test Company"
    assert result.company_metadata.reporting_currency == "EUR"
    assert result.company_metadata.preferred_unit == "Millions"

    assert "file1.md" in result.documents_metadata
    assert result.documents_metadata["file1.md"]["document_type"] == "annual_filing"
    assert result.documents_metadata["file1.md"]["fiscal_year"] == "2024"
