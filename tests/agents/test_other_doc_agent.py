import json
from unittest.mock import MagicMock

from src.agents.extractor_agents.extractor_other import run_other_doc_agent
from src.core.blackboard import CompanyMetadata, OtherExtraction


def test_stateless_other_doc_agent():
    mock_llm = MagicMock()
    mock_chat = MagicMock()
    mock_chat.get_history.return_value = []
    mock_chat.send_message.return_value = json.dumps(
        {
            "thought": "Finalizing",
            "tool": "finalize",
            "arguments": {
                "summary": "Favorable news about product approvals.",
            },
        }
    )
    mock_llm.create_chat.return_value = mock_chat

    company_metadata = CompanyMetadata(ticker="TEST")
    extraction = run_other_doc_agent(
        client=mock_llm,
        filename="press_release.md",
        content="dummy content",
        company_metadata=company_metadata,
    )
    assert isinstance(extraction, OtherExtraction)
    assert extraction.source_file == "press_release.md"
    assert extraction.summary == "Favorable news about product approvals."
