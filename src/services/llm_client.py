import json
import logging
import re
import litellm
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Type, TypeVar, Union
from types import SimpleNamespace

from src.core.config import load_config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Pre-compile regex at module level to avoid recompilation overhead
SERIALIZED_PROMPT_RE = re.compile(r"(?:^|\n+)\-\-\-\s*([A-Za-z]+)\s*\-\-\-\n+")


def parse_serialized_prompt(prompt: str) -> list:
    """Parse a serialized history prompt string with role headers back to structured messages."""
    if not isinstance(prompt, str):
        return prompt

    if "---" not in prompt:
        return [{"role": "user", "content": prompt}]

    parts = SERIALIZED_PROMPT_RE.split(prompt)
    if len(parts) < 3:
        return [{"role": "user", "content": prompt}]
    messages = []
    if parts[0].strip():
        messages.append({"role": "user", "content": parts[0].strip()})
    for i in range(1, len(parts), 2):
        role = parts[i].lower()
        if role not in ("system", "assistant", "user"):
            role = "user"
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            messages.append({"role": role, "content": content})
    return messages


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
    def send_message(
        self, message: str, tool_responses: list = None
    ) -> Union[str, list]:
        """Sends a message to the session. If tool_responses is provided, outputs tool results to conversation."""
        pass

    @abstractmethod
    def get_history(self) -> list[dict]:
        """Returns standard format messages history."""
        pass


class LiteLLMChatSession(ChatSession):
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
        self.last_tool_calls = []
        self.finalized = False
        self.finalized_args = {}

        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

        # Process tool definitions for LiteLLM / OpenAI format
        self.formatted_tools = []
        if self.tools:
            for t in self.tools:
                try:
                    tool_dict = litellm.utils.function_to_dict(t)
                    self.formatted_tools.append(tool_dict)
                except Exception as e:
                    logger.warning(f"Could not format tool {t} for LiteLLM: {e}")

    def send_message(
        self, message: str, tool_responses: list = None
    ) -> Union[str, list]:
        if tool_responses:
            for resp in tool_responses:
                call_id = resp.get("tool_call_id") or f"call_{resp['name']}"
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": resp["name"],
                        "content": str(resp["content"]),
                    }
                )
                if resp["name"] == "finalize":
                    self.finalized = True
        elif message:
            self.messages.append({"role": "user", "content": message})

        target_model, api_key = self.client._resolve_model_and_key(self.model)

        kwargs = {
            "model": target_model,
            "messages": self.messages,
            "temperature": self.temperature,
            "api_key": api_key,
            "timeout": self.client.timeout,
        }
        if self.formatted_tools:
            kwargs["tools"] = self.formatted_tools

        response = litellm.completion(**kwargs)
        assistant_msg = response.choices[0].message

        # Append assistant response to message history
        msg_dict = {"role": "assistant"}
        if assistant_msg.content:
            msg_dict["content"] = assistant_msg.content
        if getattr(assistant_msg, "tool_calls", None):
            msg_dict["tool_calls"] = [
                tc.model_dump() if hasattr(tc, "model_dump") else dict(tc)
                for tc in assistant_msg.tool_calls
            ]
        self.messages.append(msg_dict)

        if getattr(assistant_msg, "tool_calls", None):
            tool_calls_out = []
            for tc in assistant_msg.tool_calls:
                func_name = tc.function.name
                try:
                    func_args = json.loads(tc.function.arguments)
                except Exception:
                    func_args = {}

                if func_name == "finalize":
                    self.finalized = True
                    self.finalized_args = func_args

                call_obj = SimpleNamespace(
                    id=tc.id,
                    name=func_name,
                    args=func_args,
                )
                tool_calls_out.append(call_obj)
            return tool_calls_out

        return assistant_msg.content or ""

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


