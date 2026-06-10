import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

from src.core.exceptions import ConfigNotFoundError, ConfigError

CONFIG_FILE_PATH = Path(".env")


class Settings(BaseModel):
    full_name: str = Field(..., description="Full Name of the user")
    email: str = Field(..., description="Email address of the user")
    project_name: str = Field(..., description="Project name")
    primary_llm_api_key: str = Field(..., description="Primary LLM API key")
    text_model_id: str = Field(
        "google/gemma-2-9b-it", description="Text-to-Text Model ID"
    )
    vision_model_id: str = Field(
        "google/gemma-2-9b-it", description="Vision-to-Text Model ID"
    )
    base_workspace_dir: str = Field(
        ..., description="Base directory containing workspaces"
    )
    active_ticker: Optional[str] = Field(None, description="Active ticker symbol")
    active_workspace_path: Optional[str] = Field(
        None, description="Active company workspace directory path"
    )


def config_exists() -> bool:
    """Check if the settings file exists."""
    return CONFIG_FILE_PATH.exists()


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
