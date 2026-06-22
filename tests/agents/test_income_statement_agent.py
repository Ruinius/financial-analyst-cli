import json
from unittest.mock import MagicMock

from src.agents.extractor_agents.extractor_financials_agents.income_statement_agent import (
    run_income_statement_agent,
    IncomeStatementExtraction,
)
from src.core.blackboard import CompanyMetadata


def test_stateless_income_statement_agent():
    mock_llm = MagicMock()
    mock_chat = MagicMock()
    mock_chat.get_history.return_value = []
    mock_chat.send_message.return_value = json.dumps(
        {
            "thought": "Finalizing",
            "tool": "finalize",
            "arguments": {
                "raw_income_statement_markdown": "| Revenue | 500 |",
                "currency": "USD",
                "unit": "Millions",
            },
        }
    )
    mock_llm.create_chat.return_value = mock_chat

    company_metadata = CompanyMetadata(ticker="TEST")
    extraction = run_income_statement_agent(
        client=mock_llm,
        filename="income_statement.md",
        content="dummy content",
        company_metadata=company_metadata,
        is_quarterly=True,
    )
    assert isinstance(extraction, IncomeStatementExtraction)
    assert extraction.raw_income_statement_markdown == "| Revenue | 500 |"
    assert extraction.currency == "USD"
    assert extraction.unit == "Millions"
