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

    from src.core.config import config_exists

    existing_settings = None
    if config_exists():
        try:
            existing_settings = load_config()
        except Exception:
            pass

    default_name = existing_settings.full_name if existing_settings else ""
    prompt_name = (
        f"Full Name (e.g. Jane Doe) [{default_name}]: "
        if default_name
        else "Full Name (e.g. Jane Doe): "
    )
    full_name = await get_input_with_pig(session, prompt_text=prompt_name)
    full_name = full_name.strip()
    if not full_name and default_name:
        full_name = default_name

    default_email = existing_settings.email if existing_settings else ""
    prompt_email = (
        f"Email Address (e.g. jane.doe@example.com) [{default_email}]: "
        if default_email
        else "Email Address (e.g. jane.doe@example.com): "
    )
    email = await get_input_with_pig(session, prompt_text=prompt_email)
    email = email.strip()
    if not email and default_email:
        email = default_email

    default_project = existing_settings.project_name if existing_settings else ""
    prompt_project = (
        f"Project Name (e.g. Value_Investing_2026) [{default_project}]: "
        if default_project
        else "Project Name (e.g. Value_Investing_2026): "
    )
    project_name = await get_input_with_pig(session, prompt_text=prompt_project)
    project_name = project_name.strip()
    if not project_name and default_project:
        project_name = default_project

    default_provider = (
        existing_settings.api_provider if existing_settings else "openrouter"
    )
    prompt_provider = (
        f"API Provider (openrouter/gemini/deepseek) [{default_provider}]: "
    )
    api_provider = await get_input_with_pig(session, prompt_text=prompt_provider)
    api_provider = api_provider.strip().lower()
    if not api_provider or api_provider not in ["openrouter", "gemini", "deepseek"]:
        api_provider = default_provider

    existing_openrouter = (
        existing_settings.openrouter_api_key if existing_settings else None
    )
    existing_gemini = existing_settings.gemini_api_key if existing_settings else None
    existing_deepseek = (
        existing_settings.deepseek_api_key if existing_settings else None
    )

    openrouter_api_key = None
    gemini_api_key = None
    deepseek_api_key = None

    if api_provider == "openrouter":
        prompt_text = "OpenRouter API Key: "
        if existing_openrouter:
            masked = mask_key(existing_openrouter)
            prompt_text = f"OpenRouter API Key [{masked}]: "
        val = await get_input_with_pig(
            session, prompt_text=prompt_text, is_password=True
        )
        val = val.strip()
        if not val and existing_openrouter:
            openrouter_api_key = existing_openrouter
        else:
            openrouter_api_key = val if val else None

        if existing_settings and existing_settings.api_provider == "openrouter":
            default_model = existing_settings.text_model_id or "google/gemma-4-31b-it"
        else:
            default_model = (
                existing_settings.openrouter_model if existing_settings else None
            ) or "google/gemma-4-31b-it"

    elif api_provider == "gemini":
        prompt_text = "Gemini API Key: "
        if existing_gemini:
            masked = mask_key(existing_gemini)
            prompt_text = f"Gemini API Key [{masked}]: "
        val = await get_input_with_pig(
            session, prompt_text=prompt_text, is_password=True
        )
        val = val.strip()
        if not val and existing_gemini:
            gemini_api_key = existing_gemini
        else:
            gemini_api_key = val if val else None

        if existing_settings and existing_settings.api_provider == "gemini":
            default_model = existing_settings.text_model_id or "gemini-3.1-flash-lite"
        else:
            default_model = (
                existing_settings.gemini_model if existing_settings else None
            ) or "gemini-3.1-flash-lite"

    else:
        prompt_text = "DeepSeek API Key: "
        if existing_deepseek:
            masked = mask_key(existing_deepseek)
            prompt_text = f"DeepSeek API Key [{masked}]: "
        val = await get_input_with_pig(
            session, prompt_text=prompt_text, is_password=True
        )
        val = val.strip()
        if not val and existing_deepseek:
            deepseek_api_key = existing_deepseek
        else:
            deepseek_api_key = val if val else None

        if existing_settings and existing_settings.api_provider == "deepseek":
            default_model = existing_settings.text_model_id or "deepseek-v4-flash"
        else:
            default_model = (
                existing_settings.deepseek_model if existing_settings else None
            ) or "deepseek-v4-flash"

    text_model = await get_input_with_pig(
        session, prompt_text=f"Text-to-Text Model ID [{default_model}]: "
    )
    text_model = text_model.strip()
    if not text_model:
        text_model = default_model

    # Retain the existing keys for other providers that weren't selected
    if existing_settings:
        if api_provider != "openrouter":
            openrouter_api_key = existing_openrouter
        if api_provider != "gemini":
            gemini_api_key = existing_gemini
        if api_provider != "deepseek":
            deepseek_api_key = existing_deepseek

    # Determine default workspace path
    if existing_settings:
        default_ws = existing_settings.base_workspace_dir
    else:
        default_ws = str(Path.home() / "Desktop" / project_name.strip())

    base_ws_dir = await get_input_with_pig(
        session,
        prompt_text=f"Workspace Path (Base folder for company workspaces) [{default_ws}]: ",
    )
    base_ws_dir = base_ws_dir.strip()
    if not base_ws_dir:
        base_ws_dir = default_ws

    # Preserve other existing configuration fields
    gemini_model = existing_settings.gemini_model if existing_settings else None
    openrouter_model = existing_settings.openrouter_model if existing_settings else None
    deepseek_model = existing_settings.deepseek_model if existing_settings else None

    # Update the provider's specific model if they configured it in the text_model prompt
    if api_provider == "openrouter":
        openrouter_model = text_model
    elif api_provider == "gemini":
        gemini_model = text_model
    else:
        deepseek_model = text_model

    active_ticker = existing_settings.active_ticker if existing_settings else None
    active_workspace_path = (
        existing_settings.active_workspace_path if existing_settings else None
    )
    llm_timeout = existing_settings.llm_timeout if existing_settings else 30.0
    concurrency_limit_company = (
        existing_settings.concurrency_limit_company if existing_settings else 1
    )
    concurrency_limit_document = (
        existing_settings.concurrency_limit_document if existing_settings else 3
    )
    concurrency_limit_phase = (
        existing_settings.concurrency_limit_phase if existing_settings else 3
    )

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
        gemini_model=gemini_model,
        openrouter_model=openrouter_model,
        deepseek_model=deepseek_model,
        base_workspace_dir=base_ws_dir,
        active_ticker=active_ticker,
        active_workspace_path=active_workspace_path,
        llm_timeout=llm_timeout,
        concurrency_limit_company=concurrency_limit_company,
        concurrency_limit_document=concurrency_limit_document,
        concurrency_limit_phase=concurrency_limit_phase,
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
        table.add_row("Gemini Model", settings.gemini_model or "gemini-3.1-flash-lite")
        table.add_row(
            "OpenRouter Model",
            settings.openrouter_model or "google/gemma-4-31b-it",
        )
        table.add_row("DeepSeek Model", settings.deepseek_model or "deepseek-v4-flash")
        table.add_row("Text-to-Text Model ID (Active)", settings.text_model_id)
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
    gemini_model: str = typer.Option(
        None, "--gemini-model", help="Set the Gemini Model ID"
    ),
    openrouter_model: str = typer.Option(
        None, "--openrouter-model", help="Set the OpenRouter Model ID"
    ),
    deepseek_model: str = typer.Option(
        None, "--deepseek-model", help="Set the DeepSeek Model ID"
    ),
):
    """Set the API provider, keys, and/or models directly without the interactive wizard."""
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
        # Dynamically switch active model to the provider's configured model
        if p == "gemini":
            settings.text_model_id = settings.gemini_model or "gemini-3.1-flash-lite"
        elif p == "openrouter":
            settings.text_model_id = (
                settings.openrouter_model or "google/gemma-4-31b-it"
            )
        elif p == "deepseek":
            settings.text_model_id = settings.deepseek_model or "deepseek-v4-flash"

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

    if gemini_model is not None:
        settings.gemini_model = gemini_model.strip()
        if settings.api_provider == "gemini":
            settings.text_model_id = gemini_model.strip()
        updated = True

    if openrouter_model is not None:
        settings.openrouter_model = openrouter_model.strip()
        if settings.api_provider == "openrouter":
            settings.text_model_id = openrouter_model.strip()
        updated = True

    if deepseek_model is not None:
        settings.deepseek_model = deepseek_model.strip()
        if settings.api_provider == "deepseek":
            settings.text_model_id = deepseek_model.strip()
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
