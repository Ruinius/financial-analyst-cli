import sys

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import typer

from pathlib import Path
from src.core.config import config_exists, load_config
from src.cli.commands import config as config_cmd
from src.cli.commands import use as use_cmd
from src.cli.commands import query as query_cmd
from src.cli.commands import chat as chat_cmd
from src.cli.commands import viewer as viewer_cmd
from src.utils import formatting
from src.services.edgar_client import EdgarClient
from src.agents.orchestrator_pipelines.ingest import Ingester


def patch_typer_help() -> None:
    """Monkey-patch typer.rich_utils.rich_format_help to output Options below Commands."""
    import typer.rich_utils
    from collections import defaultdict

    def custom_rich_format_help(
        *,
        obj,
        ctx,
        markup_mode,
    ) -> None:
        console = typer.rich_utils._get_rich_console()

        # Print usage
        console.print(
            typer.rich_utils.Padding(
                typer.rich_utils.highlighter(obj.get_usage(ctx)), 1
            ),
            style=typer.rich_utils.STYLE_USAGE_COMMAND,
        )

        # Print command / group help if we have some
        if obj.help:
            # Print with some padding
            console.print(
                typer.rich_utils.Padding(
                    typer.rich_utils.Align(
                        typer.rich_utils._get_help_text(
                            obj=obj,
                            markup_mode=markup_mode,
                        ),
                        pad=False,
                    ),
                    (0, 1, 1, 1),
                )
            )

        panel_to_arguments = defaultdict(list)
        panel_to_options = defaultdict(list)
        for param in obj.get_params(ctx):
            # Skip if option is hidden
            if getattr(param, "hidden", False):
                continue
            if isinstance(param, typer.rich_utils.TyperArgument):
                panel_name = (
                    getattr(param, typer.rich_utils._RICH_HELP_PANEL_NAME, None)
                    or typer.rich_utils.ARGUMENTS_PANEL_TITLE
                )
                panel_to_arguments[panel_name].append(param)
            elif isinstance(param, typer.rich_utils.TyperOption):
                panel_name = (
                    getattr(param, typer.rich_utils._RICH_HELP_PANEL_NAME, None)
                    or typer.rich_utils.OPTIONS_PANEL_TITLE
                )
                panel_to_options[panel_name].append(param)

        # 1. Print Arguments Panel first (as in original)
        default_arguments = panel_to_arguments.get(
            typer.rich_utils.ARGUMENTS_PANEL_TITLE, []
        )
        typer.rich_utils._print_options_panel(
            name=typer.rich_utils.ARGUMENTS_PANEL_TITLE,
            params=default_arguments,
            ctx=ctx,
            markup_mode=markup_mode,
            console=console,
        )
        for panel_name, arguments in panel_to_arguments.items():
            if panel_name == typer.rich_utils.ARGUMENTS_PANEL_TITLE:
                # Already printed above
                continue
            typer.rich_utils._print_options_panel(
                name=panel_name,
                params=arguments,
                ctx=ctx,
                markup_mode=markup_mode,
                console=console,
            )

        # 2. Print Commands Panel (if it's a Group/TyperGroup)
        if isinstance(obj, typer.rich_utils.TyperGroup):
            panel_to_commands = defaultdict(list)
            for command_name in obj.list_commands(ctx):
                command = obj.get_command(ctx, command_name)
                if command and not command.hidden:
                    panel_name = (
                        getattr(command, typer.rich_utils._RICH_HELP_PANEL_NAME, None)
                        or typer.rich_utils.COMMANDS_PANEL_TITLE
                    )
                    panel_to_commands[panel_name].append(command)

            # Identify the longest command name in all panels
            max_cmd_len = max(
                [
                    len(command.name or "")
                    for commands in panel_to_commands.values()
                    for command in commands
                ],
                default=0,
            )

            # Print each command group panel
            default_commands = panel_to_commands.get(
                typer.rich_utils.COMMANDS_PANEL_TITLE, []
            )
            typer.rich_utils._print_commands_panel(
                name=typer.rich_utils.COMMANDS_PANEL_TITLE,
                commands=default_commands,
                markup_mode=markup_mode,
                console=console,
                cmd_len=max_cmd_len,
            )
            for panel_name, commands in panel_to_commands.items():
                if panel_name == typer.rich_utils.COMMANDS_PANEL_TITLE:
                    # Already printed above
                    continue
                typer.rich_utils._print_commands_panel(
                    name=panel_name,
                    commands=commands,
                    markup_mode=markup_mode,
                    console=console,
                    cmd_len=max_cmd_len,
                )

        # 3. Print Options Panel (originally printed before Commands)
        default_options = panel_to_options.get(typer.rich_utils.OPTIONS_PANEL_TITLE, [])
        typer.rich_utils._print_options_panel(
            name=typer.rich_utils.OPTIONS_PANEL_TITLE,
            params=default_options,
            ctx=ctx,
            markup_mode=markup_mode,
            console=console,
        )
        for panel_name, options in panel_to_options.items():
            if panel_name == typer.rich_utils.OPTIONS_PANEL_TITLE:
                # Already printed above
                continue
            typer.rich_utils._print_options_panel(
                name=panel_name,
                params=options,
                ctx=ctx,
                markup_mode=markup_mode,
                console=console,
            )

        # Epilogue if we have it
        if obj.epilog:
            # Remove single linebreaks, replace double with single
            lines = obj.epilog.split("\n\n")
            epilogue = "\n".join([x.replace("\n", " ").strip() for x in lines])
            epilogue_text = typer.rich_utils._make_rich_text(
                text=epilogue, markup_mode=markup_mode
            )
            console.print(
                typer.rich_utils.Padding(
                    typer.rich_utils.Align(epilogue_text, pad=False), 1
                )
            )

    typer.rich_utils.rich_format_help = custom_rich_format_help


