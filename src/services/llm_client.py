import json
import time
import logging
import httpx
import re
from src.core.config import load_config

logger = logging.getLogger(__name__)


def parse_serialized_prompt(prompt: str) -> list:
    """Parse a serialized history prompt string with role headers back to structured messages."""
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


def parse_partial_json(s: str) -> dict | None:
    s = clean_leading_json_wrapper(s)
    if not s.startswith("{"):
        return None

    res = {}

    # Extract "thought"
    thought_match = re.search(r'"thought"\s*:\s*"', s)
    thought_finished = False
    if thought_match:
        start_idx = thought_match.end()
        end_idx = start_idx
        while end_idx < len(s):
            if s[end_idx] == '"' and s[end_idx - 1] != "\\":
                break
            end_idx += 1
        res["thought"] = s[start_idx:end_idx]
        if end_idx < len(s):
            thought_finished = True
    res["_thought_finished"] = thought_finished

    # Extract "tool"
    tool_match = re.search(r'"tool"\s*:\s*"', s)
    tool_finished = False
    if tool_match:
        start_idx = tool_match.end()
        end_idx = start_idx
        while end_idx < len(s):
            if s[end_idx] == '"' and s[end_idx - 1] != "\\":
                break
            end_idx += 1
        res["tool"] = s[start_idx:end_idx]
        if end_idx < len(s):
            tool_finished = True
    res["_tool_finished"] = tool_finished

    # Extract "arguments"
    args_match = re.search(r'"arguments"\s*:\s*', s)
    args_finished = False
    if args_match:
        start_idx = args_match.end()
        remaining = s[start_idx:].strip()
        if remaining.startswith("{"):
            brace_count = 0
            end_idx = 0
            started = False
            for i, c in enumerate(remaining):
                if c == "{":
                    brace_count += 1
                    started = True
                elif c == "}":
                    brace_count -= 1
                if started and brace_count == 0:
                    end_idx = i + 1
                    break
            if end_idx > 0:
                res["arguments"] = remaining[:end_idx]
                args_finished = True
            else:
                res["arguments"] = remaining
        elif remaining.startswith('"'):
            end_idx = 1
            while end_idx < len(remaining):
                if remaining[end_idx] == '"' and remaining[end_idx - 1] != "\\":
                    break
                end_idx += 1
            res["arguments"] = remaining[1:end_idx]
            if end_idx < len(remaining):
                args_finished = True
        else:
            res["arguments"] = remaining
    res["_args_finished"] = args_finished

    return res


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
        prompt: str | list,
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.1,
        stream_thinking: bool = True,
    ) -> str:
        """Generate a response from the LLM model."""
        if not model:
            if self.provider == "gemini":
                model = (
                    getattr(self.settings, "gemini_model", None) or "gemini-2.5-flash"
                )
            elif self.provider == "deepseek":
                model = (
                    getattr(self.settings, "deepseek_model", None)
                    or "deepseek-v4-flash"
                )
            else:
                model = (
                    getattr(self.settings, "openrouter_model", None)
                    or "google/gemma-4-31b-it:free"
                )

        # Safeguard: if using Gemini provider but model is Gemma/OpenRouter/DeepSeek, fallback
        if self.provider == "gemini" and (
            "gemma" in model.lower()
            or "google" in model.lower()
            or "deepseek" in model.lower()
        ):
            model = getattr(self.settings, "gemini_model", None) or "gemini-2.5-flash"
        # Safeguard: if using DeepSeek provider but model is Gemma/Google/Gemini, fallback
        elif self.provider == "deepseek" and (
            "gemma" in model.lower()
            or "google" in model.lower()
            or "gemini" in model.lower()
        ):
            model = (
                getattr(self.settings, "deepseek_model", None) or "deepseek-v4-flash"
            )

        messages = []
        if isinstance(prompt, list):
            messages = list(prompt)
        else:
            prompt_str = str(prompt)
            if "--- USER ---" in prompt_str or "--- ASSISTANT ---" in prompt_str:
                messages = parse_serialized_prompt(prompt_str)
            else:
                messages.append({"role": "user", "content": prompt_str})

        # If system_prompt is provided and not already in messages, insert it at the beginning
        if system_prompt and not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": system_prompt})

        payload = {
            "model": model,
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
                    timeout_val = max(
                        getattr(self.settings, "llm_timeout", 30.0), 120.0
                    )
                    timeout_config = httpx.Timeout(
                        timeout=timeout_val, connect=10.0, read=timeout_val
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
                                            f"Error parsing stream chunk as JSON: {e}"
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

                                    try:
                                        reasoning = delta.get(
                                            "reasoning_content"
                                        ) or delta.get("reasoning")
                                        content = delta.get("content")

                                        if reasoning:
                                            if not has_started_thinking:
                                                safe_console_print(
                                                    console,
                                                    "[italic dim]Sir Pennyworth is pondering... [/italic dim]",
                                                    end="",
                                                    markup=True,
                                                )
                                                has_started_thinking = True
                                            safe_console_print(
                                                console,
                                                reasoning,
                                                end="",
                                                style="italic dim",
                                            )
                                            console.file.flush()
                                            reasoning_content.append(reasoning)

                                        if content:
                                            full_content.append(content)
                                            accumulated = "".join(full_content)

                                            if "<think>" in accumulated:
                                                if "</think>" not in accumulated:
                                                    if not has_started_thinking:
                                                        safe_console_print(
                                                            console,
                                                            "[italic dim]Sir Pennyworth is pondering... [/italic dim]",
                                                            end="",
                                                            markup=True,
                                                        )
                                                        has_started_thinking = True
                                                    thinking_part = accumulated.split(
                                                        "<think>", 1
                                                    )[1]
                                                    unprinted = thinking_part[
                                                        printed_thinking_len:
                                                    ]
                                                    if unprinted:
                                                        safe_console_print(
                                                            console,
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
                                                        thinking_part = (
                                                            accumulated.split(
                                                                "</think>", 1
                                                            )[0].split("<think>", 1)[1]
                                                        )
                                                        unprinted = thinking_part[
                                                            printed_thinking_len:
                                                        ]
                                                        if unprinted:
                                                            safe_console_print(
                                                                console,
                                                                unprinted,
                                                                end="",
                                                                style="italic dim",
                                                            )
                                                        safe_console_print(console, "")
                                                        has_started_thinking = False

                                                    if not has_started_content:
                                                        safe_console_print(
                                                            console,
                                                            "[dim]Extracting metrics... [/dim]",
                                                            end="",
                                                            markup=True,
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
                                                        safe_console_print(
                                                            console,
                                                            "."
                                                            * (
                                                                new_content_len // 5
                                                                or 1
                                                            ),
                                                            end="",
                                                            flush=True,
                                                        )
                                                        printed_content_len = len(
                                                            actual_content
                                                        )
                                            else:
                                                if "<think>".startswith(accumulated):
                                                    pass
                                                else:
                                                    if not has_started_content:
                                                        if has_started_thinking:
                                                            safe_console_print(
                                                                console, ""
                                                            )
                                                            has_started_thinking = False
                                                        safe_console_print(
                                                            console,
                                                            "[dim]Extracting metrics... [/dim]",
                                                            end="",
                                                            markup=True,
                                                        )
                                                        has_started_content = True
                                                    safe_console_print(
                                                        console, ".", end="", flush=True
                                                    )
                                    except Exception as e:
                                        logger.exception(
                                            f"Error processing stream chunk delta: {e}"
                                        )
                            if has_started_thinking or has_started_content:
                                safe_console_print(console, "")
                    return "".join(full_content)
                else:
                    timeout_val = max(
                        getattr(self.settings, "llm_timeout", 30.0), 120.0
                    )
                    timeout_config = httpx.Timeout(
                        timeout=timeout_val, connect=10.0, read=timeout_val
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
                    if stream_thinking:
                        raise RuntimeError(f"LLM streaming generation failed: {str(e)}")
                    else:
                        raise RuntimeError(f"LLM generation failed: {str(e)}")

                delay = initial_delay * (backoff**attempt)
                logger.warning(
                    f"LLM API request failed: {e}. Retrying in {delay:.1f}s (Attempt {attempt + 1}/{max_retries + 1})..."
                )
                time.sleep(delay)
