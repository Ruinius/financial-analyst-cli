"""
Lightweight static file server for financial-analyst-skills with scenario save endpoint.

Usage:
    python tools/serve.py [--port 3000]

Serves:
    GET /                          → tools/financial_model_viewer.html
    GET /output_data/...           → static files from output_data/
    POST /api/save-scenario        → saves scenario to TICKER_scenarios.json
"""

import http.server
import json
import os
import sys
import urllib.parse
from pathlib import Path

PORT = 3000
ROOT = Path(__file__).resolve().parent.parent  # financial-analyst-skills root


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Root → serve the viewer
        if path == "/" or path == "":
            self.path = "/scripts/financial_model_viewer.html" + ("?" + parsed.query if parsed.query else "")
            return super().do_GET()

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/save-scenario":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body)
                ticker = data.get("ticker", "UNKNOWN")
                scenario = data.get("scenario", {})

                scenarios_path = ROOT / "output_data" / ticker / f"{ticker}_scenarios.json"
                scenarios_path.parent.mkdir(parents=True, exist_ok=True)

                # Load existing scenarios or create new list
                existing = []
                if scenarios_path.exists():
                    with open(scenarios_path, "r", encoding="utf-8") as f:
                        existing = json.load(f)

                existing.append(scenario)

                with open(scenarios_path, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "count": len(existing)}).encode())

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format, *args):
        # Quieter logging
        if "/api/" in str(args[0]) if args else False:
            super().log_message(format, *args)


def main():
    port = PORT
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    print(f"Financial Analyst Skills Viewer | http://127.0.0.1:{port}/?ticker=ADBE")
    print(f"Serving from: {ROOT}")
    print(f"Press Ctrl+C to stop\n")

    with http.server.HTTPServer(("127.0.0.1", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
