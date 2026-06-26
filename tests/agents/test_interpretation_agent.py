import json
from unittest.mock import MagicMock

from src.agents.extractor_agents.extractor_financials_agents.interpretation_agent import (
    run_interpretation_agent,
)
from src.core.blackboard import CompanyMetadata, WorkspaceContext, LineItem


def test_stateless_interpretation_agent():
    mock_llm = MagicMock()
    mock_chat = MagicMock()
    mock_chat.get_history.return_value = []
    mock_chat.send_message.return_value = json.dumps(
        {
            "thought": "Finalizing",
            "tool": "finalize",
            "arguments": {
                "line_items": json.dumps(
                    [
                        {
                            "line_name": "Cash and Cash Equivalents",
                            "value": 12000.0,
                            "category": "current_assets",
                            "operating": True,
                            "calculated": False,
                        },
                        {
                            "line_name": "Total Assets",
                            "value": 50000.0,
                            "category": "current_assets",
                            "operating": False,
                            "calculated": True,
                        },
                    ]
                )
            },
        }
    )
    mock_llm.create_chat.return_value = mock_chat

    company_metadata = CompanyMetadata(ticker="TEST")
    workspace_state = WorkspaceContext(metadata=company_metadata)

    orig_items = [
        LineItem(
            line_name="Cash and Cash Equivalents",
            value=12000.0,
            category="current_assets",
        ),
        LineItem(line_name="Total Assets", value=50000.0, category="income_statement"),
    ]

    result = run_interpretation_agent(
        client=mock_llm,
        extracted_line_items=orig_items,
        company_metadata=company_metadata,
        workspace_state=workspace_state,
        period_key="2024_Q4",
        is_quarterly=True,
    )

    assert len(result) == 2
    assert result[0].line_name == "Cash and Cash Equivalents"
    assert result[0].value == 12000.0
    assert result[0].category == "current_assets"
    assert result[0].operating is True
    assert result[0].calculated is False

    assert result[1].line_name == "Total Assets"
    assert result[1].value == 50000.0
    assert result[1].category == "current_assets"
    assert result[1].operating is False
    assert result[1].calculated is True
