import pytest
from src.cli.commands.chat import main_chat

def test_chat_import():
    assert main_chat is not None
