"""Tests for Ollama local LLM provider integration, model discovery, and routing."""

import io
import json
import urllib.error
import urllib.request
import pytest

from src.model.repair_model import (
    HostedLLMProvider,
    MockModelProvider,
    OllamaProvider,
    get_provider,
)
from src.model.schemas import ProviderUnavailableError
from src.systems.pipeline import run_pipeline


class MockHTTPResponse:
    def __init__(self, data: dict, status: int = 200):
        self._content = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self):
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_ollama_provider_defaults():
    provider = OllamaProvider()
    assert provider.base_url == "http://localhost:11434"
    assert provider.model_name in ("deepseek-coder", "codellama", "llama3", "qwen2.5-coder")
    assert provider.get_model_name().startswith("ollama:")


def test_ollama_provider_offline_check():
    # Points to a non-existent port to test offline detection
    provider = OllamaProvider(base_url="http://127.0.0.1:54321")
    assert not provider.is_available()
    assert provider.list_models() == []


def test_ollama_provider_available_when_server_responds(monkeypatch):
    import socket
    provider = OllamaProvider(base_url="http://mock-ollama:11434")

    class MockSocket:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: MockSocket())
    assert provider.is_available()


def test_ollama_provider_list_models_success(monkeypatch):
    provider = OllamaProvider(base_url="http://mock-ollama:11434")

    def mock_urlopen(req, timeout=None):
        if "/api/tags" in req.full_url:
            return MockHTTPResponse({
                "models": [
                    {"name": "deepseek-coder:6.7b"},
                    {"name": "llama3:latest"},
                    {"name": "qwen2.5-coder:7b"},
                ]
            })
        raise urllib.error.URLError("Not found")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    models = provider.list_models()
    assert models == ["deepseek-coder:6.7b", "llama3:latest", "qwen2.5-coder:7b"]


def test_ollama_provider_generate_json(monkeypatch):
    provider = OllamaProvider(base_url="http://mock-ollama:11434", model_name="deepseek-coder")
    recorded_req = {}

    def mock_urlopen(req, timeout=None):
        recorded_req["url"] = req.full_url
        recorded_req["data"] = json.loads(req.data.decode("utf-8"))
        return MockHTTPResponse({
            "message": {
                "role": "assistant",
                "content": json.dumps({
                    "repaired_code": "def add(a, b):\n    return a + b\n",
                    "repair_category": "syntax",
                    "root_cause": "Missing colon after def header",
                    "target_line": 1,
                    "confidence": 0.95,
                }),
            }
        })

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    output = provider.generate("Fix this code", system_prompt="You are a code fixer")
    data = json.loads(output)
    assert data["repaired_code"] == "def add(a, b):\n    return a + b\n"
    assert recorded_req["data"]["format"] == "json"
    assert recorded_req["data"]["model"] == "deepseek-coder"
    assert len(recorded_req["data"]["messages"]) == 2


def test_ollama_provider_offline_raises_unavailable():
    provider = OllamaProvider(base_url="http://127.0.0.1:54321", timeout_seconds=0.5)
    with pytest.raises(ProviderUnavailableError, match="Failed to connect to Ollama"):
        provider.generate("Fix this")


def test_get_provider_factory():
    p_mock = get_provider("mock")
    assert isinstance(p_mock, MockModelProvider)

    p_ollama = get_provider("ollama", model_name="llama3")
    assert isinstance(p_ollama, OllamaProvider)
    assert p_ollama.model_name == "llama3"

    p_hosted = get_provider("hosted", model_name="gpt-4o")
    assert isinstance(p_hosted, HostedLLMProvider)


def test_pipeline_with_ollama_mock_integration(monkeypatch):
    # Test that run_pipeline accepts provider="ollama" and handles successful generation
    def mock_urlopen(req, timeout=None):
        return MockHTTPResponse({
            "message": {
                "content": json.dumps({
                    "repaired_code": "def add(a, b):\n    return a + b\n",
                    "repair_category": "delimiter_punctuation",
                    "root_cause": "Added colon",
                    "target_line": 1,
                    "confidence": 0.9,
                })
            }
        })

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    report = run_pipeline("def add(a, b)\n    return a + b\n", "python", provider="ollama")
    assert report.status == "VERIFIED"
    assert report.repaired_code == "def add(a, b):\n    return a + b\n"
    assert "ollama:" in (report.model_used or "")


def test_api_models_endpoint():
    import threading
    from http.server import ThreadingHTTPServer
    from dev_frontend.server import Handler

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/api/models", timeout=5) as resp:
            data = json.load(resp)
        assert "providers" in data
        assert "ollama" in data["providers"]
        assert "mock" in data["providers"]
        assert data["providers"]["mock"]["available"] is True
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
