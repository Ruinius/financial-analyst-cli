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
        f"Ah, let us fetch the filings for [bold]{active_ticker}[/bold] from the SEC EDGAR archives, my dear fellow!"
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
def run_ingest(ticker: str = typer.Option(None, "--ticker", "-t")):
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
        f"Splendid! I found [bold]{len(raw_files)}[/bold] raw file(s) ready for ingestion."
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

    formatting.speak(
        f"Splendid! I found [bold]{len(parsed_files)}[/bold] parsed file(s) ready for extraction."
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

    formatting.print_info("Starting extraction stage...")
    try:
        extractor = Extractor()
        extractor.run_extraction(limit=limit)
        formatting.print_success(
            "Successfully extracted financial data and calculated metrics."
        )
    except Exception as e:
        formatting.print_error(f"Extraction failed: {str(e)}")
        raise typer.Exit(1)


@run_app.command("historical")
def run_historical(ticker: str = typer.Option(None, "--ticker", "-t")):
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
        f"Let us synthesize the longitudinal financial trends! I found [bold]{extracted_files_count}[/bold] extracted file(s) ready for analysis."
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

    formatting.print_info("Starting historical trend synthesis stage...")
    try:
        from src.pipeline.analyzer import Analyzer

        analyzer = Analyzer()
        analyzer.run_analysis(limit=limit)
        formatting.print_success(
            "Successfully synthesized all longitudinal financial trends and views."
        )
    except Exception as e:
        formatting.print_error(f"Historical trend synthesis failed: {str(e)}")
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
        formatting.speak(
            "Greetings! I am Sir Pennyworth, your financial concierge. Ready to begin our financial trufflings?"
        )

    if not config_exists() and not is_help and not is_config_init:
        try:
            config_cmd.initialize_config_flow()
        except typer.Abort:
            formatting.print_error("Configuration flow was aborted.")
            sys.exit(1)
        except Exception as e:
            formatting.print_error(f"Failed to auto-initialize settings: {str(e)}")
            sys.exit(1)

    app()


if __name__ == "__main__":
    main()
