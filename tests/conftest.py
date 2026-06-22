import socket
import pytest


@pytest.fixture(autouse=True)
def block_network_calls(monkeypatch):
    """
    Globally block all socket-based network calls in the test suite to prevent accidental LLM or external API calls,
    while allowing local loopback connections needed by asyncio and local servers.
    """
    original_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0]
        if host not in ("localhost", "127.0.0.1", "::1"):
            raise RuntimeError(
                f"Accidental real network connection blocked in tests to prevent real LLM/API calls: {address}. "
                "Please mock the HTTP/API clients in your test."
            )
        return original_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
