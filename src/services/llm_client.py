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


def _get_tool_descriptions(tools: list) -> str:
    if not tools:
        return ""
    import inspect

    descriptions = []
    for tool in tools:
        name = getattr(tool, "__name__", str(tool))
        doc = getattr(tool, "__doc__", "") or "No description provided."
        sig = inspect.signature(tool)
        params = []
        for param_name, param in sig.parameters.items():
            ann = param.annotation
            type_str = getattr(ann, "__name__", str(ann))
            if type_str == "_empty":
                type_str = "str"
            params.append(f"{param_name}: {type_str}")
        params_desc = ", ".join(params)
        descriptions.append(
            f"- Tool Name: '{name}'\n"
            f"  Arguments: {{{params_desc}}}\n"
            f"  Description: {doc.strip()}"
        )
    return "\n".join(descriptions)


class ChatSession(ABC):
    @abstractmethod
    def send_message(
        self, message: str, tool_responses: list = None
    ) -> Union[str, list]:
        """Sends a message to the session. If tool_responses is provided, outputs tool results to conversation."""
        pass

    @abstractmethod
    def get_history(self) -> list[dict]:
        """Returns standard format messages history."""
        pass


class SimulatedChatSession(ChatSession):
    def __init__(
        self,
        client,
        system_prompt: str = None,
        tools: list = None,
        model: str = None,
        temperature: float = 0.1,
    ):
        self.client = client
        self.model = model
        self.temperature = temperature
        self.messages = []
        self.tools = tools or []

        injected_sys = system_prompt or ""
        if tools:
            tool_descs = _get_tool_descriptions(tools)
            injected_sys += (
                "\n\nYou have access to the following tools:\n"
                f"{tool_descs}\n\n"
                "To execute a tool call, respond ONLY with a single valid JSON object of this structure:\n"
                "{\n"
                '  "thought": "reasoning for selecting the tool",\n'
                '  "tool": "tool_name",\n'
                '  "arguments": {"arg1": val1, ...}\n'
                "}\n"
                "Do not add any markdown formatting or surrounding text (like ```json). Respond ONLY with the raw JSON object."
            )

        if injected_sys:
            self.messages.append({"role": "system", "content": injected_sys})

    def send_message(
        self, message: str, tool_responses: list = None
    ) -> Union[str, list]:
        from src.utils.markdown_helper import extract_json_from_text
        from types import SimpleNamespace

        if tool_responses:
            for resp in tool_responses:
                self.messages.append(
                    {
                        "role": "user",
                        "content": f"Observation from {resp['name']}:\n{resp['content']}",
                    }
                )
        else:
            self.messages.append({"role": "user", "content": message})

        resp_text = self.client.generate(
            self.messages,
            model=self.model,
            temperature=self.temperature,
            stream_thinking=True,
        )
        self.messages.append({"role": "assistant", "content": resp_text})

        # Check if the output contains a tool call request
        json_str = extract_json_from_text(resp_text)
        if json_str:
            try:
                action = json.loads(json_str)
                if "tool" in action:
                    call = SimpleNamespace(
                        name=action["tool"], args=action.get("arguments", {})
                    )
                    return [call]
            except Exception:
                pass

        return resp_text

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

        from src.utils.markdown_helper import extract_json_from_text

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
            tools=tools,
            model=model,
            temperature=temperature,
        )

    def _customize_payload_for_thinking(self, payload: dict) -> None:
        pass

    def _extract_reasoning_and_content(self, delta: dict) -> tuple[str, str]:
        return "", delta.get("content") or ""


def get_llm_client(provider: str = None, model: str = None) -> LLMClient:
    settings = load_config()
    if provider is None:
        provider = getattr(settings, "api_provider", "openrouter")
    provider = provider.lower()

    if provider == "gemini":
        from src.services.gemini_client import GeminiLLMClient

        return GeminiLLMClient(settings, model=model)
    elif provider == "deepseek":
        from src.services.deepseek_client import DeepSeekLLMClient

        return DeepSeekLLMClient(settings, model=model)
    else:
        from src.services.openrouter_client import OpenRouterLLMClient

        return OpenRouterLLMClient(settings, model=model)
