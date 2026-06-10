import asyncio
from pathlib import Path

import typer
from rich.table import Table
from prompt_toolkit import PromptSession

from src.core.config import Settings, save_config, load_config, mask_key
from src.utils import formatting
from src.utils.pig_animation import get_input_with_pig

app = typer.Typer(help="Manage Sir Pennyworth's configuration settings.")


async def _initialize_config_flow_async() -> Settings:
    session = PromptSession()

    full_name = await get_input_with_pig(session, prompt_text="Full Name (e.g. Jane Doe): ")
    email = await get_input_with_pig(session, prompt_text="Email Address (e.g. jane.doe@example.com): ")
    project_name = await get_input_with_pig(session, prompt_text="Project Name (e.g. Value_Investing_2026): ")
    api_key = await get_input_with_pig(session, prompt_text="Primary LLM API Key: ", is_password=True)

    text_model = await get_input_with_pig(session, prompt_text="Text-to-Text Model ID [google/gemma-2-9b-it]: ")
    if not text_model.strip():
        text_model = "google/gemma-2-9b-it"

    vision_model = await get_input_with_pig(session, prompt_text="Vision-to-Text Model ID [google/gemma-2-9b-it]: ")
    if not vision_model.strip():
        vision_model = "google/gemma-2-9b-it"

    default_ws = str(Path.home() / "Desktop")
    base_ws_dir = await get_input_with_pig(session, prompt_text=f"Workspace Path (Base folder for company workspaces) [{default_ws}]: ")
    if not base_ws_dir.strip():
        base_ws_dir = default_ws

    settings = Settings(
        full_name=full_name,
        email=email,
        project_name=project_name,
        primary_llm_api_key=api_key,
        text_model_id=text_model,
        vision_model_id=vision_model,
        base_workspace_dir=base_ws_dir,
    )
    save_config(settings)
    formatting.print_success("Configuration initialized successfully!")
    return settings


def initialize_config_flow() -> Settings:
    """Interactively guides the user to set up configuration and returns the Settings object."""
    formatting.speak(
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
        table.add_row("Primary LLM API Key", mask_key(settings.primary_llm_api_key))
        table.add_row("Text-to-Text Model ID", settings.text_model_id)
        table.add_row("Vision-to-Text Model ID", settings.vision_model_id)
        table.add_row("Base Workspace Dir", settings.base_workspace_dir)
        table.add_row("Active Ticker", settings.active_ticker or "[None]")
        table.add_row(
            "Active Workspace Path", settings.active_workspace_path or "[None]"
        )

        formatting.console.print(table)
    except Exception as e:
        formatting.print_error(str(e))
