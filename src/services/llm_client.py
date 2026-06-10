import json
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
        stream_thinking: bool = True,
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

        if stream_thinking:
            payload["stream"] = True
            from rich.console import Console

            console = Console()

            full_content = []
            reasoning_content = []
            has_started_thinking = False
            has_started_content = False

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
                                        reasoning_content.append(reasoning)

                                    if content:
                                        full_content.append(content)
                                        accumulated = "".join(full_content)

                                        if (
                                            "<think>" in accumulated
                                            and "</think>" not in accumulated
                                        ):
                                            if not has_started_thinking:
                                                console.print(
                                                    "[italic dim]Sir Pennyworth is pondering... [/italic dim]",
                                                    end="",
                                                )
                                                has_started_thinking = True
                                            print_token = content
                                            if "<think>" in content:
                                                print_token = content.split(
                                                    "<think>", 1
                                                )[1]
                                            console.print(
                                                print_token, end="", style="italic dim"
                                            )
                                        elif (
                                            "</think>" in accumulated
                                            and has_started_thinking
                                        ):
                                            if "</think>" in content:
                                                print_token = content.split(
                                                    "</think>", 1
                                                )[0]
                                                console.print(
                                                    print_token,
                                                    end="",
                                                    style="italic dim",
                                                )
                                            console.print()
                                            has_started_thinking = False
                                            has_started_content = True
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
