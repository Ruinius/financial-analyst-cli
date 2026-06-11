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
            self.headers = {
                "Content-Length": "100",
                "Content-Type": "application/json",
                "Origin": "http://localhost:3000",
            }
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


def test_save_scenario_csrf_protection(monkeypatch, tmp_path):
    """
    Test CSRF protections in /api/save-scenario (Content-Type and Origin validation)
    """
    from src.core.config import Settings

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

    class MockRequestFile:
        def read(self, length):
            return b'{"ticker": "AAPL"}'

    class MockHandler(DCFViewerHandler):
        def __init__(
            self, content_type="application/json", origin="http://localhost:3000"
        ):
            self.path = "/api/save-scenario"
            self.headers = {"Content-Length": "18"}
            if content_type is not None:
                self.headers["Content-Type"] = content_type
            if origin is not None:
                self.headers["Origin"] = origin
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

    # 1. Invalid Content-Type
    handler = MockHandler(content_type="text/plain", origin="http://localhost:3000")
    handler.do_POST()
    assert ("code", 400) in handler.responses
    assert any(
        "Invalid Content-Type" in str(r[1])
        for r in handler.responses
        if r[0] == "write"
    )

    # 2. Forbidden Origin
    handler = MockHandler(
        content_type="application/json", origin="http://malicious.com"
    )
    handler.do_POST()
    assert ("code", 403) in handler.responses
    assert any(
        "Forbidden Origin" in str(r[1]) for r in handler.responses if r[0] == "write"
    )

    # 3. Valid local IP Origin
    handler = MockHandler(
        content_type="application/json", origin="http://127.0.0.1:8080"
    )
    # Make directory so it doesn't fail on save
    (tmp_path / "8_historical_model_json").mkdir(parents=True, exist_ok=True)
    handler.do_POST()
    assert ("code", 200) in handler.responses


def test_viewer_options_handler():
    """
    Test the do_OPTIONS method handling of CORS/Origin checks.
    """

    class MockHandler(DCFViewerHandler):
        def __init__(self, origin=None):
            self.headers = {}
            if origin is not None:
                self.headers["Origin"] = origin
            self.responses = []

        def send_response(self, code, message=None):
            self.responses.append(("code", code))

        def send_header(self, keyword, value):
            self.responses.append(("header", keyword, value))

        def end_headers(self):
            pass

    # 1. Valid local origin
    handler = MockHandler(origin="http://localhost:3000")
    handler.do_OPTIONS()
    assert ("code", 200) in handler.responses
    assert (
        "header",
        "Access-Control-Allow-Origin",
        "http://localhost:3000",
    ) in handler.responses

    # 2. Valid local IP origin
    handler = MockHandler(origin="http://127.0.0.1:8080")
    handler.do_OPTIONS()
    assert ("code", 200) in handler.responses
    assert (
        "header",
        "Access-Control-Allow-Origin",
        "http://127.0.0.1:8080",
    ) in handler.responses

    # 3. Invalid malicious origin
    handler = MockHandler(origin="http://evil-attacker.com")
    handler.do_OPTIONS()
    assert ("code", 403) in handler.responses

    # 4. No origin header
    handler = MockHandler(origin=None)
    handler.do_OPTIONS()
    assert ("code", 403) in handler.responses
