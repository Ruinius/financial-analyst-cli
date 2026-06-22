import json
from unittest.mock import MagicMock

from src.agents.extractor_agents.metadata_agent import run_metadata_agent
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
            },
        }
    )
    mock_llm.create_chat.return_value = mock_chat
    mock_llm.generate.return_value = mock_chat.send_message.return_value

    parsed_docs = {
        "file1.md": "header info Test Company",
        "file2.md": "more detail EUR Millions",
    }

    metadata = run_metadata_agent(mock_llm, "TEST", parsed_docs)
    assert isinstance(metadata, CompanyMetadata)
    assert metadata.ticker == "TEST"
    assert metadata.company_name == "Test Company"
    assert metadata.reporting_currency == "EUR"
    assert metadata.preferred_unit == "Millions"
