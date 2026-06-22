import json
from unittest.mock import MagicMock

from src.agents.extractor_agents.extractor_financials_agents.balance_sheet_agent import (
    run_balance_sheet_agent,
    BalanceSheetExtraction,
)
from src.core.blackboard import CompanyMetadata


def test_stateless_balance_sheet_agent():
    mock_llm = MagicMock()
    mock_chat = MagicMock()
    mock_chat.get_history.return_value = []
    mock_chat.send_message.return_value = json.dumps(
        {
            "thought": "Finalizing",
            "tool": "finalize",
            "arguments": {
                "raw_balance_sheet_markdown": "| Assets | 100 |",
                "currency": "USD",
                "unit": "Millions",
            },
        }
    )
    mock_llm.create_chat.return_value = mock_chat

    company_metadata = CompanyMetadata(ticker="TEST")
    extraction = run_balance_sheet_agent(
        client=mock_llm,
        filename="balance_sheet.md",
        content="dummy content",
        company_metadata=company_metadata,
        is_quarterly=False,
    )
    assert isinstance(extraction, BalanceSheetExtraction)
    assert extraction.raw_balance_sheet_markdown == "| Assets | 100 |"
    assert extraction.currency == "USD"
    assert extraction.unit == "Millions"
