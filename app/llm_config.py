"""Server-only OpenAI-compatible API configuration and sanitized diagnostics."""

import math
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float
    max_tokens: int
    temperature: float | None

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
        if not math.isfinite(timeout) or not 1 <= timeout <= 120:
            raise ValueError("LLM_TIMEOUT: допустимо от 1 до 120 секунд")
        if not 128 <= maximum <= 8192:
            raise ValueError("LLM_MAX_TOKENS: допустимо от 128 до 8192")
        if temperature is not None and (not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise ValueError("LLM_TEMPERATURE: допустимо от 0 до 2 или пустое значение")
        return cls(base, os.getenv("LLM_API_KEY", "").strip(),
                   os.getenv("LLM_MODEL", "").strip(), timeout, maximum, temperature)

    def request_body(self, messages):
        body = {
            "model": self.model, "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"}, "messages": messages,
        }
        # Not every model accepts explicit sampling parameters. Let the provider
        # choose its default unless the operator intentionally configures one.
        if self.temperature is not None:
            body["temperature"] = self.temperature
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
