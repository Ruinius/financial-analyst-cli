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
    "6_financial_model": "Readable markdown outputs detailing DCF projections and intrinsic value calculations.",
    "7_historical_model_json": "Structured JSON representations of model projections used by the interactive web viewer.",
}


def initialize_workspace(workspace_dir: Path, ticker: str) -> None:
    """Initialize the 7 subdirectories with descriptive README.md files and default wiki/learning files."""
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
                "## Ingested Sources\n- None\n"
            )
            wiki_path.write_text(wiki_content, encoding="utf-8")

        extract_learning_path = workspace_dir / f"{ticker}_extract_learning.md"
        if not extract_learning_path.exists():
            extract_content = (
                f"# Ingestion & Extraction Learning: {ticker}\n\n"
                "## Fiscal Schedule Mappings\n"
                "- Q1: N/A\n"
                "- Q2: N/A\n"
                "- Q3: N/A\n"
                "- FY: N/A\n\n"
                "## Lessons to Better Ingest & Extract\n- None\n\n"
                "## balance_sheet\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## income_statement\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## diluted_shares\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## organic growth\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## ebita\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## tax\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## User Feedback\n"
                "<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->\n"
            )
            extract_learning_path.write_text(extract_content, encoding="utf-8")

        analyze_learning_path = workspace_dir / f"{ticker}_analyze_learning.md"
        if not analyze_learning_path.exists():
            analyze_content = (
                f"# Analysis Learning: {ticker}\n\n"
                "## Lessons to Better Analyze\n- None\n\n"
                "## User Feedback\n"
                "<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->\n"
            )
            analyze_learning_path.write_text(analyze_content, encoding="utf-8")

        model_learning_path = workspace_dir / f"{ticker}_model_learning.md"
        if not model_learning_path.exists():
            model_content = (
                f"# Modeling Learning: {ticker}\n\n"
                "## Lessons to Better Model\n- None\n\n"
                "## User Feedback\n"
                "<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->\n"
            )
            model_learning_path.write_text(model_content, encoding="utf-8")

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
        if not target_path.exists():
            formatting.print_info(
                f"Workspace for {ticker} not found. Creating it now..."
            )
            initialize_workspace(target_path, ticker)
            msg = f"Indubitably! I have created and switched our workspace to {ticker}.\nAll 7 folders are initialized at: {target_path}"
        else:
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
