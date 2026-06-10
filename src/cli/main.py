import sys
import typer

from src.core.config import config_exists
from src.cli.commands import config as config_cmd
from src.cli.commands import use as use_cmd
from src.cli.commands import query as query_cmd
from src.cli.commands import chat as chat_cmd
from src.cli.commands import viewer as viewer_cmd
from src.utils import formatting
from src.services.edgar_client import EdgarClient
from src.pipeline.ingester import Ingester
from src.pipeline.extractor import Extractor
from src.pipeline.modeler import Modeler

app = typer.Typer(
    name="fa",
    help="Sir Pennyworth's Financial Analyst CLI Assistant",
    no_args_is_help=True,
)

# Register config commands
app.add_typer(config_cmd.app, name="config")

# Register use command
# Note: Use `app.command("use")(use_cmd.main_use)` to register it as 'use'
app.command("use")(use_cmd.main_use)


# ==========================================
# Future Phases Command Placeholders
# ==========================================

run_app = typer.Typer(help="Execute data pipeline stages.")
app.add_typer(run_app, name="run")


@run_app.command("edgar")
def run_edgar(
    ticker: str, years: int = typer.Option(5, "--years", "-y", help="Years to download")
):
    """Download filings from SEC EDGAR."""
    formatting.print_info(
        f"Starting filings download for {ticker} (limit {years} years)..."
    )
    try:
        client = EdgarClient()
        paths = client.download_filings(ticker, years)
        if paths:
            formatting.print_success(
                f"Successfully downloaded {len(paths)} filings for {ticker} to 1_ingest_data/."
            )
        else:
            formatting.print_warning(
                f"No filings found or downloaded for {ticker} in the last {years} years."
            )
    except Exception as e:
        formatting.print_error(f"Failed to download filings: {str(e)}")
        raise typer.Exit(1)


@run_app.command("ingest")
def run_ingest(ticker: str = typer.Option(None, "--ticker", "-t")):
    """Parse and ingest raw files."""
    formatting.print_info("Starting ingestion stage...")
    try:
        ingester = Ingester()
        # Note: workspace context handles ticker, but we can log ticker filtering if passed
        ingester.run_ingestion()
        formatting.print_success(
            "Successfully processed all raw files in 1_ingest_data/."
        )
    except Exception as e:
        formatting.print_error(f"Ingestion failed: {str(e)}")
        raise typer.Exit(1)


@run_app.command("extract")
def run_extract(ticker: str = typer.Option(None, "--ticker", "-t")):
    """Extract statements and metrics from parsed data."""
    formatting.print_info("Starting extraction stage...")
    try:
        if ticker:
            # Switch ticker if explicitly requested
            use_cmd.main_use(ticker)

        extractor = Extractor()
        extractor.run_extraction()
        formatting.print_success(
            "Successfully extracted financial data and calculated metrics."
        )
    except Exception as e:
        formatting.print_error(f"Extraction failed: {str(e)}")
        raise typer.Exit(1)


@run_app.command("historical")
def run_historical(ticker: str = typer.Option(None, "--ticker", "-t")):
    """Synthesize longitudinal trends and analyst views."""
    formatting.print_info("Starting historical trend synthesis stage...")
    try:
        if ticker:
            use_cmd.main_use(ticker)

        from src.pipeline.analyzer import Analyzer

        analyzer = Analyzer()
        analyzer.run_analysis()
        formatting.print_success(
            "Successfully synthesized all longitudinal financial trends and views."
        )
    except Exception as e:
        formatting.print_error(f"Historical trend synthesis failed: {str(e)}")
        raise typer.Exit(1)


@run_app.command("model")
def run_model(ticker: str = typer.Option(None, "--ticker", "-t")):
    """Propose assumptions and construct valuation models."""
    formatting.print_info("Starting financial modeling stage...")
    try:
        modeler = Modeler()
        modeler.run_modeling(ticker)
        formatting.print_success("Successfully generated valuation models.")
    except Exception as e:
        formatting.print_error(f"Modeling failed: {str(e)}")
        raise typer.Exit(1)


app.add_typer(query_cmd.app, name="query", help="Query parsed metrics and evaluations.")


app.command("chat")(chat_cmd.main_chat)


app.command("viewer")(viewer_cmd.main_viewer)


@app.callback()
def main_callback(ctx: typer.Context):
    """Global callback."""
    pass


def main():
    args = sys.argv[1:]

    # Allow config init or help options without configuration
    is_help = "--help" in args or "-h" in args
    is_config_init = "config" in args and "init" in args

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
