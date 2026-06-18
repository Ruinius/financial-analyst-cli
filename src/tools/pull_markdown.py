from pathlib import Path


def pull_markdown_file(workspace: Path | str, file_name: str) -> str:
    """Safe lookup of markdown files within workspace directories."""
    workspace_path = Path(workspace)
    clean_name = Path(file_name).name

    # 1. Check in 4_extracted_data
    p1 = workspace_path / "4_extracted_data" / clean_name
    if p1.exists():
        return p1.read_text(encoding="utf-8")

    # 2. Check in 5_historical_analysis
    p2 = workspace_path / "5_historical_analysis" / clean_name
    if p2.exists():
        return p2.read_text(encoding="utf-8")

    # 3. Check in workspace root
    p3 = workspace_path / clean_name
    if p3.exists():
        return p3.read_text(encoding="utf-8")

    return f"Error: File '{file_name}' not found in workspace."
