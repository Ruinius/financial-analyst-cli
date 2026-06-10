import typer
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown

from src.core.config import load_config
from src.utils import formatting

app = typer.Typer()
console = Console()


def read_markdown_file(filepath: Path) -> None:
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            console.print(Markdown(content))
    else:
        formatting.print_warning(f"File not found: {filepath}")


@app.command("summary")
def query_summary(ticker: str = typer.Argument(..., help="Company ticker symbol")):
    """Display historical metric tables."""
    settings = load_config()
    workspace = Path(settings.base_workspace_dir) / ticker

    annual_path = workspace / "5_historical_analysis" / "financials_annual.md"
    quarterly_path = workspace / "5_historical_analysis" / "financials_quarter.md"

    formatting.speak(
        f"Here is a summary of historical financial tables for [bold]{ticker}[/bold], my dear fellow:"
    )
    read_markdown_file(annual_path)
    read_markdown_file(quarterly_path)


@app.command("assessment")
def query_assessment(ticker: str = typer.Argument(..., help="Company ticker symbol")):
    """Display qualitative moat and margin assessments."""
    settings = load_config()
    workspace = Path(settings.base_workspace_dir) / ticker

    views_path = workspace / "5_historical_analysis" / "analyst_views.md"

    formatting.speak(
        f"Here is the qualitative moat and margin assessment report for [bold]{ticker}[/bold]:"
    )
    read_markdown_file(views_path)


@app.command("valuation")
def query_valuation(ticker: str = typer.Argument(..., help="Company ticker symbol")):
    """Display WACC metrics and intrinsic value models."""
    settings = load_config()
    workspace = Path(settings.base_workspace_dir) / ticker

    model_dir = workspace / "7_financial_model"

    if not model_dir.exists():
        formatting.print_warning(f"Model directory not found: {model_dir}")
        return

    models = list(model_dir.glob("*.md"))
    if not models:
        formatting.print_warning(f"No valuation models found in {model_dir}")
        return

    # Get the most recently created/modified model
    latest_model = max(models, key=lambda p: p.stat().st_mtime)

    formatting.speak(
        f"Behold the cost of capital and DCF intrinsic valuation models for [bold]{ticker}[/bold]:"
    )
    read_markdown_file(latest_model)


@app.command("trace")
def query_trace(
    ticker: str = typer.Argument(..., help="Company ticker symbol"),
    metric: str = typer.Argument(..., help="Metric name to trace (e.g., 'Revenue')"),
    period: str = typer.Argument(..., help="Period to trace (e.g., '2024')"),
):
    """Retrieve full audit trail/provenance for a metric."""
    settings = load_config()
    workspace = Path(settings.base_workspace_dir) / ticker
    extracted_dir = workspace / "4_extracted_data"

    if not extracted_dir.exists():
        formatting.print_warning(f"Extracted data directory not found: {extracted_dir}")
        return

    target_files = list(extracted_dir.glob(f"{period}*_extracted.md"))
    if not target_files:
        formatting.print_warning(
            f"No extracted data found for period {period} in {extracted_dir}"
        )
        return

    formatting.speak(
        f"Tracing the audit trail and provenance for [bold]'{metric}'[/bold] in [bold]{period}[/bold]:"
    )
    found = False

    for file_path in target_files:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if metric.lower() in line.lower() and "|" in line:
                # Found a potential match in a table
                found = True
                console.print(f"[bold green]File:[/bold green] {file_path.name}")
                # Print table header if possible (naive approach: find previous lines with |---|)
                start_idx = i
                while start_idx > 0 and "|" in lines[start_idx - 1]:
                    start_idx -= 1
                end_idx = i
                while end_idx < len(lines) - 1 and "|" in lines[end_idx + 1]:
                    end_idx += 1

                table_lines = "".join(lines[start_idx : end_idx + 1])
                console.print(Markdown(table_lines))
                console.print("-" * 40)

    if not found:
        formatting.print_warning(
            f"Metric '{metric}' not found in extraction files for {period}."
        )
