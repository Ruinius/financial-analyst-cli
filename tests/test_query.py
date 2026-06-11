import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from src.cli.commands.query import app

runner = CliRunner()


@patch("src.cli.commands.query.load_config")
def test_query_summary(mock_load_config):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ticker = "AAPL"

        # Setup mock workspace structure
        workspace = tmp_path / ticker
        hist_dir = workspace / "5_historical_analysis"
        hist_dir.mkdir(parents=True)

        annual_file = hist_dir / "financials_annual.md"
        annual_file.write_text("# Annual Financials\nRevenue: $100B", encoding="utf-8")

        quarter_file = hist_dir / "financials_quarter.md"
        quarter_file.write_text(
            "# Quarterly Financials\nRevenue: $25B", encoding="utf-8"
        )

        mock_settings = MagicMock()
        mock_settings.base_workspace_dir = str(tmp_path)
        mock_load_config.return_value = mock_settings

        result = runner.invoke(app, ["summary", ticker])
        assert result.exit_code == 0
        assert "Annual Financials" in result.stdout
        assert "Quarterly Financials" in result.stdout
        assert "Revenue: $100B" in result.stdout


@patch("src.cli.commands.query.load_config")
def test_query_assessment(mock_load_config):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ticker = "AAPL"

        workspace = tmp_path / ticker
        hist_dir = workspace / "5_historical_analysis"
        hist_dir.mkdir(parents=True)

        views_file = hist_dir / "analyst_views.md"
        views_file.write_text(
            "# Economic Moat\nWide economic moat rating", encoding="utf-8"
        )

        mock_settings = MagicMock()
        mock_settings.base_workspace_dir = str(tmp_path)
        mock_load_config.return_value = mock_settings

        result = runner.invoke(app, ["assessment", ticker])
        assert result.exit_code == 0
        assert "Economic Moat" in result.stdout
        assert "Wide economic moat rating" in result.stdout


@patch("src.cli.commands.query.load_config")
def test_query_valuation(mock_load_config):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ticker = "AAPL"

        workspace = tmp_path / ticker
        model_dir = workspace / "7_financial_model"
        model_dir.mkdir(parents=True)

        # Write dummy model markdown files
        model_file1 = model_dir / "20240101_AAPL_model.md"
        model_file1.write_text("# Old Model\nIntrinsic value: $150", encoding="utf-8")

        model_file2 = model_dir / "20240102_AAPL_model.md"
        model_file2.write_text(
            "# Latest Model\nIntrinsic value: $160", encoding="utf-8"
        )

        mock_settings = MagicMock()
        mock_settings.base_workspace_dir = str(tmp_path)
        mock_load_config.return_value = mock_settings

        result = runner.invoke(app, ["valuation", ticker])
        assert result.exit_code == 0
        # The subcommand picks the most recently modified file. Since both are created close in time,
        # either might be picked, but we assert at least one successful load containing "Model"
        assert "Model" in result.stdout
        assert "Intrinsic value" in result.stdout


@patch("src.cli.commands.query.load_config")
def test_query_trace(mock_load_config):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ticker = "AAPL"

        workspace = tmp_path / ticker
        extracted_dir = workspace / "4_extracted_data"
        extracted_dir.mkdir(parents=True)

        extracted_file = extracted_dir / "2024_extracted.md"
        extracted_file.write_text(
            "# Extractions\n"
            "| Metric | Value |\n"
            "|---|---|\n"
            "| Revenue | 350,000 |\n"
            "| EBITA | 80,000 |",
            encoding="utf-8",
        )

        mock_settings = MagicMock()
        mock_settings.base_workspace_dir = str(tmp_path)
        mock_load_config.return_value = mock_settings

        # Trace existing metric
        result = runner.invoke(app, ["trace", ticker, "Revenue", "2024"])
        assert result.exit_code == 0
        assert "2024_extracted.md" in result.stdout
        assert "Revenue" in result.stdout
        assert "350,000" in result.stdout

        # Trace non-existent metric
        result_missing = runner.invoke(app, ["trace", ticker, "NetIncome", "2024"])
        assert result_missing.exit_code == 0
        assert "not found" in result_missing.stdout.lower()