# Apply the patch immediately upon import
patch_typer_help()

app = typer.Typer(
    name="fa",
    help="Sir Pennyworth's Financial Analyst CLI Assistant",
    no_args_is_help=True,
)

# 1. Register use command
app.command("use")(use_cmd.main_use)

# 2. Register run command
run_app = typer.Typer(help="Execute data pipeline stages.")


@run_app.callback(invoke_without_command=True)
def run_callback(
    ctx: typer.Context,
    ticker: str = typer.Option(
        None, "--ticker", "-t", help="Company ticker symbol (e.g. AAPL)"
    ),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-n"),
):
    """Execute data pipeline stages. Calling 'fa run' directly runs the full pipeline (ingest -> extract -> analyze -> model)."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        settings = load_config()
    except Exception as e:
        formatting.print_error(f"Configuration error: {str(e)}")
        raise typer.Exit(1)

    if ticker:
        use_cmd.main_use(ticker)
        settings = load_config()

    active_ticker = settings.active_ticker
    if not active_ticker:
        formatting.print_error(
            "No active ticker selected. Please specify a ticker or run 'fa use <ticker>' first."
        )
        raise typer.Exit(1)

    # Ingestion limit prompt if there are raw files to process
    limit = None
    if settings.active_workspace_path:
        ingest_dir = Path(settings.active_workspace_path) / "1_ingest_data"
        raw_files = (
            [
                p
                for p in ingest_dir.iterdir()
                if p.is_file()
                and p.name.lower() != "readme.md"
                and not p.name.startswith(".")
            ]
            if ingest_dir.exists()
            else []
        )
        if raw_files:
            formatting.speak(
                f"Splendid! I found {len(raw_files)} raw file(s) ready for ingestion."
            )
            if non_interactive:
                response = "all"
            else:
                response = typer.prompt(
                    "How many files would you like to process?", default="all"
                )

            if response.strip().lower() != "all":
                try:
                    limit = int(response.strip())
                except ValueError:
                    formatting.print_warning(
                        "Invalid number of files entered. Defaulting to processing all files."
                    )
                    limit = None

    formatting.print_info(f"Starting full data pipeline for {active_ticker}...")
    try:
        from src.agents.blackboard_orchestrator import BlackboardOrchestrator
        import asyncio

        orchestrator = BlackboardOrchestrator(settings=settings)
        asyncio.run(
            orchestrator.run_pipeline(
                active_ticker,
                stage=None,
                non_interactive=non_interactive,
                limit=limit,
            )
        )
        formatting.print_success(
            f"Successfully executed full data pipeline for {active_ticker}!"
        )
    except Exception as e:
        formatting.print_error(f"Full pipeline execution failed: {str(e)}")
        raise typer.Exit(1)


app.add_typer(run_app, name="run")


@run_app.command("edgar")
def run_edgar(
    ticker: str = typer.Argument(None, help="Company ticker symbol (e.g. AAPL)"),
    years: int = typer.Option(5, "--years", "-y", help="Years to download"),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-n"),
    agent: str = typer.Option(None, "--agent", "-a"),
):
    """Download filings from SEC EDGAR."""
    try:
        settings = load_config()
    except Exception as e:
        formatting.print_error(f"Configuration error: {str(e)}")
        raise typer.Exit(1)

    if ticker:
        use_cmd.main_use(ticker)
        settings = load_config()

    active_ticker = settings.active_ticker
    if not active_ticker:
        formatting.print_error(
            "No active ticker selected. Please specify a ticker or run 'fa use <ticker>' first."
        )
        raise typer.Exit(1)

    formatting.speak(
        f"Ah, let us fetch the filings for {active_ticker} from the SEC EDGAR archives, my dear fellow!"
    )
    formatting.print_info(
        f"Starting filings download for {active_ticker} (limit {years} years)..."
    )
    try:
        client = EdgarClient()
        paths = client.download_filings(active_ticker, years)
        if paths:
            formatting.print_success(
                f"Successfully downloaded {len(paths)} filings for {active_ticker} to 1_ingest_data/."
            )
        else:
            formatting.print_warning(
                f"No filings found or downloaded for {active_ticker} in the last {years} years."
            )
    except Exception as e:
        formatting.print_error(f"Failed to download filings: {str(e)}")
        raise typer.Exit(1)


@run_app.command("ingest")
def run_ingest(
    ticker: str = typer.Option(None, "--ticker", "-t"),
    heal: bool = typer.Option(
        False,
        "--heal",
        help="Run metadata self-healing and Quality Check Agent on existing parsed files",
    ),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-n"),
    agent: str = typer.Option(None, "--agent", "-a"),
):
    """Parse and ingest raw files."""
    try:
        settings = load_config()
    except Exception as e:
        formatting.print_error(f"Configuration error: {str(e)}")
        raise typer.Exit(1)

    if ticker:
        use_cmd.main_use(ticker)
        settings = load_config()

    if not settings.active_workspace_path:
        formatting.print_error(
            "No active workspace is selected. Use 'fa use <ticker>' first."
        )
        raise typer.Exit(1)

    if heal:
        formatting.print_info("Starting metadata self-healing stage...")
        try:
            ingester = Ingester()
            ingester.run_self_healing()
            formatting.print_success("Successfully completed self-healing check.")
            return
        except Exception as e:
            formatting.print_error(f"Self-healing failed: {str(e)}")
            raise typer.Exit(1)

    ingest_dir = Path(settings.active_workspace_path) / "1_ingest_data"
    raw_files = (
        [
            p
            for p in ingest_dir.iterdir()
            if p.is_file()
            and p.name.lower() != "readme.md"
            and not p.name.startswith(".")
        ]
        if ingest_dir.exists()
        else []
    )

    if not raw_files:
        formatting.speak(
            "No raw files found to ingest in our workspace directory, my good sir!"
        )
        return

    formatting.speak(
        f"Splendid! I found {len(raw_files)} raw file(s) ready for ingestion."
    )

    if non_interactive:
        response = "all"
    else:
        response = typer.prompt(
            "How many files would you like to process?", default="all"
        )

    limit = None
    if response.strip().lower() != "all":
        try:
            limit = int(response.strip())
        except ValueError:
            formatting.print_warning(
                "Invalid number of files entered. Defaulting to processing all files."
            )
            limit = None

    formatting.print_info("Starting ingestion stage...")
    try:
        ingester = Ingester()
        ingester.run_ingestion(limit=limit)
        formatting.print_success("Successfully processed raw files.")
    except Exception as e:
        formatting.print_error(f"Ingestion failed: {str(e)}")
        raise typer.Exit(1)


@run_app.command("extract")
def run_extract(
    ticker: str = typer.Option(None, "--ticker", "-t"),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-n"),
    agent: str = typer.Option(None, "--agent", "-a"),
):
    """Extract statements and metrics from parsed data."""
    try:
        settings = load_config()
    except Exception as e:
        formatting.print_error(f"Configuration error: {str(e)}")
        raise typer.Exit(1)

    if ticker:
        use_cmd.main_use(ticker)
        settings = load_config()

    active_ticker = settings.active_ticker
    if not active_ticker:
        formatting.print_error(
            "No active ticker selected. Please specify a ticker or run 'fa use <ticker>' first."
        )
        raise typer.Exit(1)

    formatting.print_info(f"Starting extraction stage for {active_ticker}...")
    try:
        from src.agents.blackboard_orchestrator import BlackboardOrchestrator
        import asyncio

        orchestrator = BlackboardOrchestrator(settings=settings)
        asyncio.run(
            orchestrator.run_pipeline(
                active_ticker,
                stage="extract",
                agent=agent,
                non_interactive=non_interactive,
            )
        )
        formatting.print_success(
            "Successfully extracted financial data and calculated metrics."
        )
    except Exception as e:
        formatting.print_error(f"Extraction failed: {str(e)}")
        raise typer.Exit(1)


@run_app.command("analyze")
def run_analyze(
    ticker: str = typer.Option(None, "--ticker", "-t"),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-n"),
    agent: str = typer.Option(None, "--agent", "-a"),
):
    """Synthesize longitudinal trends and analyst views."""
    try:
        settings = load_config()
    except Exception as e:
        formatting.print_error(f"Configuration error: {str(e)}")
        raise typer.Exit(1)

    if ticker:
        use_cmd.main_use(ticker)
        settings = load_config()

    active_ticker = settings.active_ticker
    if not active_ticker:
        formatting.print_error(
            "No active ticker selected. Please specify a ticker or run 'fa use <ticker>' first."
        )
        raise typer.Exit(1)

    formatting.print_info(
        f"Starting historical trend synthesis stage for {active_ticker}..."
    )
    try:
        from src.agents.blackboard_orchestrator import BlackboardOrchestrator
        import asyncio

        orchestrator = BlackboardOrchestrator(settings=settings)
        asyncio.run(
            orchestrator.run_pipeline(
                active_ticker,
                stage="analyze",
                agent=agent,
                non_interactive=non_interactive,
            )
        )
        formatting.print_success(
            "Successfully synthesized all longitudinal financial trends and views."
        )
    except Exception as e:
        formatting.print_error(f"Trend synthesis failed: {str(e)}")
        raise typer.Exit(1)


@run_app.command("model")
def run_model(
    ticker: str = typer.Option(None, "--ticker", "-t"),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-n"),
    agent: str = typer.Option(None, "--agent", "-a"),
):
    """Propose assumptions and construct valuation models."""
    try:
        settings = load_config()
    except Exception as e:
        formatting.print_error(f"Configuration error: {str(e)}")
        raise typer.Exit(1)

    if ticker:
        use_cmd.main_use(ticker)
        settings = load_config()

    active_ticker = settings.active_ticker
    if not active_ticker:
        formatting.print_error(
            "No active ticker selected. Please specify a ticker or run 'fa use <ticker>' first."
        )
        raise typer.Exit(1)

    formatting.print_info(f"Starting financial modeling stage for {active_ticker}...")
    try:
        from src.agents.blackboard_orchestrator import BlackboardOrchestrator
        import asyncio

        orchestrator = BlackboardOrchestrator(settings=settings)
        asyncio.run(
            orchestrator.run_pipeline(
                active_ticker,
                stage="model",
                agent=agent,
                non_interactive=non_interactive,
            )
        )
        formatting.print_success("Successfully generated valuation models.")
    except Exception as e:
        formatting.print_error(f"Modeling failed: {str(e)}")
        raise typer.Exit(1)


@run_app.command("curate_wiki")
def run_curate_wiki(
    ticker: str = typer.Option(None, "--ticker", "-t"),
):
    """Run CuratorAgent to compile or update qualitative wiki files under write lock."""
    try:
        settings = load_config()
    except Exception as e:
        formatting.print_error(f"Configuration error: {str(e)}")
        raise typer.Exit(1)

    if ticker:
        use_cmd.main_use(ticker)
        settings = load_config()

    active_ticker = settings.active_ticker
    if not active_ticker:
        formatting.print_error(
            "No active ticker selected. Please specify a ticker or run 'fa use <ticker>' first."
        )
        raise typer.Exit(1)

    formatting.print_info(f"Curating qualitative wiki for {active_ticker}...")
    try:
        from src.agents.curator_agent import CuratorAgent

        curator = CuratorAgent(settings=settings)
        curator.curate_wiki(active_ticker)
        formatting.print_success("Successfully compiled and updated qualitative wiki.")
    except Exception as e:
        formatting.print_error(f"Wiki curation failed: {str(e)}")
        raise typer.Exit(1)


# 3. Register chat command
app.command("chat")(chat_cmd.main_chat)

# 4. Register query command
app.add_typer(query_cmd.app, name="query", help="Query parsed metrics and evaluations.")

# 5. Register viewer command
app.command("viewer")(viewer_cmd.main_viewer)

# 6. Register config commands
app.add_typer(config_cmd.app, name="config")


@app.callback()
def main_callback(ctx: typer.Context):
    """Global callback."""
    pass


def main():
    args = sys.argv[1:]

    # Allow config init or help options without configuration
    is_help = "--help" in args or "-h" in args
    is_config_init = "config" in args and "init" in args

    # Print welcome banner when launched with no arguments or --help
    if not args or is_help:
        msg = "Greetings! I am Sir Pennyworth, your financial concierge. Ready to begin our financial trufflings?"
        for arg in args:
            if arg == "use":
                msg = "Greetings! I am Sir Pennyworth, your financial concierge. Shall we switch our active workspace, my good sir?"
                break
            elif arg == "chat":
                msg = "Greetings! I am Sir Pennyworth, your financial concierge. Shall we converse in our interactive REPL session, my good sir?"
                break
            elif arg == "viewer":
                msg = "Greetings! I am Sir Pennyworth, your financial concierge. Shall we launch the local HTML valuation viewer, my good sir?"
                break
            elif arg == "run":
                msg = "Greetings! I am Sir Pennyworth, your financial concierge. Shall we execute our data pipeline stages, my good sir?"
                break
            elif arg == "query":
                msg = "Greetings! I am Sir Pennyworth, your financial concierge. Shall we query our parsed metrics and evaluations, my good sir?"
                break
            elif arg == "config":
                msg = "Greetings! I am Sir Pennyworth, your financial concierge. Shall we manage our configuration settings, my good sir?"
                break
        formatting.speak(msg)

    if not config_exists() and not is_help and not is_config_init:
        try:
            config_cmd.initialize_config_flow()
        except typer.Abort:
            formatting.print_error("Configuration flow was aborted.")
            sys.exit(1)
        except Exception as e:
            formatting.print_error(f"Failed to auto-initialize settings: {str(e)}")
            sys.exit(1)

    try:
        app()
    except KeyboardInterrupt:
        formatting.speak(
            "Tata for now, my good sir! Operation halted by user.",
            title="Sir Pennyworth",
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
