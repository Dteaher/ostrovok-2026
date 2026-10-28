"""Paid, sequential route comparison using identical production request bodies.

Only this diagnostic client's proxy behavior changes. No application settings,
Windows proxy settings, credentials or trip records are modified.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import time
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent import presentation, validate_narration  # noqa: E402
from app.evidence import facts_for  # noqa: E402
from app.llm_config import LLMConfig, parse_completion  # noqa: E402
from app.models import TripRequirements  # noqa: E402
from app.parser import (  # noqa: E402
    ParsedIntent,
    extract_intent,
    parse_rules,
    validated_model_intent,
)
from app.service import compile_state, local_today, new_state  # noqa: E402

MESSAGE = "бюджэт 140 тыщ, осталное не трогай"


async def production_bodies(config, state):
    bodies = {}

    class Capture:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            bodies["intent"] = kwargs["json"]
            content = {"action": "change", "patch": {"budget": 140000},
                       "evidence": {"budget": "140 тыщ"}, "questions": []}
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps(content)}}]})

    async def capture_narration(messages, **kwargs):
        bodies["narration"] = config.request_body(messages,
            output_schema=kwargs.get("output_schema"),
            schema_name=kwargs.get("schema_name", "response"))
        return {"fact_ids": ["ranking"]} if config.structured_output else {
            "title": "Почему эти варианты", "fact_ids": ["ranking"], "ask_priority": False}

    with patch.dict(os.environ, {"TRAVEL_MODE": "connected", "AGENT_ENABLED": "1"}):
        with patch("httpx.AsyncClient", Capture):
            await extract_intent(MESSAGE, TripRequirements.model_validate(state["requirements"]), local_today())
        with patch("app.agent.model_json", side_effect=capture_narration):
            await presentation(deepcopy(state), "Объясни, почему рекомендованы эти варианты", "explain")
    return bodies


async def measure(config, state, body, *, trust_env, stage, repeat, timeout):
    events = []
    started = time.monotonic()
    row = {"repeat": repeat, "route": "system_proxy" if trust_env else "without_system_proxy",
           "stage": stage, "model": config.model, "limit_seconds": timeout,
           "body_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}

    async def trace(name, info):
        event = {"event": name, "seconds": round(time.monotonic() - started, 3)}
        if name == "connection.connect_tcp.started":
            event.update(host=info.get("host"), port=info.get("port"))
        events.append(event)

    try:
        async with asyncio.timeout(timeout), httpx.AsyncClient(
            trust_env=trust_env, timeout=timeout, follow_redirects=False,
        ) as client:
            response = await client.post(config.base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + config.api_key}, json=body,
                extensions={"trace": trace})
            row["http"] = response.status_code
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            row.update(output_chars=len(message.get("content") or ""),
                       reasoning_chars=len(message.get("reasoning_content") or ""))
            usage = data.get("usage") or {}
            row["usage"] = {key: usage[key] for key in (
                "prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(usage.get(key), int)}
            raw = parse_completion(data)
            if stage == "intent":
                current = TripRequirements.model_validate(state["requirements"])
                intent = validated_model_intent(raw, MESSAGE, current,
                    parse_rules(MESSAGE, current, today=local_today()))
                row["valid"] = intent.mode == "llm" and intent.patch == {"budget": 140000}
            else:
                if config.structured_output:
                    raw = {"title": "Почему эти варианты", "fact_ids": raw["fact_ids"],
                           "ask_priority": False}
                validate_narration(raw, facts_for(state), "explain")
                row["valid"] = True
    except ValidationError as exc:
        row.update(valid=False, error_type="ValidationError", schema_errors=[
            {"field": ".".join(map(str, error["loc"])), "type": error["type"]}
            for error in exc.errors(include_input=False, include_url=False)])
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as exc:
        row.update(valid=False, error_type=type(exc).__name__)
    row["seconds"] = round(time.monotonic() - started, 3)
    row["events"] = events
    tls = [e["seconds"] for e in events if e["event"].endswith("start_tls.complete")]
    sent = [e["seconds"] for e in events if e["event"].endswith("send_request_body.complete")
            and tls and e["seconds"] >= tls[-1]]
    row["tls_complete_seconds"] = tls[-1] if tls else None
    row["generation_request_sent_seconds"] = sent[-1] if sent else None
    row["failure_phase"] = next((e["event"] for e in reversed(events)
                                  if e["event"].endswith("failed")), None)
    return row


async def run(args):
    load_dotenv(ROOT / ".env")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    config = LLMConfig.from_env()
    if not config.api_key:
        raise SystemExit("No configured key")
    state = compile_state(new_state(), ParsedIntent(recognized=True, patch={
        "destination": "Сочи", "check_in": (local_today() + timedelta(days=55)).isoformat(),
        "budget": 500000, "breakfast": True}))
    bodies = await production_bodies(config, state)
    if args.effort != "default":
        for body in bodies.values():
            body["reasoning_effort"] = args.effort
    proxies = {}
    for scheme, value in urllib.request.getproxies().items():
        if scheme not in {"http", "https"}:
            continue
        url = urlsplit(value if "://" in value else "http://" + value)
        proxies[scheme] = {"host": url.hostname, "port": url.port}
    report = {"generated_at": datetime.now(ZoneInfo("Europe/Moscow")).isoformat(),
        "model": config.model, "effort": args.effort, "system_proxies": proxies,
        "method": "Sequential paired identical production payloads; alternating route order. No fallback or retries. trust_env=False bypasses the system HTTP proxy, not necessarily an OS VPN/TUN route. No prompts, headers, responses, reasoning text or credentials stored.",
        "results": []}
    for repeat in range(1, args.rounds + 1):
        for stage in ("intent", "narration"):
            for trust_env in ([True, False] if repeat % 2 else [False, True]):
                row = await measure(config, state, bodies[stage], trust_env=trust_env,
                    stage=stage, repeat=repeat, timeout=args.timeout)
                report["results"].append(row)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps({key: value for key, value in row.items()
                    if key not in {"events", "body_sha256", "usage"}}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--effort", choices=["default", "none", "low"], default="default")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/provider-path-retest.json")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 30:
        parser.error("timeout must be between 1 and 30 seconds")
    asyncio.run(run(args))
