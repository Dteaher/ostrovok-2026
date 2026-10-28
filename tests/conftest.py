"""Unit/regression tests must not consume a developer's real model balance."""

import pytest


@pytest.fixture(autouse=True)
def no_real_model_credentials(monkeypatch):
    # Individual adapter tests replace these with fake credentials and a local
    # server/mock. A developer's populated .env must never cause paid pytest calls.
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("AGENT_ENABLED", "0")
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("LLM_STRUCTURED_OUTPUT", "0")
    monkeypatch.setenv("LLM_TRUST_ENV", "0")
    # Provider contract tests opt in with fake keys; production defaults local.
    monkeypatch.setenv("TRAVEL_MODE", "connected")
