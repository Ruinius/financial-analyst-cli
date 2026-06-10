from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

# Theme Color Constants
COLOR_CHAR = "#FFB6C1"  # Pink/Rose for Sir Pennyworth
COLOR_SUCCESS = "green"  # Green for capital creation / success
COLOR_ERROR = "red"  # Red for errors / capital destruction
COLOR_WARN = "gold1"  # Yellow/Gold for warnings / inputs


PENNYWORTH_ASCII = """
    ◢◣       ◢◣
   ┌┴┴───────┴┴┐
   │  $     $  │
   │    (oo)   │
   │   ╘═══╛   │
   └───────────┘
"""


def get_sir_pennyworth_art(color: str = COLOR_CHAR) -> Text:
    """Returns the Sir Pennyworth ASCII art as a Rich Text object."""
    return Text(PENNYWORTH_ASCII.strip("\n"), style=color)


def speak(message: str, title: str = "Sir Pennyworth", show_art: bool = True) -> None:
    """Make Sir Pennyworth speak a message in a beautiful Pink/Rose panel."""
    if show_art:
        art = get_sir_pennyworth_art()
        console.print(art)

    panel = Panel(
        Text(message, style="italic"),
        title=f"[bold]{title}[/bold]",
        border_style=COLOR_CHAR,
        expand=False,
    )
    console.print(panel)
    console.print()


def print_success(message: str) -> None:
    """Print a success message with green styling."""
    console.print(f"[bold {COLOR_SUCCESS}]✓ Success:[/bold {COLOR_SUCCESS}] {message}")


def print_error(message: str) -> None:
    """Print an error message with red styling."""
    console.print(f"[bold {COLOR_ERROR}]✗ Error:[/bold {COLOR_ERROR}] {message}")


def print_warning(message: str) -> None:
    """Print a warning message with gold styling."""
    console.print(f"[bold {COLOR_WARN}]⚠ Warning:[/bold {COLOR_WARN}] {message}")


def print_info(message: str) -> None:
    """Print an info message with cyan styling."""
    console.print(f"[bold cyan]ℹ Info:[/bold cyan] {message}")
