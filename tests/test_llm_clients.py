from unittest.mock import patch, MagicMock
import pytest
from pydantic import BaseModel

from src.core.config import Settings
from src.services.llm_client import (
    get_llm_client,
    GeminiClient,
    DeepseekClient,
    OpenRouterClient,
    GeminiChatSession,
    SimulatedChatSession,
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
def test_factory_routing_gemini(mock_load_config, base_settings):
    base_settings.api_provider = "gemini"
    mock_load_config.return_value = base_settings

    # Mock the google-genai import and genai.Client
    with patch("google.genai.Client") as mock_genai_client:
        client = get_llm_client()
        assert isinstance(client, GeminiClient)
        assert client.provider == "gemini"
        mock_genai_client.assert_called_once_with(api_key="sk-gemini")


@patch("src.services.llm_client.load_config")
def test_factory_routing_deepseek(mock_load_config, base_settings):
    base_settings.api_provider = "deepseek"
    mock_load_config.return_value = base_settings

    client = get_llm_client()
    assert isinstance(client, DeepseekClient)
    assert client.provider == "deepseek"


@patch("src.services.llm_client.load_config")
def test_factory_routing_openrouter(mock_load_config, base_settings):
    base_settings.api_provider = "openrouter"
    mock_load_config.return_value = base_settings

    client = get_llm_client()
    assert isinstance(client, OpenRouterClient)
    assert client.provider == "openrouter"


@patch("src.services.llm_client.load_config")
@patch("httpx.Client")
def test_deepseek_generate_stream(mock_httpx_client, mock_load_config, base_settings):
    base_settings.api_provider = "deepseek"
    mock_load_config.return_value = base_settings

    # Set up mock stream response
    mock_response = MagicMock()
    mock_response.iter_lines.return_value = [
        'data: {"choices": [{"delta": {"reasoning_content": "Pondering...", "content": ""}}]}',
        'data: {"choices": [{"delta": {"reasoning_content": "", "content": "Revenue is 500"}}]}',
        "data: [DONE]",
    ]

    mock_client_instance = MagicMock()
    mock_client_instance.stream.return_value.__enter__.return_value = mock_response
    mock_httpx_client.return_value.__enter__.return_value = mock_client_instance

    client = get_llm_client()
    res = client.generate("Hello Deepseek", stream_thinking=True)
    assert "Revenue is 500" in res


@patch("src.services.llm_client.load_config")
@patch("httpx.Client")
def test_openrouter_structured_fallback(
    mock_httpx_client, mock_load_config, base_settings
):
    base_settings.api_provider = "openrouter"
    mock_load_config.return_value = base_settings

    # Mock non-streaming response for structured output
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": 'Here is the data: ```json\n{"name": "EBITA", "value": 120.5}\n```'
                }
            }
        ]
    }
    mock_client_instance = MagicMock()
    mock_client_instance.post.return_value = mock_response
    mock_httpx_client.return_value.__enter__.return_value = mock_client_instance

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
    assert isinstance(chat, SimulatedChatSession)
    assert len(chat.messages) == 1
    assert chat.messages[0]["role"] == "system"


@patch("src.services.llm_client.load_config")
def test_gemini_chat_session_creation(mock_load_config, base_settings):
    base_settings.api_provider = "gemini"
    mock_load_config.return_value = base_settings

    with patch("google.genai.Client") as mock_genai_client:
        mock_client_instance = MagicMock()
        mock_genai_client.return_value = mock_client_instance

        client = get_llm_client()
        chat = client.create_chat(system_prompt="You are Sir Pennyworth")
        assert isinstance(chat, GeminiChatSession)
        mock_client_instance.chats.create.assert_called_once()
