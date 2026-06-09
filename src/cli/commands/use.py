from pathlib import Path
import typer

from src.core.config import load_config, save_config
from src.utils import formatting

app = typer.Typer()

FOLDER_DEFINITIONS = {
    "1_ingest_data": "Raw downloaded filings (PDFs, HTML filings, earnings announcements, transcripts, press releases).",
    "2_parsed_data": "Cleaned, alignment-preserved markdown files parsed from raw sources, divided into 5k char chunks with chunk_id=0 index table prepended.",
    "3_archived_data": "Archived exact raw documents after conversion to preserve history.",
    "4_extracted_data": "Chunk-by-chunk extraction summaries, balance sheets, income statements, and audit linkage records.",
    "5_historical_analysis": "Longitudinal quarterly and annual metrics, synthesized analyst views, and qualitative trend reports.",
    "6_company_context": "Self-healing company contexts, fiscal calendars, statement formats, and custom classification guidelines.",
    "7_financial_model": "Readable markdown outputs detailing DCF projections and intrinsic value calculations.",
    "8_historical_model_json": "Structured JSON representations of model projections used by the interactive web viewer.",
}


def initialize_workspace(workspace_dir: Path, ticker: str) -> None:
    """Initialize the 8 subdirectories with descriptive README.md files."""
    try:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        for folder, desc in FOLDER_DEFINITIONS.items():
            folder_path = workspace_dir / folder
            folder_path.mkdir(exist_ok=True)

            # Write descriptive README.md
            readme_path = folder_path / "README.md"
            if not readme_path.exists():
                readme_content = (
                    f"# Workspace Folder: {folder}\n\n"
                    f"**Purpose**: {desc}\n\n"
                    f"**Company Ticker**: {ticker}\n"
                )
                readme_path.write_text(readme_content, encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"Failed to initialize workspace folders: {str(e)}")


@app.command()
def main_use(
    ticker: str = typer.Argument(..., help="Company ticker symbol (e.g. AAPL)"),
):
    """Switch the current active workspace to the folder for the specified company ticker."""
    try:
        ticker = ticker.strip().upper()
        if not ticker:
            raise ValueError("Ticker symbol cannot be empty.")

        settings = load_config()

        # Calculate active path
        target_path = Path(settings.base_workspace_dir) / ticker

        # Initialize workspace folders
        initialize_workspace(target_path, ticker)

        # Update settings
        settings.active_ticker = ticker
        settings.active_workspace_path = str(target_path)
        save_config(settings)

        formatting.speak(
            f"Indubitably! I have switched our workspace to [bold]{ticker}[/bold].\n"
            f"All 8 folders are initialized at: {target_path}",
            title="Sir Pennyworth",
        )
    except Exception as e:
        formatting.print_error(f"Failed to switch workspace: {str(e)}")