class LiteLLMClient(LLMClient):
    def _resolve_model_and_key(self, model: str = None) -> tuple[str, str]:
        provider = self.provider
        if provider == "gemini":
            target = (
                model
                or getattr(self.settings, "gemini_model", None)
                or "gemini-2.5-flash"
            )
            if "/" not in target:
                target = f"gemini/{target}"
            api_key = self.settings.gemini_api_key or self.settings.primary_llm_api_key
        elif provider == "deepseek":
            target = (
                model
                or getattr(self.settings, "deepseek_model", None)
                or "deepseek-chat"
            )
            if "/" not in target:
                target = f"deepseek/{target}"
            api_key = (
                self.settings.deepseek_api_key or self.settings.primary_llm_api_key
            )
        else:
            target = (
                model
                or getattr(self.settings, "openrouter_model", None)
                or "google/gemma-4-31b-it:free"
            )
            if "/" not in target:
                target = f"openrouter/{target}"
            api_key = (
                self.settings.openrouter_api_key or self.settings.primary_llm_api_key
            )

        return target, api_key

    def _format_messages(
        self, prompt: Union[str, list], system_prompt: str = None
    ) -> list:
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

        return messages

    def generate(
        self,
        prompt: Union[str, list],
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
        stream_thinking: bool = True,
    ) -> str:
        target_model, api_key = self._resolve_model_and_key(model)
        messages = self._format_messages(prompt, system_prompt)

        if stream_thinking:
            from rich.console import Console

            console = Console()
            full_content = []
            started_thinking = False

            response = litellm.completion(
                model=target_model,
                messages=messages,
                temperature=temperature,
                api_key=api_key,
                timeout=self.timeout,
                stream=True,
            )

            for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if not delta:
                    continue

                reasoning = (
                    getattr(delta, "reasoning_content", None)
                    or getattr(delta, "reasoning", None)
                    or ""
                )
                content = getattr(delta, "content", None) or ""

                if reasoning:
                    if not started_thinking:
                        safe_console_print(
                            console,
                            "[italic dim]Sir Pennyworth is pondering... [/italic dim]",
                            end="",
                            markup=True,
                        )
                        started_thinking = True
                    safe_console_print(console, reasoning, end="", style="italic dim")
                    console.file.flush()

                if content:
                    if started_thinking:
                        safe_console_print(console, "")
                        started_thinking = False

                    full_content.append(content)
                    safe_console_print(console, ".", end="", flush=True)

            if started_thinking or len(full_content) > 0:
                safe_console_print(console, "")
            return "".join(full_content)
        else:
            response = litellm.completion(
                model=target_model,
                messages=messages,
                temperature=temperature,
                api_key=api_key,
                timeout=self.timeout,
                stream=False,
            )
            return response.choices[0].message.content or ""

    def generate_structured(
        self,
        prompt: Union[str, list],
        response_schema: Type[T],
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
    ) -> T:
        target_model, api_key = self._resolve_model_and_key(model)
        messages = self._format_messages(prompt, system_prompt)

        try:
            response = litellm.completion(
                model=target_model,
                messages=messages,
                temperature=temperature,
                api_key=api_key,
                timeout=self.timeout,
                response_format=response_schema,
            )
            content = response.choices[0].message.content
            return response_schema.model_validate_json(content)
        except Exception as e:
            logger.warning(
                f"Native response_format failed, falling back to schema prompt injection: {e}"
            )
            schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
            simulated_system = (system_prompt or "") + (
                f"\n\nYou MUST return a JSON object that adheres strictly to the following JSON Schema:\n"
                f"```json\n{schema_json}\n```\n"
                f"Respond ONLY with the raw JSON object, without any Markdown wrappers or explanations."
            )
            messages_with_schema = self._format_messages(prompt, simulated_system)
            response = litellm.completion(
                model=target_model,
                messages=messages_with_schema,
                temperature=temperature,
                api_key=api_key,
                timeout=self.timeout,
            )
            content = response.choices[0].message.content
            from src.utils.markdown_helper import extract_json_from_text

            json_str = extract_json_from_text(content) or content
            return response_schema.model_validate_json(json_str)

    def create_chat(
        self,
        system_prompt: str = None,
        tools: list = None,
        model: str = None,
        temperature: float = 0.1,
    ) -> ChatSession:
        return LiteLLMChatSession(
            client=self,
            system_prompt=system_prompt,
            tools=tools,
            model=model,
            temperature=temperature,
        )


def get_llm_client(provider: str = None, model: str = None) -> LLMClient:
    settings = load_config()
    return LiteLLMClient(settings)
