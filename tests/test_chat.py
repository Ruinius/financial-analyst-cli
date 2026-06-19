from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from src.cli.commands.chat import app

runner = CliRunner()


@patch("prompt_toolkit.PromptSession")
@patch("src.cli.commands.chat.get_llm_client")
@patch("src.cli.commands.chat.get_input_with_pig")
def test_chat_interaction_flow(
    mock_get_input, mock_llm_client_class, mock_prompt_session_class
):
    # Set up simulated inputs:
    # 1. Standard chat text
    # 2. Math calculation
    # 3. Exit command
    simulated_inputs = ["Splendid weather for truffles", "= 5 * 6 + 12", "exit"]
    input_index = 0

    async def side_effect_input(*args, **kwargs):
        nonlocal input_index
        val = simulated_inputs[input_index]
        input_index += 1
        return val

    mock_get_input.side_effect = side_effect_input

    # Mock LLM Client behavior
    mock_llm_instance = MagicMock()
    mock_llm_instance.generate.return_value = (
        "Indeed, my dear fellow, the markets look exceptional today!"
    )
    mock_llm_client_class.return_value = mock_llm_instance

    result = runner.invoke(app, ["AAPL"])

    assert result.exit_code == 0
    # Check that LLM query was processed
    assert (
        "Sir Pennyworth is pondering..." in result.stdout or "Indeed" in result.stdout
    )
    assert "exceptional today" in result.stdout

    # Check that math calculation was processed and solved (5 * 6 + 12 = 42)
    assert "result of your calculation is precisely" in result.stdout
    assert "42" in result.stdout

    # Check exit greeting
    assert "Tata for now" in result.stdout or "pennies make pounds" in result.stdout


@patch("prompt_toolkit.PromptSession")
@patch("src.cli.commands.chat.get_llm_client")
@patch("src.cli.commands.chat.get_input_with_pig")
def test_chat_keyboard_interrupt(
    mock_get_input, mock_llm_client_class, mock_prompt_session_class
):
    # Simulate KeyboardInterrupt on prompt input
    mock_get_input.side_effect = KeyboardInterrupt()

    mock_llm_client_class.return_value = MagicMock()

    result = runner.invoke(app, ["AAPL"])
    assert result.exit_code == 0
    assert "financial truffling" in result.stdout
