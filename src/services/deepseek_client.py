import logging
from src.services.llm_client import OpenAICompatibleClient

logger = logging.getLogger(__name__)


class DeepSeekLLMClient(OpenAICompatibleClient):
    def __init__(self, settings, model: str = None, max_thinking_tokens: int = 1024):
        super().__init__(settings)
        self.api_key = settings.deepseek_api_key or settings.primary_llm_api_key
        self.endpoint = "https://api.deepseek.com/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.default_model = (
            model or getattr(settings, "deepseek_model", None) or "deepseek-v4-flash"
        )
        self.max_thinking_tokens = max_thinking_tokens

    def _customize_payload_for_thinking(self, payload: dict) -> None:
        payload["thinking"] = {
            "type": "enabled",
            "budget_tokens": self.max_thinking_tokens,
        }

    def _extract_reasoning_and_content(self, delta: dict) -> tuple[str, str]:
        reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
        content = delta.get("content") or ""
        return reasoning, content
