import json
import time
import logging
import httpx
import re
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Type, TypeVar, Union

from src.core.config import load_config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def parse_serialized_prompt(prompt: str) -> list:
    """Parse a serialized history prompt string with role headers back to structured messages."""
    if not isinstance(prompt, str):
        return prompt
    pattern = r"(?:^|\n+)\-\-\-\s*([A-Za-z]+)\s*\-\-\-\n+"
    parts = re.split(pattern, prompt)
    if len(parts) < 3:
        return [{"role": "user", "content": prompt}]
    messages = []
    if parts[0].strip():
        messages.append({"role": "user", "content": parts[0].strip()})
    for i in range(1, len(parts), 2):
        role = parts[i].lower()
        if role == "system":
            role = "system"
        elif role == "assistant":
            role = "assistant"
        else:
            role = "user"
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            messages.append({"role": role, "content": content})
    return messages


def clean_leading_json_wrapper(s: str) -> str:
    s = s.strip()
    if s.startswith("```json"):
        s = s[7:].strip()
    elif s.startswith("```"):
        s = s[3:].strip()
    return s


def safe_console_print(console, text: str, *args, **kwargs) -> None:
    """Safely print to the Rich console, encoding/decoding as fallback to prevent UnicodeEncodeError on Windows terminals."""
    if "markup" not in kwargs:
        kwargs["markup"] = False
    if "highlight" not in kwargs:
        kwargs["highlight"] = False

    flush = kwargs.pop("flush", False)

    try:
        console.print(text, *args, **kwargs)
    except Exception:
        try:
            encoding = getattr(console.file, "encoding", None) or "utf-8"
            safe_text = text.encode(encoding, errors="replace").decode(encoding)
            console.print(safe_text, *args, **kwargs)
        except Exception:
            pass

    if flush:
        try:
            console.file.flush()
        except Exception:
            try:
                import sys

                sys.stdout.flush()
            except Exception:
                pass


class ChatSession(ABC):
    @abstractmethod
    def send_message(self, message: str) -> str:
        """Sends a user message to the session and returns response text."""
        pass

    @abstractmethod
    def get_history(self) -> list[dict]:
        """Returns standard format messages history."""
        pass


class GeminiChatSession(ChatSession):
    def __init__(
        self,
        client,
        model: str,
        system_prompt: str = None,
        tools: list = None,
        temperature: float = 0.1,
    ):
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
        )
        if tools:
            config.tools = tools
        self.chat = client.chats.create(model=model, config=config)

    def send_message(self, message: str) -> str:
        response = self.chat.send_message(message)
        return response.text or ""

    def get_history(self) -> list[dict]:
        history = []
        for msg in self.chat.get_history():
            role = "assistant" if msg.role == "model" else "user"
            content = ""
            if msg.parts:
                parts_list = []
                for p in msg.parts:
                    if p.text:
                        parts_list.append(p.text)
                    elif p.function_call:
                        parts_list.append(f"Function call: {p.function_call.name}")
                    elif p.function_response:
                        parts_list.append(
                            f"Function response: {p.function_response.response}"
                        )
                content = "\n".join(parts_list)
            history.append({"role": role, "content": content})
        return history


class SimulatedChatSession(ChatSession):
    def __init__(
        self,
        client,
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
    ):
        self.client = client
        self.model = model
        self.temperature = temperature
        self.messages = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

    def send_message(self, message: str) -> str:
        self.messages.append({"role": "user", "content": message})
        response = self.client.generate(
            self.messages,
            model=self.model,
            temperature=self.temperature,
            stream_thinking=True,
        )
        self.messages.append({"role": "assistant", "content": response})
        return response

    def get_history(self) -> list[dict]:
        return self.messages


class LLMClient(ABC):
    def __init__(self, settings):
        self.settings = settings
        self.provider = getattr(settings, "api_provider", "openrouter").lower()
        self.timeout = max(getattr(settings, "llm_timeout", 30.0), 120.0)

    @abstractmethod
    def generate(
        self,
        prompt: Union[str, list],
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
        stream_thinking: bool = True,
    ) -> str:
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: Union[str, list],
        response_schema: Type[T],
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
    ) -> T:
        pass

    @abstractmethod
    def create_chat(
        self,
        system_prompt: str = None,
        tools: list = None,
        model: str = None,
        temperature: float = 0.1,
    ) -> ChatSession:
        pass


