"""Explicit paid connected dialogue. Expected state and real LLM stages checked."""
import asyncio
import json
import logging
import sys
import time
from copy import deepcopy
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent import enabled  # noqa: E402
from app.agent_transport import provider_session  # noqa: E402
from app.evidence import facts_for  # noqa: E402
from app.explanations import explain_snapshot  # noqa: E402
from app.service import new_state, process_message  # noqa: E402


def verdict(parser_mode, agent, *, local, read, quality):
    if local:
        return "local_operation"
    narration = agent.get("mode") == "llm"
    if quality and (narration if read else parser_mode == "llm" and narration):
        return "llm"
    return "fallback_or_partial"


async def run():
    load_dotenv(ROOT / ".env")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not enabled():
        raise SystemExit("LLM credentials not configured")
    cases = [
        ("search", "В Сочи с 20 декабря 2026 на 7 ночей, двое взрослых, бюджет 200 тысяч", {"destination": "Сочи", "check_in": "2026-12-20", "nights": 7, "adults": 2, "budget": 200000}, False, False),
        ("dates", "Перенеси заезд на 22 декабря 2026", {"check_in": "2026-12-22"}, False, False),
        ("budget", "Теперь бюджет 150 тысяч", {"budget": 150000}, False, False),
        ("pet", "Добавь собаку", {"pets": True}, True, False),
        ("explain", "Объясни, почему рекомендованы эти варианты", {}, False, True),
        ("compare", "Сравни первый и второй отель", {}, False, True),
        ("empty", "Снизь бюджет до 1000 рублей", {"budget": 1000}, False, False),
        ("compromises", "Предложи альтернативы", {}, False, True),
        ("confirm", "Подтверждаю компромисс 1", None, True, False),
        ("restore", "Верни первоначальные даты", {"check_in": "2026-12-20", "nights": 7}, True, False),
    ]
    state, rows = new_state(), []
    async with provider_session():
        for name, message, expected, local, read in cases:
            before = deepcopy(state["requirements"])
            if expected is None:
                pending = state.get("_agent_proposals") or {}
                expected = (pending.get("items") or [{}])[0].get("patch", {})
            started = time.monotonic()
            result = await process_message(state, message)
            initial = time.monotonic() - started
            agent = result.get("agent") or {}
            if result.get("_explanation"):
                agent = await explain_snapshot(deepcopy(result)) or {}
                result["agent"] = agent
            actual = result["requirements"]
            errors = [k for k, v in expected.items() if actual.get(k) != v]
            allowed = set(expected) | {"assumptions", "preference_modes"}
            if name != "search":
                errors += ["unexpected:" + k for k, v in before.items() if k not in allowed and actual[k] != v]
            if name == "confirm" and not expected:
                errors.append("missing_proposal")
            known = {f["id"]: f for f in facts_for(result, agent.get("offer_indices") or None, alternatives=agent.get("tool") == "alternatives")}
            grounded = all(f == known.get(f["id"]) for f in agent.get("facts", []))
            if not grounded or result.get("order"):
                errors.append("unsafe")
            row = {"scenario": name, "mode": verdict(result.get("parser_mode"), agent, local=local, read=read, quality=not errors),
                   "quality_ok": not errors, "failures": errors, "grounded": grounded,
                   "initial_seconds": round(initial, 3), "seconds": round(time.monotonic()-started, 3)}
            rows.append(row)
            state = result
            print(json.dumps(row), flush=True)
            (ROOT / "artifacts/connected-agent-latest.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


if __name__ == "__main__":
    results = asyncio.run(run())
    raise SystemExit(0 if all(r["quality_ok"] and r["mode"] != "fallback_or_partial" for r in results) else 1)
