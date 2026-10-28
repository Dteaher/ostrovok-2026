"""Paid sequential compatibility probe. No fallback, credentials or raw bodies printed."""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.llm_config import LLMConfig, parse_completion  # noqa: E402


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 120:
        parser.error("timeout must be 1..120")
    load_dotenv(ROOT / ".env")
    config = LLMConfig.from_env()
    if not config.api_key or not config.model:
        raise SystemExit("Credentials/model not configured")
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    stages = [
        ("simple", "Reply OK", {}),
        ("json", 'Return JSON {"ok":true}', {"response_format": {"type": "json_object"}}),
        ("schema", 'Return JSON {"ok":true}', {"response_format": {"type": "json_schema", "json_schema": {"name": "probe", "strict": True, "schema": schema}}}),
        ("tool", "Call check_trip", {"tools": [{"type": "function", "function": {"name": "check_trip", "description": "Check trip", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}], "tool_choice": {"type": "function", "function": {"name": "check_trip"}}}),
    ]
    results = []
    with httpx.Client(timeout=args.timeout, follow_redirects=False) as client:
        for name, prompt, extra in stages:
            started = time.monotonic()
            row = {"stage": name, "model": config.model}
            try:
                response = client.post(config.base_url + "/chat/completions", headers={"Authorization": "Bearer " + config.api_key},
                    json={"model": config.model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 256, **extra})
                row["http"] = response.status_code
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                if name == "tool":
                    calls = message.get("tool_calls") or []
                    row["tool_count"] = len(calls)
                    row["valid"] = len(calls) == 1 and calls[0]["function"]["name"] == "check_trip" and json.loads(calls[0]["function"]["arguments"]) == {}
                elif name == "simple":
                    row["valid"] = message.get("content", "").strip() == "OK"
                else:
                    row["valid"] = parse_completion(data) == {"ok": True}
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                row["error_type"] = type(exc).__name__
                row["valid"] = False
            row["seconds"] = round(time.monotonic() - started, 2)
            results.append(row)
            print(json.dumps(row), flush=True)
            (ROOT / "artifacts/provider-probe.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if all(r["valid"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(run())
