"""Server-only OpenAI-compatible API configuration and sanitized diagnostics."""

import json
import math
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from urllib.parse import urlsplit


def strict_object_schema(schema):
    """Make fixed Pydantic objects compatible with strict structured output."""
    value = deepcopy(schema)
    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    return value


def parse_json_content(content: str) -> dict:
    """Accept one JSON object, optionally in a single complete Markdown fence.

    Never extract a JSON-looking substring from prose or execute model text.
    Domain validation still belongs to the caller.
    """
    if not isinstance(content, str):
        raise ValueError("Expected JSON text")
    content = content.strip()
    if content.startswith("```"):
        fence = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", content)
        if fence is None:
            raise ValueError("Invalid JSON fence")
        content = fence.group(1)
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return value


def parse_completion(data: dict) -> dict:
    """The JSON protocol accepts exactly one complete answer, never native calls.

    Native tools are probed separately; application tools use the validated
    Decision schema. Silently ignoring tool_calls could conceal partial output.
    """
    if not isinstance(data, dict):
        raise ValueError("Expected completion object")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("Expected one model choice")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise ValueError("Expected completion message")
    if choice.get("finish_reason") not in {None, "stop"}:
        raise ValueError("Incomplete or non-text completion")
    message = choice["message"]
    if message.get("tool_calls") or message.get("function_call") or message.get("refusal"):
        raise ValueError("Unexpected tool call or refusal in JSON protocol")
    return parse_json_content(message.get("content"))


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float
    max_tokens: int
    temperature: float | None
    reasoning_effort: str | None = None
    structured_output: bool = False
    trust_env: bool = True

    @classmethod
    def from_env(cls):
        base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        parsed = urlsplit(base)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))
        ):
            raise ValueError("LLM_BASE_URL: нужен HTTPS-адрес API без ключа и параметров в URL")
        timeout = float(os.getenv("LLM_TIMEOUT", "30"))
        maximum = int(os.getenv("LLM_MAX_TOKENS", "1500"))
        raw_temperature = os.getenv("LLM_TEMPERATURE", "").strip()
        temperature = float(raw_temperature) if raw_temperature else None
        effort = os.getenv("LLM_REASONING_EFFORT", "").strip() or None
        if effort not in {None, "none", "minimal", "low", "medium", "high", "max"}:
            raise ValueError("LLM_REASONING_EFFORT: недопустимый режим рассуждений")
        structured = os.getenv("LLM_STRUCTURED_OUTPUT", "0").strip().lower() in {"1", "true", "on"}
        trust_env = os.getenv("LLM_TRUST_ENV", "1").strip().lower() not in {"0", "false", "off"}
        if not math.isfinite(timeout) or not 1 <= timeout <= 120:
            raise ValueError("LLM_TIMEOUT: допустимо от 1 до 120 секунд")
        if not 128 <= maximum <= 8192:
            raise ValueError("LLM_MAX_TOKENS: допустимо от 128 до 8192")
        if temperature is not None and (not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise ValueError("LLM_TEMPERATURE: допустимо от 0 до 2 или пустое значение")
        return cls(base, os.getenv("LLM_API_KEY", "").strip(),
                   os.getenv("LLM_MODEL", "").strip(), timeout, maximum, temperature,
                   effort, structured, trust_env)

    def request_body(self, messages, *, output_schema=None, schema_name="response"):
        body = {
            "model": self.model, "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"}, "messages": messages,
        }
        # Not every model accepts explicit sampling parameters. Let the provider
        # choose its default unless the operator intentionally configures one.
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        if self.structured_output and output_schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema_name, "strict": True, "schema": output_schema}}
        return body


def failure_notice(status: int | None = None) -> str:
    reason = {
        401: "Сервис AI отклонил ключ доступа.",
        403: "У ключа нет доступа к выбранной AI-модели.",
        402: "Недостаточно баланса или лимита расходов у AI-провайдера.",
        404: "Выбранная AI-модель или адрес API недоступны.",
        429: "AI-провайдер ограничил частоту запросов.",
    }.get(status, "AI сейчас недоступен.")
    return reason + " Использую локальное понимание условий; проверьте их перед выбором."
