import json
from unittest.mock import MagicMock

from src.agents.extractor_agents.extractor_analyst_report import (
    run_analyst_report_agent,
)
from src.core.blackboard import CompanyMetadata, AnalystReportExtraction


def test_stateless_analyst_report_agent():
    mock_llm = MagicMock()
    mock_chat = MagicMock()
    mock_chat.get_history.return_value = []
    mock_chat.send_message.return_value = json.dumps(
        {
            "thought": "Finalizing",
            "tool": "finalize",
            "arguments": {
                "economic_moat": "Wide",
                "economic_moat_rationale": "High switching costs",
                "margin_outlook": "Increasing",
                "margin_magnitude": "1 pp",
                "margin_rationale": "Cost savings program",
                "growth_outlook": "Accelerating",
                "growth_magnitude": "2 pp",
                "growth_rationale": "Product launch",
            },
        }
    )
    mock_llm.create_chat.return_value = mock_chat

    company_metadata = CompanyMetadata(ticker="TEST")
    extraction = run_analyst_report_agent(
        client=mock_llm,
        filename="analyst_report.md",
        content="dummy content",
        company_metadata=company_metadata,
    )
    assert isinstance(extraction, AnalystReportExtraction)
    assert extraction.source_file == "analyst_report.md"
    assert extraction.economic_moat == "Wide"
    assert extraction.economic_moat_rationale == "High switching costs"
