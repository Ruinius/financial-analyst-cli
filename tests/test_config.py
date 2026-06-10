import tempfile
from pathlib import Path
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
    assert settings.text_model_id == "google/gemma-2-9b-it"


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

        # Verify 8 folders exist
        folders = [
            "1_ingest_data",
            "2_parsed_data",
            "3_archived_data",
            "4_extracted_data",
            "5_historical_analysis",
            "6_company_context",
            "7_financial_model",
            "8_historical_model_json",
        ]
        for f in folders:
            folder_path = ws_path / f
            assert folder_path.exists()
            assert folder_path.is_dir()
            readme_path = folder_path / "README.md"
            assert readme_path.exists()
            assert "AAPL" in readme_path.read_text(encoding="utf-8")


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

def test_startup_config_auto_detection(monkeypatch, temp_config):
    # Test that auto-init is triggered if config is missing
    from src.cli.main import main
    import sys

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
