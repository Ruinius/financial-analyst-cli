from src.viewer.server import DCFViewerHandler


def test_server_import():
    assert DCFViewerHandler is not None


def test_save_scenario_ticker_sanitization(monkeypatch, tmp_path):
    """
    Test that ticker path traversal characters are sanitized properly
    in /api/save-scenario
    """
    from src.core.config import Settings

    # Mock settings
    monkeypatch.setattr(
        "src.viewer.server.load_config",
        lambda: Settings(
            full_name="Test User",
            email="test@example.com",
            project_name="test-project",
            primary_llm_api_key="test-key",
            base_workspace_dir=str(tmp_path),
            active_workspace_path=str(tmp_path),
        ),
    )

    # Create the model directory so glob doesn't fail
    models_dir = tmp_path / "8_historical_model_json"
    models_dir.mkdir(parents=True)

    import json

    class MockRequestFile:
        def read(self, length):
            return json.dumps(
                {"ticker": "../../../etc/passwd", "test": "data"}
            ).encode()

    class MockHandler(DCFViewerHandler):
        def __init__(self):
            self.path = "/api/save-scenario"
            self.headers = {"Content-Length": "100"}
            self.rfile = MockRequestFile()
            self.responses = []

        def send_response(self, code, message=None):
            self.responses.append(("code", code))

        def send_header(self, keyword, value):
            self.responses.append(("header", keyword, value))

        def end_headers(self):
            pass

        class WFile:
            def __init__(self, parent):
                self.parent = parent

            def write(self, data):
                self.parent.responses.append(("write", data))

        @property
        def wfile(self):
            if not hasattr(self, "_wfile"):
                self._wfile = self.WFile(self)
            return self._wfile

    handler = MockHandler()

    # Call the actual POST handler
    handler.do_POST()

    # Check that the 200 response was sent
    assert ("code", 200) in handler.responses

    # Check what file was created
    files = list(models_dir.glob("*.json"))
    assert len(files) == 1

    # The filename should have replaced the ../../ with nothing, leaving etcpasswd
    assert "etcpasswd" in files[0].name
    assert ".." not in files[0].name
    assert "/" not in files[0].name
