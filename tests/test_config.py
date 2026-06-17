import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from typer.testing import CliRunner

from src.core.config import Settings, save_config, config_exists, load_config, mask_key
from src.cli.commands.use import initialize_workspace
from src.cli.main import app

runner = CliRunner()


@pytest.fixture
def temp_config(monkeypatch):
    """Fixture to isolate configuration file tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_config_path = Path(tmpdir) / ".env"
        monkeypatch.setattr("src.core.config.CONFIG_FILE_PATH", fake_config_path)
        yield fake_config_path


def test_settings_model():
    settings = Settings(
        full_name="Alice",
        email="alice@example.com",
        project_name="TestProj",
        primary_llm_api_key="sk-abcdefg12345",
        base_workspace_dir="/tmp/workspace",
    )
    assert settings.full_name == "Alice"
    assert settings.email == "alice@example.com"
    assert settings.text_model_id == "google/gemma-4-31b-it:free"
    assert settings.gemini_model == "gemini-2.5-flash"
    assert settings.openrouter_model == "google/gemma-4-31b-it:free"
    assert settings.deepseek_model == "deepseek-v4-flash"


def test_save_load_config(temp_config):
    assert not config_exists()
    settings = Settings(
        full_name="Alice",
        email="alice@example.com",
        project_name="TestProj",
        primary_llm_api_key="sk-abcdefg12345",
        base_workspace_dir=str(temp_config.parent / "workspace"),
    )
    save_config(settings)
    assert config_exists()

    loaded = load_config()
    assert loaded.full_name == "Alice"
    assert loaded.primary_llm_api_key == "sk-abcdefg12345"


def test_mask_key():
    assert mask_key("sk-abcdefg12345") == "sk-...2345"
    assert mask_key("123") == "****"
    assert mask_key("") == ""


def test_initialize_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_path = Path(tmpdir) / "AAPL"
        initialize_workspace(ws_path, "AAPL")

        # Verify 7 folders exist
        folders = [
            "1_ingest_data",
            "2_parsed_data",
            "3_archived_data",
            "4_extracted_data",
            "5_historical_analysis",
            "6_financial_model",
            "7_historical_model_json",
        ]
        for f in folders:
            folder_path = ws_path / f
            assert folder_path.exists()
            assert folder_path.is_dir()
            readme_path = folder_path / "README.md"
            assert readme_path.exists()
            assert "AAPL" in readme_path.read_text(encoding="utf-8")

        # Verify root files exist
        assert (ws_path / "AAPL_wiki.md").exists()
        assert (ws_path / "AAPL_extract_learning.md").exists()
        assert (ws_path / "AAPL_analyze_learning.md").exists()
        assert (ws_path / "AAPL_model_learning.md").exists()


def test_cli_config_show(temp_config):
    settings = Settings(
        full_name="Bob",
        email="bob@example.com",
        project_name="BobProj",
        primary_llm_api_key="sk-secret-key-1234",
        base_workspace_dir=str(temp_config.parent / "workspace"),
    )
    save_config(settings)

    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "Bob" in result.stdout
    assert "sk-...1234" in result.stdout
    assert "Gemini Model" in result.stdout
    assert "OpenRouter Model" in result.stdout
    assert "DeepSeek Model" in result.stdout


def test_cli_use_command(temp_config):
    base_dir = temp_config.parent / "workspace"
    settings = Settings(
        full_name="Bob",
        email="bob@example.com",
        project_name="BobProj",
        primary_llm_api_key="sk-secret-key-1234",
        base_workspace_dir=str(base_dir),
    )
    save_config(settings)

    result = runner.invoke(app, ["use", "AAPL"])
    assert result.exit_code == 0
    assert "AAPL" in result.stdout

    target_path = base_dir / "AAPL"
    assert target_path.exists()
    assert (target_path / "1_ingest_data").exists()

    updated = load_config()
    assert updated.active_ticker == "AAPL"
    assert updated.active_workspace_path == str(target_path)


def test_cli_use_command_lowercase_ticker(temp_config):
    base_dir = temp_config.parent / "workspace"
    settings = Settings(
        full_name="Bob",
        email="bob@example.com",
        project_name="BobProj",
        primary_llm_api_key="sk-secret-key-1234",
        base_workspace_dir=str(base_dir),
    )
    save_config(settings)

    result = runner.invoke(app, ["use", "msft"])
    assert result.exit_code == 0
    assert "MSFT" in result.stdout

    target_path = base_dir / "MSFT"
    assert target_path.exists()

    updated = load_config()
    assert updated.active_ticker == "MSFT"
    assert updated.active_workspace_path == str(target_path)


def test_cli_use_command_mistaken_command_cancelled(temp_config):
    base_dir = temp_config.parent / "workspace"
    settings = Settings(
        full_name="Bob",
        email="bob@example.com",
        project_name="BobProj",
        primary_llm_api_key="sk-secret-key-1234",
        base_workspace_dir=str(base_dir),
    )
    save_config(settings)

    # Simulate answering "no" to the prompt
    result = runner.invoke(app, ["use", "ingest"], input="n\n")
    assert result.exit_code == 0
    assert "Workspace switch cancelled" in result.stdout

    # Active ticker should remain unchanged (None)
    updated = load_config()
    assert updated.active_ticker is None


def test_cli_use_command_mistaken_command_confirmed(temp_config):
    base_dir = temp_config.parent / "workspace"
    settings = Settings(
        full_name="Bob",
        email="bob@example.com",
        project_name="BobProj",
        primary_llm_api_key="sk-secret-key-1234",
        base_workspace_dir=str(base_dir),
    )
    save_config(settings)

    # Simulate answering "yes" to the prompt
    result = runner.invoke(app, ["use", "ingest"], input="y\n")
    assert result.exit_code == 0
    assert "INGEST" in result.stdout
    assert "Workspace switch cancelled" not in result.stdout

    target_path = base_dir / "INGEST"
    assert target_path.exists()

    updated = load_config()
    assert updated.active_ticker == "INGEST"


def test_startup_config_auto_detection(monkeypatch, temp_config):
    # Test that auto-init is triggered if config is missing
    from src.cli.main import main

    assert not config_exists()

    def mock_init():
        print("Mock initializing config flow")
        raise Exception("Mock init exception")

    monkeypatch.setattr("src.cli.main.config_cmd.initialize_config_flow", mock_init)

    monkeypatch.setattr("sys.argv", ["fa"])

    try:
        main()
    except SystemExit as e:
        assert e.code == 1


def test_pig_animation_custom_prompt():
    from src.utils.pig_animation import PigState

    state = PigState()
    prompt_html = state.get_prompt("Enter something: ")
    assert "Enter something: " in str(prompt_html)


def test_initialize_config_flow_default_workspace(monkeypatch, temp_config):
    from pathlib import Path

    # Mock PromptSession to avoid NoConsoleScreenBufferError in tests
    class MockPromptSession:
        pass

    monkeypatch.setattr("src.cli.commands.config.PromptSession", MockPromptSession)

    from src.cli.commands.config import initialize_config_flow

    prompts = [
        "Test User",  # Full Name
        "test@example.com",  # Email
        "Test_Project_2026",  # Project Name
        "openrouter",  # API Provider Selection
        "sk-abc123xyz",  # OpenRouter API Key
        "",  # Text model (default)
        "",  # Workspace Path (default)
    ]
    prompt_idx = 0

    async def mock_get_input_with_pig(*args, **kwargs):
        nonlocal prompt_idx
        val = prompts[prompt_idx]
        prompt_idx += 1
        return val

    monkeypatch.setattr(
        "src.cli.commands.config.get_input_with_pig", mock_get_input_with_pig
    )

    settings = initialize_config_flow()

    expected_ws = str(Path.home() / "Desktop" / "Test_Project_2026")
    assert settings.project_name == "Test_Project_2026"
    assert settings.base_workspace_dir == expected_ws


def test_cli_run_edgar_no_active_ticker(temp_config):
    # Initialize basic settings but no active ticker
    settings = Settings(
        full_name="Bob",
        email="bob@example.com",
        project_name="BobProj",
        primary_llm_api_key="sk-secret-key-1234",
        base_workspace_dir=str(temp_config.parent / "workspace"),
        active_ticker=None,
        active_workspace_path=None,
    )
    save_config(settings)

    # Calling run edgar with no ticker should fail since no active ticker is selected
    result = runner.invoke(app, ["run", "edgar"])
    assert result.exit_code == 1
    assert "No active ticker selected" in result.stdout


@patch("src.services.edgar_client.EdgarClient.download_filings")
def test_cli_run_edgar_uses_active_ticker(mock_download, temp_config):
    mock_download.return_value = []
    base_dir = temp_config.parent / "workspace"
    settings = Settings(
        full_name="Bob",
        email="bob@example.com",
        project_name="BobProj",
        primary_llm_api_key="sk-secret-key-1234",
        base_workspace_dir=str(base_dir),
        active_ticker="AAPL",
        active_workspace_path=str(base_dir / "AAPL"),
    )
    save_config(settings)

    # Calling run edgar with no arguments should default to active ticker (AAPL)
    result = runner.invoke(app, ["run", "edgar"])
    assert result.exit_code == 0
    assert "filings download for AAPL" in result.stdout
    mock_download.assert_called_once_with("AAPL", 5)


def test_initialize_config_flow_gemini(monkeypatch, temp_config):
    # Mock PromptSession to avoid NoConsoleScreenBufferError in tests
    class MockPromptSession:
        pass

    monkeypatch.setattr("src.cli.commands.config.PromptSession", MockPromptSession)

    from src.cli.commands.config import initialize_config_flow

    prompts = [
        "Test User Gemini",  # Full Name
        "gemini@example.com",  # Email
        "Gemini_Proj",  # Project Name
        "gemini",  # API Provider Selection
        "AIzaSy-geminiKey",  # Gemini API Key
        "",  # Text model (default)
        "",  # Workspace Path (default)
    ]
    prompt_idx = 0

    async def mock_get_input_with_pig(*args, **kwargs):
        nonlocal prompt_idx
        val = prompts[prompt_idx]
        prompt_idx += 1
        return val

    monkeypatch.setattr(
        "src.cli.commands.config.get_input_with_pig", mock_get_input_with_pig
    )

    settings = initialize_config_flow()

    assert settings.project_name == "Gemini_Proj"
    assert settings.api_provider == "gemini"
    assert settings.gemini_api_key == "AIzaSy-geminiKey"
    assert settings.text_model_id == "gemini-2.5-flash"


def test_cli_config_set(temp_config):
    settings = Settings(
        full_name="Bob",
        email="bob@example.com",
        project_name="BobProj",
        primary_llm_api_key="sk-secret-key-1234",
        base_workspace_dir=str(temp_config.parent / "workspace"),
    )
    save_config(settings)

    # test setting provider and keys
    result = runner.invoke(
        app,
        [
            "config",
            "set",
            "--provider",
            "gemini",
            "--gemini-key",
            "AIzaSy-new-gemini-key",
        ],
    )
    assert result.exit_code == 0
    assert "updated successfully" in result.stdout.lower()

    updated = load_config()
    assert updated.api_provider == "gemini"
    assert updated.gemini_api_key == "AIzaSy-new-gemini-key"
    assert updated.primary_llm_api_key == "AIzaSy-new-gemini-key"
    assert updated.text_model_id == "gemini-2.5-flash"

    # test setting provider to deepseek
    result = runner.invoke(
        app,
        [
            "config",
            "set",
            "--provider",
            "deepseek",
            "--deepseek-key",
            "sk-ds-new-deepseek-key",
        ],
    )
    assert result.exit_code == 0
    assert "updated successfully" in result.stdout.lower()

    updated = load_config()
    assert updated.api_provider == "deepseek"
    assert updated.deepseek_api_key == "sk-ds-new-deepseek-key"
    assert updated.primary_llm_api_key == "sk-ds-new-deepseek-key"
    assert updated.text_model_id == "deepseek-v4-flash"

    # test setting provider-specific models directly
    result = runner.invoke(
        app,
        [
            "config",
            "set",
            "--gemini-model",
            "gemini-test-custom",
            "--openrouter-model",
            "openrouter-test-custom",
            "--deepseek-model",
            "deepseek-test-custom",
        ],
    )
    assert result.exit_code == 0
    assert "updated successfully" in result.stdout.lower()

    updated = load_config()
    assert updated.gemini_model == "gemini-test-custom"
    assert updated.openrouter_model == "openrouter-test-custom"
    assert updated.deepseek_model == "deepseek-test-custom"
    assert updated.text_model_id == "deepseek-test-custom"


def test_initialize_config_flow_deepseek(monkeypatch, temp_config):
    # Mock PromptSession to avoid NoConsoleScreenBufferError in tests
    class MockPromptSession:
        pass

    monkeypatch.setattr("src.cli.commands.config.PromptSession", MockPromptSession)

    from src.cli.commands.config import initialize_config_flow

    prompts = [
        "Test User DeepSeek",  # Full Name
        "deepseek@example.com",  # Email
        "DS_Proj",  # Project Name
        "deepseek",  # API Provider Selection
        "sk-ds-deepseekKey",  # DeepSeek API Key
        "",  # Text model (default)
        "",  # Workspace Path (default)
    ]
    prompt_idx = 0

    async def mock_get_input_with_pig(*args, **kwargs):
        nonlocal prompt_idx
        val = prompts[prompt_idx]
        prompt_idx += 1
        return val

    monkeypatch.setattr(
        "src.cli.commands.config.get_input_with_pig", mock_get_input_with_pig
    )

    settings = initialize_config_flow()

    assert settings.project_name == "DS_Proj"
    assert settings.api_provider == "deepseek"
    assert settings.deepseek_api_key == "sk-ds-deepseekKey"
    assert settings.text_model_id == "deepseek-v4-flash"


@patch("src.cli.main.Extractor")
def test_cli_run_extract(mock_extractor_cls, temp_config):
    mock_extractor = MagicMock()
    mock_extractor.load_extracted_registry.return_value = [
        "20250828_quarterly_filing.md"
    ]
    mock_extractor_cls.return_value = mock_extractor

    base_dir = temp_config.parent / "workspace"
    settings = Settings(
        full_name="Bob",
        email="bob@example.com",
        project_name="BobProj",
        primary_llm_api_key="sk-secret-key-1234",
        base_workspace_dir=str(base_dir),
        active_ticker="AAPL",
        active_workspace_path=str(base_dir / "AAPL"),
    )
    save_config(settings)

    # Create parsed files in 2_parsed_data
    parsed_dir = base_dir / "AAPL" / "2_parsed_data"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    (parsed_dir / "20250828_quarterly_filing.md").write_text("dummy", encoding="utf-8")
    (parsed_dir / "20260131_annual_filing.md").write_text("dummy", encoding="utf-8")
    (parsed_dir / "20260521_quarterly_filing.md").write_text("dummy", encoding="utf-8")

    # Order expected:
    # New files descending: 20260521_quarterly_filing.md, 20260131_annual_filing.md
    # Extracted files descending: 20250828_quarterly_filing.md
    # So:
    # a) 20260521_quarterly_filing.md
    # b) 20260131_annual_filing.md
    # c) 20250828_quarterly_filing.md (already extracted)

    # Test selecting 'c' (re-extraction of a specific file)
    result = runner.invoke(app, ["run", "extract"], input="c\n")
    assert result.exit_code == 0
    import re

    stdout_clean = result.stdout.replace("\n", " ")
    stdout_clean = re.sub(r"[\u2500-\u257F│┌┐└┘├┤┬┴┼]", " ", stdout_clean)
    stdout_clean = re.sub(r"\s+", " ", stdout_clean)
    assert "ready for extraction" in stdout_clean
    assert "2 are new" in stdout_clean
    assert "a) 20260521_quarterly_filing.md" in stdout_clean
    assert "b) 20260131_annual_filing.md" in stdout_clean
    assert "c) 20250828_quarterly_filing.md (already extracted)" in stdout_clean

    # Verify that run_extraction was called with the specific file path of 'c'
    mock_extractor.run_extraction.assert_called_with(
        files_to_process=[parsed_dir / "20250828_quarterly_filing.md"]
    )