class GeminiClient(LLMClient):
    def __init__(self, settings):
        super().__init__(settings)
        self.api_key = settings.gemini_api_key or settings.primary_llm_api_key
        self.default_model = (
            getattr(settings, "gemini_model", None) or "gemini-2.5-flash"
        )
        from google import genai

        self.gemini_client = genai.Client(api_key=self.api_key)

    def generate(
        self,
        prompt: Union[str, list],
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
        stream_thinking: bool = True,
    ) -> str:
        from google.genai import types

        contents = []
        if isinstance(prompt, list):
            for msg in prompt:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                if role == "system":
                    if not system_prompt:
                        system_prompt = msg["content"]
                    continue
                contents.append(
                    types.Content(
                        role=role, parts=[types.Part.from_text(text=msg["content"])]
                    )
                )
        elif isinstance(prompt, str) and (
            "--- USER ---" in prompt or "--- ASSISTANT ---" in prompt
        ):
            parsed = parse_serialized_prompt(prompt)
            for msg in parsed:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                if role == "system":
                    if not system_prompt:
                        system_prompt = msg["content"]
                    continue
                contents.append(
                    types.Content(
                        role=role, parts=[types.Part.from_text(text=msg["content"])]
                    )
                )
        else:
            contents.append(
                types.Content(
                    role="user", parts=[types.Part.from_text(text=str(prompt))]
                )
            )

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
        )

        target_model = model or self.default_model
        if target_model and (
            "gemma" in target_model.lower()
            or "google" in target_model.lower()
            or "deepseek" in target_model.lower()
        ):
            target_model = self.default_model

        if target_model and (
            "gemini-2.5" in target_model.lower()
            or "gemini-3" in target_model.lower()
            or "thinking" in target_model.lower()
        ):
            config.thinking_config = types.ThinkingConfig(
                thinking_budget=-1, include_thoughts=True
            )

        if stream_thinking:
            from rich.console import Console

            console = Console()

            response = self.gemini_client.models.generate_content_stream(
                model=target_model, contents=contents, config=config
            )
            full_content = []
            started_thinking = False

            for chunk in response:
                if chunk.candidates:
                    for candidate in chunk.candidates:
                        if candidate.content and candidate.content.parts:
                            for part in candidate.content.parts:
                                if getattr(part, "thought", False):
                                    if part.text:
                                        if not started_thinking:
                                            safe_console_print(
                                                console,
                                                "[italic dim]Sir Pennyworth is pondering... [/italic dim]",
                                                end="",
                                                markup=True,
                                            )
                                            started_thinking = True
                                        safe_console_print(
                                            console,
                                            part.text,
                                            end="",
                                            style="italic dim",
                                        )
                                        console.file.flush()
                                elif part.text:
                                    if started_thinking:
                                        safe_console_print(console, "")
                                        started_thinking = False

                                    full_content.append(part.text)
                                    safe_console_print(console, ".", end="", flush=True)
                elif chunk.text:
                    if started_thinking:
                        safe_console_print(console, "")
                        started_thinking = False
                    full_content.append(chunk.text)
                    safe_console_print(console, ".", end="", flush=True)

            if started_thinking or len(full_content) > 0:
                safe_console_print(console, "")
            return "".join(full_content)
        else:
            response = self.gemini_client.models.generate_content(
                model=target_model, contents=contents, config=config
            )
            return response.text or ""

    def generate_structured(
        self,
        prompt: Union[str, list],
        response_schema: Type[T],
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
    ) -> T:
        from google.genai import types

        contents = []
        if isinstance(prompt, list):
            for msg in prompt:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                if role == "system":
                    if not system_prompt:
                        system_prompt = msg["content"]
                    continue
                contents.append(
                    types.Content(
                        role=role, parts=[types.Part.from_text(text=msg["content"])]
                    )
                )
        elif isinstance(prompt, str) and (
            "--- USER ---" in prompt or "--- ASSISTANT ---" in prompt
        ):
            parsed = parse_serialized_prompt(prompt)
            for msg in parsed:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                if role == "system":
                    if not system_prompt:
                        system_prompt = msg["content"]
                    continue
                contents.append(
                    types.Content(
                        role=role, parts=[types.Part.from_text(text=msg["content"])]
                    )
                )
        else:
            contents.append(
                types.Content(
                    role="user", parts=[types.Part.from_text(text=str(prompt))]
                )
            )

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=response_schema,
        )

        target_model = model or self.default_model
        if target_model and (
            "gemma" in target_model.lower()
            or "google" in target_model.lower()
            or "deepseek" in target_model.lower()
        ):
            target_model = self.default_model

        response = self.gemini_client.models.generate_content(
            model=target_model, contents=contents, config=config
        )
        return response_schema.model_validate_json(response.text)

    def create_chat(
        self,
        system_prompt: str = None,
        tools: list = None,
        model: str = None,
        temperature: float = 0.1,
    ) -> ChatSession:
        target_model = model or self.default_model
        if target_model and (
            "gemma" in target_model.lower()
            or "google" in target_model.lower()
            or "deepseek" in target_model.lower()
        ):
            target_model = self.default_model
        return GeminiChatSession(
            client=self.gemini_client,
            model=target_model,
            system_prompt=system_prompt,
            tools=tools,
            temperature=temperature,
        )


