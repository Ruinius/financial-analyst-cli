import http.server
import json
import logging
import re
import urllib.parse
from pathlib import Path
from src.core.config import load_config
from src.utils import formatting

ROOT = Path(__file__).resolve().parent


class DCFViewerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def get_models_dir(self):
        settings = load_config()
        if not settings.active_workspace_path:
            raise RuntimeError("No active workspace. Use `fa use <ticker>` first.")
        return Path(settings.active_workspace_path) / "8_historical_model_json"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/models":
            try:
                models_dir = self.get_models_dir()
                if models_dir.exists():
                    files = [f.name for f in models_dir.glob("*.json")]
                    # Sort files so latest is first
                    files.sort(reverse=True)
                else:
                    files = []

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(files).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                logging.error(f"Viewer Server Error: {e}")
                self.wfile.write(
                    json.dumps({"error": "An internal error occurred."}).encode()
                )
            return

        elif path.startswith("/api/models/"):
            filename = path.replace("/api/models/", "")
            try:
                models_dir = self.get_models_dir()

                # Prevent path traversal vulnerabilities
                filename = urllib.parse.unquote(filename)
                file_path = (models_dir / filename).resolve()

                # Ensure the resolved path is within the models_dir
                if not file_path.is_relative_to(models_dir.resolve()):
                    self.send_response(403)
                    self.end_headers()
                    return

                if file_path.exists() and file_path.is_file():
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                logging.error(f"Viewer Server Error: {e}")
                self.wfile.write(
                    json.dumps({"error": "An internal error occurred."}).encode()
                )
            return

        if path == "/" or path == "":
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/save-scenario":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body)
                ticker_raw = str(data.get("ticker", "UNKNOWN"))
                ticker = re.sub(r"[^a-zA-Z0-9_-]", "", ticker_raw)
                if not ticker:
                    ticker = "UNKNOWN"

                models_dir = self.get_models_dir()
                models_dir.mkdir(parents=True, exist_ok=True)

                import datetime

                today = datetime.date.today().strftime("%Y%m%d")

                # Determine next version number
                existing_files = list(models_dir.glob(f"{today}_{ticker}_*.json"))

                max_version = 0
                for f in existing_files:
                    try:
                        # Extract the integer after the last underscore
                        version_str = f.stem.split("_")[-1]
                        max_version = max(max_version, int(version_str))
                    except ValueError:
                        pass

                new_version = max_version + 1
                new_filename = f"{today}_{ticker}_{new_version}.json"
                out_path = models_dir / new_filename

                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"ok": True, "filename": new_filename}).encode()
                )
                formatting.print_success(f"Saved custom scenario to {new_filename}")

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                logging.error(f"Viewer Server Error: {e}")
                self.wfile.write(
                    json.dumps({"error": "An internal error occurred."}).encode()
                )
            return

        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        # Mute simple HTTP logs to prevent clutter
        pass


def run_server(port: int = 3000, host: str = "127.0.0.1"):
    server_address = (host, port)
    httpd = http.server.HTTPServer(server_address, DCFViewerHandler)
    formatting.print_success(f"Starting DCF Viewer server at http://{host}:{port}")
    formatting.print_info("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        formatting.print_info("\nShutting down server...")
        httpd.server_close()
