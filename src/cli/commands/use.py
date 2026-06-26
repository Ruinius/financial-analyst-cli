from pathlib import Path
import typer

from src.core.config import load_config, save_config
from src.utils import formatting

app = typer.Typer()

FOLDER_DEFINITIONS = {
    "1_ingest_data": "Raw downloaded filings (PDFs, HTML filings, earnings announcements, transcripts, press releases).",
    "2_parsed_data": "Cleaned, alignment-preserved markdown files parsed from raw sources, divided into 5k char chunks with chunk_id=0 index table prepended.",
    "3_archived_data": "Archived exact raw documents after conversion to preserve history.",
    "9_scenario_model_json": "Structured JSON representations of model projections used by the interactive web viewer.",
}


def initialize_workspace(workspace_dir: Path, ticker: str) -> None:
    """Initialize the 4 subdirectories with descriptive README.md files and default wiki/learning files."""
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

        # Initialize default Wiki and Learning files in the ticker root folder
        wiki_path = workspace_dir / f"{ticker}_wiki.md"
        if not wiki_path.exists():
            wiki_content = (
                f"# Wiki: {ticker}\n\n"
                "## Bull Perspective\n- No bull perspective compiled yet.\n\n"
                "## Bear Perspective\n- No bear perspective compiled yet.\n\n"
            )
            wiki_path.write_text(wiki_content, encoding="utf-8")

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

        if ticker in {
            "USE",
            "RUN",
            "CHAT",
            "QUERY",
            "VIEWER",
            "CONFIG",
            "EDGAR",
            "INGEST",
            "EXTRACT",
            "ANALYZE",
            "MODEL",
            "INIT",
            "SHOW",
            "SET",
            "HELP",
        }:
            formatting.print_warning(
                f"'{ticker}' is a command or subcommand name, not a typical company ticker."
            )
            if not typer.confirm(
                f"Are you sure you want to switch workspace to '{ticker}'?"
            ):
                formatting.print_info("Workspace switch cancelled.")
                raise typer.Exit(0)

        settings = load_config()

        # Calculate active path
        target_path = Path(settings.base_workspace_dir) / ticker

        # Initialize workspace folders
        if not target_path.exists():
            formatting.print_info(
                f"Workspace for {ticker} not found. Creating it now..."
            )
            initialize_workspace(target_path, ticker)
            msg = f"Indubitably! I have created and switched our workspace to {ticker}.\nAll 4 folders are initialized at: {target_path}"
        else:
            # Check and delete deprecated directories if they exist
            import shutil

            deprecated_folders = [
                "4_extracted_data",
                "5_historical_analysis",
                "6_financial_model",
                "7_historical_model_json",
            ]
            for folder in deprecated_folders:
                folder_path = target_path / folder
                if folder_path.exists():
                    formatting.print_info(
                        f"Removing deprecated directory: {folder_path}"
                    )
                    shutil.rmtree(folder_path, ignore_errors=True)

            msg = f"Indubitably! I have switched our workspace to {ticker}.\nActive workspace path: {target_path}"

        # Update settings
        settings.active_ticker = ticker
        settings.active_workspace_path = str(target_path)
        save_config(settings)

        formatting.speak(
            msg,
            title="Sir Pennyworth",
        )
    except Exception as e:
        formatting.print_error(f"Failed to switch workspace: {str(e)}")
