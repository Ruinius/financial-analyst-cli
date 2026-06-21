import logging
from typing import Union, Type, TypeVar
from pydantic import BaseModel

from src.services.llm_client import (
    LLMClient,
    ChatSession,
    parse_serialized_prompt,
    safe_console_print,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


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

    def send_message(
        self, message: str, tool_responses: list = None
    ) -> Union[str, list]:
        from google.genai import types

        if tool_responses:
            parts = []
            for resp in tool_responses:
                parts.append(
                    types.Part.from_function_response(
                        name=resp["name"], response={"result": str(resp["content"])}
                    )
                )
            response = self.chat.send_message(parts)
        else:
            response = self.chat.send_message(message)

        if response.function_calls:
            return response.function_calls
        return response.text or ""

    def get_history(self) -> list[dict]:
        history = []
        for msg in self.chat.get_history():
            role = "assistant" if msg.role == "model" else msg.role
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


class GeminiLLMClient(LLMClient):
    def __init__(self, settings, model: str = None):
        super().__init__(settings)
        self.api_key = settings.gemini_api_key or settings.primary_llm_api_key
        self.default_model = (
            model or getattr(settings, "gemini_model", None) or "gemini-2.5-flash"
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
