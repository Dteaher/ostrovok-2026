"""Local real-HTTP provider contract, sanitized failures and judge setup."""

import asyncio
import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.llm_config import LLMConfig
from app.main import create_app
from app.models import TripRequirements
from app.parser import extract_intent
from scripts.check_llm import check


@pytest.fixture
def provider(monkeypatch):
    state = {"status": 200, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append({"path": self.path, "body": body,
                                      "authorized": self.headers.get("Authorization") == "Bearer pza_test_not_real"})
            payload = {"choices": [{"message": {"content": json.dumps({
                "patch": {"budget": 160000}, "recognized": True,
            })}}]} if state["status"] == 200 else {"error": "pza_test_not_real private-provider-body"}
            if state["status"] == 200 and "content" in state:
                payload["choices"][0]["message"]["content"] = state["content"]
            encoded = json.dumps(payload).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/api/v1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("LLM_API_KEY", "pza_test_not_real")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-5.4-mini")
    monkeypatch.setenv("LLM_TIMEOUT", "2")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1500")
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    yield state
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


def test_real_http_uses_versioned_endpoint_and_server_only_key(provider):
    req = TripRequirements(budget=180000)
    result = asyncio.run(extract_intent("Бюджет 160 тысяч", req, date(2026, 10, 27)))
    assert result.mode == "llm" and result.patch["budget"] == 160000
    request = provider["requests"][0]
    assert request["path"] == "/api/v1/chat/completions" and request["authorized"]
    assert request["body"]["model"] == "openai/gpt-5.4-mini"
    assert request["body"]["max_tokens"] == 1500
    assert "temperature" not in request["body"]
    assert "pza_test_not_real" not in json.dumps(request["body"])
    assert req.budget == 180000


@pytest.mark.parametrize("status,reason", [(401, "ключ"), (402, "баланс"), (403, "доступ"), (404, "модель"), (429, "частоту"), (503, "недоступен")])
def test_provider_errors_have_actionable_safe_fallback(provider, status, reason, caplog):
    provider["status"] = status
    result = asyncio.run(extract_intent("Бюджет 160 тысяч", TripRequirements(), date(2026, 10, 27)))
    assert result.mode == "rules" and result.patch["budget"] == 160000
    assert reason in " ".join(result.notices)
    assert len(provider["requests"]) == 1  # no uncontrolled paid retry
    assert "pza_test_not_real" not in caplog.text + repr(result)
    assert "private-provider-body" not in caplog.text + repr(result)


def test_cli_probe_requires_real_success_mode_and_hides_key(provider, capsys):
    assert asyncio.run(check()) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and report["mode"] == "llm"
    provider["status"] = 402
    assert asyncio.run(check()) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and "баланс" in report["reason"]
    assert "pza_test_not_real" not in json.dumps(report)


@pytest.mark.parametrize("name,value", [
    ("LLM_TIMEOUT", "nan"), ("LLM_TIMEOUT", "0"), ("LLM_MAX_TOKENS", "0"),
    ("LLM_TEMPERATURE", "inf"), ("LLM_BASE_URL", "http://polza.ai/api/v1"),
    ("LLM_BASE_URL", "https://key:secret@polza.ai/api/v1"),
    ("LLM_BASE_URL", "https://polza.ai/api/v1?key=secret"),
])
def test_invalid_configuration_falls_back_before_network(provider, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        LLMConfig.from_env()
    result = asyncio.run(extract_intent("Бюджет 160 тысяч", TripRequirements(), date(2026, 10, 27)))
    assert result.mode == "rules" and result.notices
    assert not provider["requests"]


def test_explicit_supported_temperature_is_optional(provider, monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.2")
    asyncio.run(extract_intent("Бюджет 160 тысяч", TripRequirements(), date(2026, 10, 27)))
    assert provider["requests"][0]["body"]["temperature"] == 0.2


def test_no_key_probe_does_not_call_provider(provider, monkeypatch, capsys):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setattr("scripts.check_llm.load_dotenv", lambda *args, **kwargs: None)
    assert asyncio.run(check()) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert not provider["requests"]


def test_application_readiness_and_public_config_do_not_call_model_or_expose_key(provider, tmp_path):
    from fastapi.testclient import TestClient

    with TestClient(create_app("sqlite:///" + (tmp_path / "readiness.db").as_posix())) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.get("/api/config")
        assert response.json()["parser_mode"] == "llm"
        assert "pza_test_not_real" not in response.text
        assert not provider["requests"]


def test_fenced_provider_json_still_obeys_domain_validation(provider):
    req = TripRequirements(budget=180000)
    provider["content"] = '```json\n{"patch":{"budget":160000},"recognized":true}\n```'
    result = asyncio.run(extract_intent("Бюджет 160 тысяч", req, date(2026, 10, 27)))
    assert result.mode == "llm" and result.patch["budget"] == 160000
    provider["content"] = '```json\n{"patch":{"secret":"invented"},"recognized":true}\n```'
    result = asyncio.run(extract_intent("Бюджет 160 тысяч", req, date(2026, 10, 27)))
    assert result.mode != "llm" and "secret" not in result.patch


def test_compose_and_runtime_include_multiai_settings_and_probe():
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    template = (root / ".env.example").read_text(encoding="utf-8")
    assert "COPY --chown=oplan:oplan scripts ./scripts" in dockerfile
    assert "LLM_BASE_URL: ${LLM_BASE_URL:-https://multiai.store/v1}" in compose
    assert "LLM_MODEL: ${LLM_MODEL:-gpt-5.6-luna}" in compose
    assert "LLM_API_KEY=\n" in template
    assert "LLM_MAX_TOKENS:" in compose and "LLM_TEMPERATURE:" in compose
