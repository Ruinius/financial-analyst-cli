import asyncio
from pathlib import Path

import typer
from rich.table import Table
from prompt_toolkit import PromptSession

from src.core.config import Settings, save_config, load_config, mask_key
from src.utils import formatting
from src.utils.pig_animation import get_input_with_pig, pig_state

app = typer.Typer(help="Manage Sir Pennyworth's configuration settings.")


async def _initialize_config_flow_async() -> Settings:
    session = PromptSession()

    full_name = await get_input_with_pig(
        session, prompt_text="Full Name (e.g. Jane Doe): "
    )
    email = await get_input_with_pig(
        session, prompt_text="Email Address (e.g. jane.doe@example.com): "
    )
    project_name = await get_input_with_pig(
        session, prompt_text="Project Name (e.g. Value_Investing_2026): "
    )
    api_provider = await get_input_with_pig(
        session, prompt_text="API Provider (openrouter/gemini/deepseek) [openrouter]: "
    )
    api_provider = api_provider.strip().lower()
    if not api_provider or api_provider not in ["openrouter", "gemini", "deepseek"]:
        api_provider = "openrouter"

    openrouter_api_key = None
    gemini_api_key = None
    deepseek_api_key = None

    if api_provider == "openrouter":
        openrouter_api_key = await get_input_with_pig(
            session, prompt_text="OpenRouter API Key: ", is_password=True
        )
        default_model = "google/gemma-4-31b-it:free"
    elif api_provider == "gemini":
        gemini_api_key = await get_input_with_pig(
            session, prompt_text="Gemini API Key: ", is_password=True
        )
        default_model = "gemini-2.5-flash"
    else:
        deepseek_api_key = await get_input_with_pig(
            session, prompt_text="DeepSeek API Key: ", is_password=True
        )
        default_model = "deepseek-v4-flash"

    text_model = await get_input_with_pig(
        session, prompt_text=f"Text-to-Text Model ID [{default_model}]: "
    )
    if not text_model.strip():
        text_model = default_model

    default_ws = str(Path.home() / "Desktop" / project_name.strip())
    base_ws_dir = await get_input_with_pig(
        session,
        prompt_text=f"Workspace Path (Base folder for company workspaces) [{default_ws}]: ",
    )
    if not base_ws_dir.strip():
        base_ws_dir = default_ws

    settings = Settings(
        full_name=full_name,
        email=email,
        project_name=project_name,
        api_provider=api_provider,
        openrouter_api_key=openrouter_api_key,
        gemini_api_key=gemini_api_key,
        deepseek_api_key=deepseek_api_key,
        primary_llm_api_key=openrouter_api_key or gemini_api_key or deepseek_api_key,
        text_model_id=text_model,
        base_workspace_dir=base_ws_dir,
    )

    save_config(settings)
    formatting.print_success("Configuration initialized successfully!")
    return settings


def initialize_config_flow() -> Settings:
    """Interactively guides the user to set up configuration and returns the Settings object."""
    pig_state.quote = (
        "Greetings! I am Sir Pennyworth, your financial concierge. "
        "Before we begin our financial trufflings, we must establish our settings."
    )
    return asyncio.run(_initialize_config_flow_async())


@app.command("init")
def config_init():
    """Interactively initialize credentials, directories, and LLM providers."""
    initialize_config_flow()


@app.command("show")
def config_show():
    """Display the current configuration with sensitive API keys masked."""
    try:
        settings = load_config()
        table = Table(
            title="Sir Pennyworth's Settings Registry",
            show_header=True,
            header_style=f"bold {formatting.COLOR_CHAR}",
        )
        table.add_column("Setting Key", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Full Name", settings.full_name)
        table.add_row("Email Address", settings.email)
        table.add_row("Project Name", settings.project_name)
        table.add_row("API Provider", settings.api_provider)
        table.add_row("OpenRouter API Key", mask_key(settings.openrouter_api_key or ""))
        table.add_row("Gemini API Key", mask_key(settings.gemini_api_key or ""))
        table.add_row(
            "DeepSeek API Key",
            mask_key(getattr(settings, "deepseek_api_key", None) or ""),
        )
        table.add_row(
            "Primary LLM API Key (Legacy)", mask_key(settings.primary_llm_api_key or "")
        )
        table.add_row("Text-to-Text Model ID", settings.text_model_id)
        table.add_row("Base Workspace Dir", settings.base_workspace_dir)

        table.add_row("Active Ticker", settings.active_ticker or "[None]")
        table.add_row(
            "Active Workspace Path", settings.active_workspace_path or "[None]"
        )

        formatting.console.print(table)
    except Exception as e:
        formatting.print_error(str(e))


@app.command("set")
def config_set(
    provider: str = typer.Option(
        None,
        "--provider",
        "-p",
        help="Set the active API provider (openrouter, gemini, or deepseek)",
    ),
    openrouter_key: str = typer.Option(
        None, "--openrouter-key", help="Set the OpenRouter API Key"
    ),
    gemini_key: str = typer.Option(None, "--gemini-key", help="Set the Gemini API Key"),
    deepseek_key: str = typer.Option(
        None, "--deepseek-key", help="Set the DeepSeek API Key"
    ),
):
    """Set the API provider and/or keys directly without the interactive wizard."""
    try:
        settings = load_config()
    except Exception:
        formatting.print_error(
            "Configuration not found or invalid. Please run 'fa config init' first."
        )
        raise typer.Exit(1)

    updated = False
    if provider is not None:
        p = provider.strip().lower()
        if p not in ["openrouter", "gemini", "deepseek"]:
            formatting.print_error(
                "Invalid provider. Supported providers are: openrouter, gemini, deepseek"
            )
            raise typer.Exit(1)
        settings.api_provider = p
        # Dynamically switch default models if they are set to other provider's defaults
        if p == "gemini":
            if (
                "gemma" in settings.text_model_id.lower()
                or "google" in settings.text_model_id.lower()
                or "deepseek" in settings.text_model_id.lower()
            ):
                settings.text_model_id = "gemini-2.5-flash"
        elif p == "openrouter":
            if (
                "gemini" in settings.text_model_id.lower()
                or "deepseek" in settings.text_model_id.lower()
            ):
                settings.text_model_id = "google/gemma-4-31b-it:free"
        elif p == "deepseek":
            if (
                "gemini" in settings.text_model_id.lower()
                or "gemma" in settings.text_model_id.lower()
                or "google" in settings.text_model_id.lower()
            ):
                settings.text_model_id = "deepseek-v4-flash"

        updated = True

    if openrouter_key is not None:
        settings.openrouter_api_key = openrouter_key.strip()
        if settings.api_provider == "openrouter":
            settings.primary_llm_api_key = openrouter_key.strip()
        updated = True

    if gemini_key is not None:
        settings.gemini_api_key = gemini_key.strip()
        if settings.api_provider == "gemini":
            settings.primary_llm_api_key = gemini_key.strip()
        updated = True

    if deepseek_key is not None:
        settings.deepseek_api_key = deepseek_key.strip()
        if settings.api_provider == "deepseek":
            settings.primary_llm_api_key = deepseek_key.strip()
        updated = True

    if not updated:
        formatting.print_warning("No configuration values were specified to update.")
        return

    try:
        save_config(settings)
        formatting.print_success("Configuration updated successfully!")
    except Exception as e:
        formatting.print_error(f"Failed to save updated configuration: {str(e)}")
        raise typer.Exit(1)
