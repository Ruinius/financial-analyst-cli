import sys
import typer

from src.core.config import config_exists
from src.cli.commands import config as config_cmd
from src.cli.commands import use as use_cmd
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


query_app = typer.Typer(help="Query parsed metrics and evaluations.")
app.add_typer(query_app, name="query")


@query_app.command("summary")
def query_summary(ticker: str):
    """Display historical metric tables."""
    formatting.print_warning(
        "The 'query summary' command is currently under development (Phase 6)."
    )


@query_app.command("assessment")
def query_assessment(ticker: str):
    """Display qualitative moat and margin assessments."""
    formatting.print_warning(
        "The 'query assessment' command is currently under development (Phase 6)."
    )


@query_app.command("valuation")
def query_valuation(ticker: str):
    """Display WACC metrics and intrinsic value models."""
    formatting.print_warning(
        "The 'query valuation' command is currently under development (Phase 6)."
    )


@query_app.command("trace")
def query_trace(ticker: str, metric: str, period: str):
    """Retrieve full audit trail/provenance for a metric."""
    formatting.print_warning(
        "The 'query trace' command is currently under development (Phase 6)."
    )


@app.command("chat")
def chat(ticker: str):
    """Open interactive REPL/chat session with Sir Pennyworth."""
    formatting.print_warning(
        "The 'chat' command is currently under development (Phase 6)."
    )


@app.command("viewer")
def viewer(
    port: int = typer.Option(3000, "--port", "-p", help="Server port"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Server host"),
):
    """Launch local HTML DCF viewer server."""
    formatting.print_warning(
        "The 'viewer' command is currently under development (Phase 6)."
    )


@app.callback()
def main_callback(ctx: typer.Context):
    """Global callback to verify configuration existence."""
    # Check if we are running 'config init' or requesting help to avoid blocking
    args = sys.argv[1:]

    # Allow config init or help options without configuration
    if "config" in args and "init" in args:
        return
    if "--help" in args or "-h" in args:
        return

    # Auto-initialize if config file does not exist
    if not config_exists():
        try:
            config_cmd.initialize_config_flow()
        except typer.Abort:
            formatting.print_error("Configuration flow was aborted.")
            raise typer.Exit(1)
        except Exception as e:
            formatting.print_error(f"Failed to auto-initialize settings: {str(e)}")
            raise typer.Exit(1)


def main():
    app()


if __name__ == "__main__":
    main()
