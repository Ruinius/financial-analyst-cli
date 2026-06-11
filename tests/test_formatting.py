from rich.panel import Panel
from rich.text import Text

from src.utils.formatting import (
    COLOR_CHAR,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_WARN,
    PENNYWORTH_ASCII,
    get_sir_pennyworth_art,
    print_error,
    print_info,
    print_success,
    print_warning,
    speak,
)


def test_get_sir_pennyworth_art_default_color():
    art = get_sir_pennyworth_art()
    assert isinstance(art, Text)
    assert str(art) == PENNYWORTH_ASCII.strip("\n")
    assert art.style == COLOR_CHAR


def test_get_sir_pennyworth_art_custom_color():
    custom_color = "blue"
    art = get_sir_pennyworth_art(color=custom_color)
    assert isinstance(art, Text)
    assert str(art) == PENNYWORTH_ASCII.strip("\n")
    assert art.style == custom_color


def test_speak(monkeypatch):
    prints = []

    def mock_print(arg=None):
        prints.append(arg)

    monkeypatch.setattr("src.utils.formatting.console.print", mock_print)

    speak("Hello World", title="Test Title")

    assert len(prints) == 3
    # 1st print is the art
    assert isinstance(prints[0], Text)
    assert str(prints[0]) == PENNYWORTH_ASCII.strip("\n")
    # 2nd print is the panel
    assert isinstance(prints[1], Panel)
    assert prints[1].title == "[bold]Test Title[/bold]"
    assert prints[1].border_style == COLOR_CHAR
    assert str(prints[1].renderable) == "Hello World"
    assert prints[1].renderable.style == "italic"
    # 3rd print is empty newline
    assert prints[2] is None


def test_print_success(monkeypatch):
    prints = []

    def mock_print(arg):
        prints.append(arg)

    monkeypatch.setattr("src.utils.formatting.console.print", mock_print)

    print_success("Operation completed")

    assert len(prints) == 1
    assert (
        prints[0]
        == f"[bold {COLOR_SUCCESS}]✓ Success:[/bold {COLOR_SUCCESS}] Operation completed"
    )


def test_print_error(monkeypatch):
    prints = []

    def mock_print(arg):
        prints.append(arg)

    monkeypatch.setattr("src.utils.formatting.console.print", mock_print)

    print_error("Failed task")

    assert len(prints) == 1
    assert prints[0] == f"[bold {COLOR_ERROR}]✗ Error:[/bold {COLOR_ERROR}] Failed task"


def test_print_warning(monkeypatch):
    prints = []

    def mock_print(arg):
        prints.append(arg)

    monkeypatch.setattr("src.utils.formatting.console.print", mock_print)

    print_warning("Be careful")

    assert len(prints) == 1
    assert prints[0] == f"[bold {COLOR_WARN}]⚠ Warning:[/bold {COLOR_WARN}] Be careful"


def test_print_info(monkeypatch):
    prints = []

    def mock_print(arg):
        prints.append(arg)

    monkeypatch.setattr("src.utils.formatting.console.print", mock_print)

    print_info("Some info")

    assert len(prints) == 1
    assert prints[0] == "[bold cyan]ℹ Info:[/bold cyan] Some info"