class OpenAICompatibleClient(LLMClient):
    def __init__(self, settings):
        super().__init__(settings)
        self.api_key = None
        self.endpoint = None
        self.headers = {}
        self.default_model = None

    def generate(
        self,
        prompt: Union[str, list],
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
        stream_thinking: bool = True,
    ) -> str:
        target_model = model or self.default_model

        messages = []
        if isinstance(prompt, list):
            messages = list(prompt)
        else:
            prompt_str = str(prompt)
            if "--- USER ---" in prompt_str or "--- ASSISTANT ---" in prompt_str:
                messages = parse_serialized_prompt(prompt_str)
            else:
                messages.append({"role": "user", "content": prompt_str})

        if system_prompt and not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": system_prompt})

        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
        }

        max_retries = 3
        initial_delay = 1.0
        backoff = 2.0

        for attempt in range(max_retries + 1):
            try:
                if stream_thinking:
                    payload["stream"] = True
                    self._customize_payload_for_thinking(payload)

                    from rich.console import Console

                    console = Console()

                    full_content = []
                    started_thinking = False
                    timeout_config = httpx.Timeout(
                        timeout=self.timeout, connect=10.0, read=self.timeout
                    )

                    with httpx.Client(timeout=timeout_config) as client:
                        with client.stream(
                            "POST", self.endpoint, headers=self.headers, json=payload
                        ) as r:
                            r.raise_for_status()
                            for line in r.iter_lines():
                                if not line.strip():
                                    continue
                                if line.startswith("data: "):
                                    data_str = line[len("data: ") :]
                                    if data_str.strip() == "[DONE]":
                                        break
                                    try:
                                        chunk = json.loads(data_str)
                                    except Exception as e:
                                        logger.exception(
                                            f"Error parsing stream chunk: {e}"
                                        )
                                        continue

                                    if isinstance(chunk, dict) and "error" in chunk:
                                        error_msg = chunk["error"].get(
                                            "message"
                                        ) or str(chunk["error"])
                                        raise RuntimeError(
                                            f"LLM API returned error: {error_msg}"
                                        )

                                    choices = chunk.get("choices")
                                    if not choices:
                                        continue
                                    delta = choices[0].get("delta")
                                    if not delta:
                                        continue

                                    reasoning, content = (
                                        self._extract_reasoning_and_content(delta)
                                    )

                                    if reasoning:
                                        if not started_thinking:
                                            safe_console_print(
                                                console,
                                                "[italic dim]Sir Pennyworth is pondering... [/italic dim]",
                                                end="",
                                                markup=True,
                                            )
                                            started_thinking = True
                                        safe_console_print(
                                            console,
                                            reasoning,
                                            end="",
                                            style="italic dim",
                                        )
                                        console.file.flush()

                                    if content:
                                        if started_thinking:
                                            safe_console_print(console, "")
                                            started_thinking = False

                                        full_content.append(content)
                                        safe_console_print(
                                            console, ".", end="", flush=True
                                        )

                            if started_thinking or len(full_content) > 0:
                                safe_console_print(console, "")
                    return "".join(full_content)
                else:
                    timeout_config = httpx.Timeout(
                        timeout=self.timeout, connect=10.0, read=self.timeout
                    )
                    with httpx.Client(timeout=timeout_config) as client:
                        response = client.post(
                            self.endpoint, headers=self.headers, json=payload
                        )
                        response.raise_for_status()
                        data = response.json()
                        return data["choices"][0]["message"]["content"]
            except Exception as e:
                if attempt == max_retries:
                    raise RuntimeError(f"LLM generation failed: {str(e)}")

                delay = initial_delay * (backoff**attempt)
                logger.warning(
                    f"LLM API request failed: {e}. Retrying in {delay:.1f}s (Attempt {attempt + 1}/{max_retries + 1})..."
                )
                time.sleep(delay)

    def generate_structured(
        self,
        prompt: Union[str, list],
        response_schema: Type[T],
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
    ) -> T:
        schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
        simulated_system = (system_prompt or "") + (
            f"\n\nYou MUST return a JSON object that adheres strictly to the following JSON Schema:\n"
            f"```json\n{schema_json}\n```\n"
            f"Respond ONLY with the raw JSON object, without any Markdown wrappers or explanations."
        )

        raw_response = self.generate(
            prompt,
            system_prompt=simulated_system,
            model=model,
            temperature=temperature,
            stream_thinking=False,
        )

        from src.utils.tools import extract_json_from_text

        json_str = extract_json_from_text(raw_response)
        if not json_str:
            raise ValueError(f"Failed to extract JSON from response: {raw_response}")

        return response_schema.model_validate_json(json_str)

    def create_chat(
        self,
        system_prompt: str = None,
        tools: list = None,
        model: str = None,
        temperature: float = 0.1,
    ) -> ChatSession:
        return SimulatedChatSession(
            client=self,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
        )

    def _customize_payload_for_thinking(self, payload: dict) -> None:
        pass

    def _extract_reasoning_and_content(self, delta: dict) -> tuple[str, str]:
        return "", delta.get("content") or ""


