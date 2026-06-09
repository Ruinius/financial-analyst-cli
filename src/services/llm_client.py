import httpx
from src.core.config import load_config


class LLMClient:
    def __init__(self):
        self.settings = load_config()
        self.api_key = self.settings.primary_llm_api_key
        # Default to OpenRouter endpoint, which supports Gemma models and others
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Ruinius/financial-analyst-cli",
            "X-Title": "Financial Analyst CLI",
        }

    def generate(
        self,
        prompt: str,
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
    ) -> str:
        """Generate a response from the LLM model."""
        if not model:
            model = self.settings.text_model_id

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    self.endpoint, headers=self.headers, json=payload
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            # Handle potential API errors gracefully
            raise RuntimeError(f"LLM generation failed: {str(e)}")
