import logging
from src.services.llm_client import OpenAICompatibleClient

logger = logging.getLogger(__name__)


class OpenRouterLLMClient(OpenAICompatibleClient):
    def __init__(self, settings, model: str = None):
        super().__init__(settings)
        self.api_key = settings.openrouter_api_key or settings.primary_llm_api_key
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Ruinius/financial-analyst-cli",
            "X-Title": "Financial Analyst CLI",
        }
        self.default_model = (
            model
            or getattr(settings, "openrouter_model", None)
            or "google/gemma-4-31b-it:free"
        )

    def _customize_payload_for_thinking(self, payload: dict) -> None:
        payload["include_reasoning"] = True
        payload["reasoning"] = {"exclude": False}

    def _extract_reasoning_and_content(self, delta: dict) -> tuple[str, str]:
        reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
        content = delta.get("content") or ""
        return reasoning, content
