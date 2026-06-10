import typer
from src.viewer.server import run_server
from src.utils import formatting


app = typer.Typer()


@app.command("viewer")
def main_viewer(
    port: int = typer.Option(3000, "--port", "-p", help="Server port"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Server host"),
):
    """Launch local HTML DCF viewer server."""
    formatting.speak(
        f"Launching the interactive DCF visualizer at http://{host}:{port}/, my good sir!"
    )
    run_server(port, host)
