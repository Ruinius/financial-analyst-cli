from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, model_validator

from src.core.exceptions import ConfigNotFoundError, ConfigError

CONFIG_FILE_PATH = Path(".env")


class Settings(BaseModel):
    full_name: str = Field(..., description="Full Name of the user")
    email: str = Field(..., description="Email address of the user")
    project_name: str = Field(..., description="Project name")
    primary_llm_api_key: Optional[str] = Field(
        None, description="Primary LLM API key (legacy/fallback)"
    )
    api_provider: str = Field(
        "openrouter",
        description="Active API provider (openrouter, gemini, or deepseek)",
    )
    openrouter_api_key: Optional[str] = Field(None, description="OpenRouter API key")
    gemini_api_key: Optional[str] = Field(None, description="Gemini API key")
    deepseek_api_key: Optional[str] = Field(None, description="DeepSeek API key")

    text_model_id: str = Field(
        "google/gemma-4-31b-it:free", description="Text-to-Text Model ID"
    )

    gemini_model: Optional[str] = Field(
        "gemini-2.5-flash", description="Gemini model preference"
    )
    openrouter_model: Optional[str] = Field(
        "google/gemma-4-31b-it:free", description="OpenRouter model preference"
    )
    deepseek_model: Optional[str] = Field(
        "deepseek-v4-flash", description="DeepSeek model preference"
    )

    base_workspace_dir: str = Field(
        ..., description="Base directory containing workspaces"
    )
    active_ticker: Optional[str] = Field(None, description="Active ticker symbol")
    active_workspace_path: Optional[str] = Field(
        None, description="Active company workspace directory path"
    )
    llm_timeout: float = Field(
        30.0, description="Timeout for LLM API requests in seconds"
    )
    concurrency_limit_company: int = Field(
        1, description="Concurrency limit for company runs"
    )
    concurrency_limit_document: int = Field(
        3, description="Concurrency limit for document processing"
    )
    concurrency_limit_phase: int = Field(
        3, description="Concurrency limit for stage/phase execution"
    )

    @model_validator(mode="before")
    @classmethod
    def migrate_and_sync_models(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            return data

        # Normalize keys to lowercase since load_config parses keys as lower()
        provider = data.get("api_provider") or "openrouter"
        provider = provider.lower()

        text_model = data.get("text_model_id")

        # Determine defaults for each provider model
        default_gemini = "gemini-2.5-flash"
        default_openrouter = "google/gemma-4-31b-it:free"
        default_deepseek = "deepseek-v4-flash"

        # Populate provider-specific models if they are not explicitly specified
        if "gemini_model" not in data or not data["gemini_model"]:
            if provider == "gemini" and text_model:
                data["gemini_model"] = text_model
            else:
                data["gemini_model"] = default_gemini

        if "openrouter_model" not in data or not data["openrouter_model"]:
            if provider == "openrouter" and text_model:
                data["openrouter_model"] = text_model
            else:
                data["openrouter_model"] = default_openrouter

        if "deepseek_model" not in data or not data["deepseek_model"]:
            if provider == "deepseek" and text_model:
                data["deepseek_model"] = text_model
            else:
                data["deepseek_model"] = default_deepseek

        # Now sync text_model_id to the active provider's preference
        if provider == "gemini":
            data["text_model_id"] = data["gemini_model"]
        elif provider == "deepseek":
            data["text_model_id"] = data["deepseek_model"]
        else:
            data["text_model_id"] = data["openrouter_model"]

        return data


def config_exists() -> bool:
    """Check if the settings file exists and contains valid config settings."""
    if not CONFIG_FILE_PATH.exists():
        return False
    try:
        required_keys = {"full_name", "email"}
        found_keys = set()
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key = line.split("=", 1)[0].strip().lower()
                    if key in required_keys:
                        found_keys.add(key)
        return len(found_keys) == len(required_keys)
    except Exception:
        return False


def load_config() -> Settings:
    """Load configuration from the configuration file."""
    if not config_exists():
        raise ConfigNotFoundError(
            "Configuration file not found. Please run 'fa config init' first."
        )
    try:
        data = {}
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]

                    if value == "":
                        data[key.lower()] = None
                    else:
                        data[key.lower()] = value
        return Settings(**data)
    except Exception as e:
        raise ConfigError(f"Failed to load configuration: {str(e)}")


def save_config(settings: Settings) -> None:
    """Save configuration to the configuration file."""
    try:
        CONFIG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            for key, value in settings.model_dump().items():
                env_key = key.upper()
                env_value = "" if value is None else str(value)
                f.write(f'{env_key}="{env_value}"\n')
    except Exception as e:
        raise ConfigError(f"Failed to save configuration: {str(e)}")


def mask_key(key: str) -> str:
    """Mask a sensitive API key, revealing only a small prefix and suffix."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    # standard format e.g. sk-1234...89ab or just showing prefix and suffix
    prefix = key[:3]
    suffix = key[-4:]
    return f"{prefix}...{suffix}"
