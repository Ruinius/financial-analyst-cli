from pathlib import Path


def access_resources(resource_name: str) -> str:
    """
    Safely look up static markdown resources (such as accounting glossaries/dictionaries in the codebase).
    Arguments:
      resource_name: The name of the dictionary to access. Options: 'income_statement', 'balance_sheet'.
    """
    dict_path = Path("src/resources/dictionary") / f"{resource_name}.md"
    if dict_path.exists():
        try:
            return dict_path.read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading dictionary {resource_name}: {e}"
    return f"Error: Dictionary '{resource_name}' not found."
