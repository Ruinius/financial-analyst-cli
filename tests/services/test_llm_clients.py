from unittest.mock import patch, MagicMock
import pytest
from pydantic import BaseModel

from src.core.config import Settings
from src.services.llm_client import (
    get_llm_client,
    LiteLLMClient,
    LiteLLMChatSession,
)


class MockStructuredSchema(BaseModel):
    name: str
    value: float


@pytest.fixture
def base_settings(tmp_path):
    return Settings(
        full_name="Test User",
        email="test@example.com",
        project_name="TestProject",
        primary_llm_api_key="sk-testkey",
        gemini_api_key="sk-gemini",
        deepseek_api_key="sk-deepseek",
        openrouter_api_key="sk-openrouter",
        base_workspace_dir=str(tmp_path),
    )


@patch("src.services.llm_client.load_config")
def test_factory_routing(mock_load_config, base_settings):
    base_settings.api_provider = "gemini"
    mock_load_config.return_value = base_settings

    client = get_llm_client()
    assert isinstance(client, LiteLLMClient)
    assert client.provider == "gemini"

    target_model, api_key = client._resolve_model_and_key()
    assert target_model.startswith("gemini/")
    assert api_key == "sk-gemini"


@patch("src.services.llm_client.load_config")
@patch("litellm.completion")
def test_generate_stream(mock_completion, mock_load_config, base_settings):
    base_settings.api_provider = "deepseek"
    mock_load_config.return_value = base_settings

    # Mock chunk responses
    chunk1 = MagicMock()
    chunk1.choices = [
        MagicMock(delta=MagicMock(reasoning_content="Pondering...", content=None))
    ]
    chunk2 = MagicMock()
    chunk2.choices = [
        MagicMock(delta=MagicMock(reasoning_content=None, content="Revenue is 500"))
    ]

    mock_completion.return_value = [chunk1, chunk2]

    client = get_llm_client()
    res = client.generate("Hello Deepseek", stream_thinking=True)
    assert "Revenue is 500" in res
    mock_completion.assert_called_once()


@patch("src.services.llm_client.load_config")
@patch("litellm.completion")
def test_structured_output(mock_completion, mock_load_config, base_settings):
    base_settings.api_provider = "openrouter"
    mock_load_config.return_value = base_settings

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content='{"name": "EBITA", "value": 120.5}'))
    ]
    mock_completion.return_value = mock_response

    client = get_llm_client()
    res_obj = client.generate_structured(
        "Get EBITA", response_schema=MockStructuredSchema
    )

    assert isinstance(res_obj, MockStructuredSchema)
    assert res_obj.name == "EBITA"
    assert res_obj.value == 120.5


@patch("src.services.llm_client.load_config")
def test_chat_session_creation(mock_load_config, base_settings):
    base_settings.api_provider = "deepseek"
    mock_load_config.return_value = base_settings

    client = get_llm_client()
    chat = client.create_chat(system_prompt="You are Sir Pennyworth")
    assert isinstance(chat, LiteLLMChatSession)
    assert len(chat.messages) == 1
    assert chat.messages[0]["role"] == "system"
