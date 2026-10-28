"""Explicit paid concierge probe with synthetic data, no database or orders."""

import asyncio
import json
import logging
import sys
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent import enabled  # noqa: E402
from app.evidence import facts_for  # noqa: E402
from app.parser import ParsedIntent  # noqa: E402
from app.service import compile_state, local_today, new_state, process_message  # noqa: E402


async def run():
    load_dotenv(ROOT / ".env", override=False)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not enabled():
        print("Agent API not configured; no paid requests performed.")
        return 2
    state = compile_state(new_state(), ParsedIntent(patch={"destination": "Сочи", "check_in": (local_today() + timedelta(days=45)).isoformat(), "budget": 500000, "breakfast": True}, recognized=True))
    results = []
    for message, tool in [
        ("Объясни, почему эти варианты рекомендованы", "explain"),
        ("Сравни первый и второй отель", "compare"),
        ("Покажи сначала варианты ближе к морю", "prioritize"),
        ("Есть ли в первом отеле спа?", "details"),
        ("Предложи альтернативы", "alternatives"),
    ]:
        before = deepcopy(state["requirements"])
        state = await process_message(state, message)
        result = state.get("agent") or {}
        known = {f["id"]: f for f in facts_for(state, result.get("offer_indices") or None, alternatives=tool == "alternatives")}
        checked = bool(result.get("facts")) and all(f["id"] in known and f == known[f["id"]] for f in result.get("facts", []))
        ok = result.get("tool") == tool and result.get("mode") == "llm" and checked and state["requirements"] == before and state["order"] is None
        row = {"tool": tool, "actual_tool": result.get("tool"), "mode": result.get("mode"), "evidence_valid": checked, "passed": ok}
        results.append(row)
        print(json.dumps(row), flush=True)
    target = ROOT / "artifacts" / "agent-live-check.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if all(row["passed"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
