import sys

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import csv
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
from src.pipeline.ingester import Ingester
from src.pipeline.extractor_orchestrator import Extractor
from src.pipeline.modeler import Modeler


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
app.add_typer(run_app, name="run")


@run_app.command("edgar")
def run_edgar(
    ticker: str = typer.Argument(None, help="Company ticker symbol (e.g. AAPL)"),
    years: int = typer.Option(5, "--years", "-y", help="Years to download"),
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

    response = typer.prompt("How many files would you like to process?", default="all")
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
def run_extract(ticker: str = typer.Option(None, "--ticker", "-t")):
    """Extract statements and metrics from parsed data."""
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

    parsed_dir = Path(settings.active_workspace_path) / "2_parsed_data"
    parsed_files = (
        [
            p
            for p in parsed_dir.iterdir()
            if p.is_file()
            and p.suffix.lower() == ".md"
            and p.name.lower() != "readme.md"
            and not p.name.startswith(".")
            and p.name != "parsed_data.csv"
        ]
        if parsed_dir.exists()
        else []
    )

    if not parsed_files:
        formatting.speak(
            "No parsed files found to extract in our workspace directory, my good sir!"
        )
        return

    try:
        extractor = Extractor()
        extracted_registry = extractor.load_extracted_registry()
    except Exception as e:
        formatting.print_error(f"Failed to load registry: {str(e)}")
        raise typer.Exit(1)

    new_files = [p for p in parsed_files if p.name not in extracted_registry]
    extracted_files = [p for p in parsed_files if p.name in extracted_registry]

    new_files.sort(key=lambda p: p.name, reverse=True)
    extracted_files.sort(key=lambda p: p.name, reverse=True)

    ordered_files = []
    for p in new_files:
        ordered_files.append((p, False))
    for p in extracted_files:
        ordered_files.append((p, True))

    num_total = len(parsed_files)
    num_new = len(new_files)
    formatting.speak(
        f"Splendid! I found {num_total} parsed file(s) ready for extraction, of which {num_new} are new."
    )

    def get_letter_label(index: int) -> str:
        label = ""
        while index >= 0:
            label = chr(ord("a") + (index % 26)) + label
            index = (index // 26) - 1
        return label

    label_to_file = {}
    for i, (p_file, is_extracted) in enumerate(ordered_files):
        label = get_letter_label(i)
        label_to_file[label] = p_file
        suffix = " (already extracted)" if is_extracted else ""
        formatting.console.print(f"  {label}) {p_file.name}{suffix}")
    formatting.console.print()

    response = typer.prompt("How many files would you like to process?", default="all")
    response_clean = response.strip().lower()

    if response_clean in label_to_file:
        chosen_file = label_to_file[response_clean]
        formatting.print_info(
            f"Starting extraction stage for specifically selected file: {chosen_file.name}..."
        )
        try:
            extractor.run_extraction(files_to_process=[chosen_file])
            formatting.print_success(
                "Successfully extracted financial data and calculated metrics."
            )
        except Exception as e:
            formatting.print_error(f"Extraction failed: {str(e)}")
            raise typer.Exit(1)
    elif response_clean == "all":
        formatting.print_info("Starting extraction stage...")
        try:
            extractor.run_extraction(limit=None)
            formatting.print_success(
                "Successfully extracted financial data and calculated metrics."
            )
        except Exception as e:
            formatting.print_error(f"Extraction failed: {str(e)}")
            raise typer.Exit(1)
    elif response_clean.isdigit():
        limit = int(response_clean)
        formatting.print_info("Starting extraction stage...")
        try:
            extractor.run_extraction(limit=limit)
            formatting.print_success(
                "Successfully extracted financial data and calculated metrics."
            )
        except Exception as e:
            formatting.print_error(f"Extraction failed: {str(e)}")
            raise typer.Exit(1)
    else:
        formatting.print_warning(
            "Invalid input entered. Defaulting to processing all new files."
        )
        formatting.print_info("Starting extraction stage...")
        try:
            extractor.run_extraction(limit=None)
            formatting.print_success(
                "Successfully extracted financial data and calculated metrics."
            )
        except Exception as e:
            formatting.print_error(f"Extraction failed: {str(e)}")
            raise typer.Exit(1)


@run_app.command("analyze")
def run_analyze(
    ticker: str = typer.Option(None, "--ticker", "-t"),
    limit: int = typer.Option(
        None, "--limit", "-l", help="Limit the number of files to process"
    ),
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

    if not settings.active_workspace_path:
        formatting.print_error(
            "No active workspace is selected. Use 'fa use <ticker>' first."
        )
        raise typer.Exit(1)

    extracted_dir = Path(settings.active_workspace_path) / "4_extracted_data"
    extracted_csv = extracted_dir / "extracted_data.csv"
    extracted_files_count = 0
    if extracted_csv.exists():
        try:
            with open(extracted_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                extracted_files_count = sum(
                    1 for row in reader if row.get("source_file")
                )
        except Exception:
            pass

    if extracted_files_count == 0:
        formatting.speak(
            "No extracted files found to synthesize in our workspace directory, my good sir!"
        )
        return

    formatting.speak(
        f"Let us synthesize the longitudinal financial trends! I found {extracted_files_count} extracted file(s) ready for analysis."
    )

    formatting.print_info("Starting historical trend synthesis stage...")
    try:
        from src.pipeline.analyzer import Analyzer

        analyzer = Analyzer()
        analyzer.run_analysis(limit=limit)
        formatting.print_success(
            "Successfully synthesized all longitudinal financial trends and views."
        )
    except Exception as e:
        formatting.print_error(f"Trend synthesis failed: {str(e)}")
        raise typer.Exit(1)


@run_app.command("model")
def run_model(ticker: str = typer.Option(None, "--ticker", "-t")):
    """Propose assumptions and construct valuation models."""
    try:
        settings = load_config()
    except Exception as e:
        formatting.print_error(f"Configuration error: {str(e)}")
        raise typer.Exit(1)

    if ticker:
        use_cmd.main_use(ticker)
        settings = load_config()

    formatting.speak(
        "Time to construct our DCF valuation model and establish assumptions!"
    )
    formatting.print_info("Starting financial modeling stage...")
    try:
        modeler = Modeler()
        modeler.run_modeling(settings.active_ticker)
        formatting.print_success("Successfully generated valuation models.")
    except Exception as e:
        formatting.print_error(f"Modeling failed: {str(e)}")
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
