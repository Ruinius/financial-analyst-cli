import json
import httpx
from src.core.config import load_config


class LLMClient:
    def __init__(self):
        self.settings = load_config()
        # Determine provider (default: openrouter)
        self.provider = getattr(self.settings, "api_provider", "openrouter").lower()

        # Route API Key and Endpoint
        if self.provider == "gemini":
            self.api_key = (
                self.settings.gemini_api_key or self.settings.primary_llm_api_key
            )
            self.endpoint = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            self.headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        elif self.provider == "deepseek":
            self.api_key = (
                self.settings.deepseek_api_key or self.settings.primary_llm_api_key
            )
            self.endpoint = "https://api.deepseek.com/chat/completions"
            self.headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        else:
            self.api_key = (
                self.settings.openrouter_api_key or self.settings.primary_llm_api_key
            )
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
        stream_thinking: bool = True,
    ) -> str:
        """Generate a response from the LLM model."""
        if not model:
            model = self.settings.text_model_id

        # Safeguard: if using Gemini provider but model is Gemma/OpenRouter default, fallback to gemini-2.5-flash
        if self.provider == "gemini" and (
            "gemma" in model.lower()
            or "google" in model.lower()
            or "deepseek" in model.lower()
        ):
            model = "gemini-2.5-flash"
        # Safeguard: if using DeepSeek provider but model is Gemma/Google/Gemini, fallback to deepseek-v4-flash
        elif self.provider == "deepseek" and (
            "gemma" in model.lower()
            or "google" in model.lower()
            or "gemini" in model.lower()
        ):
            model = "deepseek-v4-flash"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if stream_thinking:
            payload["stream"] = True
            if self.provider == "openrouter":
                payload["include_reasoning"] = True
                payload["reasoning"] = {"exclude": False}
            elif self.provider == "deepseek":
                payload["thinking"] = {"type": "enabled"}

            from rich.console import Console

            console = Console()

            full_content = []
            reasoning_content = []
            has_started_thinking = False
            has_started_content = False
            printed_thinking_len = 0
            printed_content_len = 0

            try:
                with httpx.Client(timeout=60.0) as client:
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
                                    delta = chunk["choices"][0]["delta"]

                                    reasoning = delta.get(
                                        "reasoning_content"
                                    ) or delta.get("reasoning")
                                    content = delta.get("content")

                                    if reasoning:
                                        if not has_started_thinking:
                                            console.print(
                                                "[italic dim]Sir Pennyworth is pondering... [/italic dim]",
                                                end="",
                                            )
                                            has_started_thinking = True
                                        console.print(
                                            reasoning, end="", style="italic dim"
                                        )
                                        console.file.flush()
                                        reasoning_content.append(reasoning)

                                    if content:
                                        full_content.append(content)
                                        accumulated = "".join(full_content)

                                        if "<think>" in accumulated:
                                            if "</think>" not in accumulated:
                                                if not has_started_thinking:
                                                    console.print(
                                                        "[italic dim]Sir Pennyworth is pondering... [/italic dim]",
                                                        end="",
                                                    )
                                                    has_started_thinking = True
                                                thinking_part = accumulated.split(
                                                    "<think>", 1
                                                )[1]
                                                unprinted = thinking_part[
                                                    printed_thinking_len:
                                                ]
                                                if unprinted:
                                                    console.print(
                                                        unprinted,
                                                        end="",
                                                        style="italic dim",
                                                    )
                                                    printed_thinking_len += len(
                                                        unprinted
                                                    )
                                                console.file.flush()
                                            else:
                                                if has_started_thinking:
                                                    thinking_part = accumulated.split(
                                                        "</think>", 1
                                                    )[0].split("<think>", 1)[1]
                                                    unprinted = thinking_part[
                                                        printed_thinking_len:
                                                    ]
                                                    if unprinted:
                                                        console.print(
                                                            unprinted,
                                                            end="",
                                                            style="italic dim",
                                                        )
                                                    console.print()
                                                    has_started_thinking = False

                                                if not has_started_content:
                                                    console.print(
                                                        "[dim]Extracting metrics... [/dim]",
                                                        end="",
                                                    )
                                                    has_started_content = True

                                                actual_content = accumulated.split(
                                                    "</think>", 1
                                                )[1]
                                                new_content_len = (
                                                    len(actual_content)
                                                    - printed_content_len
                                                )
                                                if new_content_len > 0:
                                                    console.print(
                                                        "."
                                                        * (new_content_len // 5 or 1),
                                                        end="",
                                                    )
                                                    printed_content_len = len(
                                                        actual_content
                                                    )
                                                console.file.flush()
                                        else:
                                            if "<think>".startswith(accumulated):
                                                pass
                                            else:
                                                if not has_started_content:
                                                    if has_started_thinking:
                                                        console.print()
                                                        has_started_thinking = False
                                                    console.print(
                                                        "[dim]Extracting metrics... [/dim]",
                                                        end="",
                                                    )
                                                    has_started_content = True
                                                console.print(".", end="")
                                                console.file.flush()
                                except Exception:
                                    pass
                        if has_started_thinking or has_started_content:
                            console.print()
                return "".join(full_content)
            except Exception as e:
                raise RuntimeError(f"LLM streaming generation failed: {str(e)}")
        else:
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
