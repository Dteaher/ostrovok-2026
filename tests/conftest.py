"""Unit/regression tests must not consume a developer's real model balance."""

import pytest


@pytest.fixture(autouse=True)
def no_real_model_credentials(monkeypatch):
    # Individual adapter tests replace these with fake credentials and a local
    # server/mock. A developer's populated .env must never cause paid pytest calls.
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_MODEL", "")