class DeepseekClient(OpenAICompatibleClient):
    def __init__(self, settings):
        super().__init__(settings)
        self.api_key = settings.deepseek_api_key or settings.primary_llm_api_key
        self.endpoint = "https://api.deepseek.com/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.default_model = (
            getattr(settings, "deepseek_model", None) or "deepseek-v4-flash"
        )

    def _customize_payload_for_thinking(self, payload: dict) -> None:
        payload["thinking"] = {"type": "enabled"}

    def _extract_reasoning_and_content(self, delta: dict) -> tuple[str, str]:
        reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
        content = delta.get("content") or ""
        return reasoning, content


class OpenRouterClient(OpenAICompatibleClient):
    def __init__(self, settings):
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
            getattr(settings, "openrouter_model", None) or "google/gemma-4-31b-it:free"
        )

    def _customize_payload_for_thinking(self, payload: dict) -> None:
        payload["include_reasoning"] = True
        payload["reasoning"] = {"exclude": False}

    def _extract_reasoning_and_content(self, delta: dict) -> tuple[str, str]:
        reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
        content = delta.get("content") or ""
        return reasoning, content


def get_llm_client() -> LLMClient:
    settings = load_config()
    provider = getattr(settings, "api_provider", "openrouter").lower()

    if provider == "gemini":
        return GeminiClient(settings)
    elif provider == "deepseek":
        return DeepseekClient(settings)
    else:
        return OpenRouterClient(settings)
