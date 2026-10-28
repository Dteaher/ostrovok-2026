"""Explicit paid paired benchmark; no credentials, prompts or raw responses in reports."""

import argparse
import asyncio
import json
import logging
import math
import os
import sys
import time
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent import local_decision  # noqa: E402
from app.agent_transport import provider_session, shared_provider_client  # noqa: E402
from app.evidence import facts_for  # noqa: E402
from app.explanations import explain_snapshot  # noqa: E402
from app.parser import ParsedIntent  # noqa: E402
from app.request_budget import request_seconds  # noqa: E402
from app.service import compile_state, local_today, new_state, process_message  # noqa: E402


def cases():
    day = local_today() + timedelta(days=55)
    return [
        ("typo_budget", "бюджэт 140 тыщ, осталное не трогай", {"budget": 140000}, None),
        ("words_budget", "по деньгам потолок сто пятьдесят тысяч рублей за всё", {"budget": 150000}, None),
        ("short_budget", "максимум 180к за всю поездку", {"budget": 180000}, None),
        ("budget_edit", "Теперь бюджет 200 тысяч", {"budget": 200000}, None),
        ("pet_casual", "пёс едет с нами, нужен отель куда пустят с ним", {"pets": True}, None),
        ("cat_casual", "хотим взять с собой кошку, нужен подходящий отель", {"pets": True}, None),
        ("child_age", "нас двое взрослых и мелкому 6 лет", {"adults": 2, "children_ages": [6]}, None),
        ("two_children", "едем с двумя детьми, им 4 и 9 лет", {"children_ages": [4, 9]}, None),
        ("adults", "теперь нас трое взрослых", {"adults": 3}, None),
        ("infant", "с нами ребёнок 0 лет", {"children_ages": [0]}, None),
        ("breakfast_soft", "с завтраками было бы кайф, но если без них сильно дешевле — переживу", {"breakfast": True, "preference_modes": {"breakfast": "preferred"}}, None),
        ("breakfast_required", "завтрак обязателен", {"breakfast": True}, None),
        ("breakfast_remove", "завтрак не нужен", {"breakfast": False}, None),
        ("pool", "нужен отель с бассейном", {"pool": True}, None),
        ("quiet", "хочу тихий отель, тишина желательна", {"quiet": True}, None),
        ("refund", "нужна бесплатная отмена", {"refundable": True}, None),
        ("date_edit", f"Перенеси заезд на {(day + timedelta(days=2)).isoformat()}", {"check_in": (day + timedelta(days=2)).isoformat()}, None),
        ("duration", "Сократи поездку до 5 ночей", {"nights": 5}, None),
        ("rebuild", f"Перенеси заезд на {(day + timedelta(days=3)).isoformat()}, на 5 ночей, бюджет 250 тысяч", {"check_in": (day + timedelta(days=3)).isoformat(), "nights": 5, "budget": 250000}, None),
        ("adults_budget", "Теперь трое взрослых, бюджет 300 тысяч", {"adults": 3, "budget": 300000}, None),
        ("initial_search", f"В Сочи с {day.isoformat()} на 7 ночей, двое взрослых, бюджет 300 тысяч", {"destination": "Сочи", "check_in": day.isoformat(), "nights": 7, "adults": 2, "budget": 300000}, None),
        ("whatif", "Что изменится, если убрать завтрак? Пока ничего не меняй", {}, None),
        ("explain", "Объясни, почему рекомендованы эти варианты", {}, "explain"),
        ("why", "Почему эти варианты?", {}, "explain"),
        ("justify", "Обоснуй рекомендацию", {}, "explain"),
        ("compare", "Сравни первый и второй отель", {}, "compare"),
        ("difference", "Чем отличаются эти отели?", {}, "compare"),
        ("compare_price", "Сравни варианты по цене и расстоянию до моря", {}, "compare"),
        ("details_first", "Расскажи подробнее про первый отель", {}, "details"),
        ("details_second", "Расскажи подробнее про второй отель", {}, "details"),
        ("spa", "Есть ли в отеле спа?", {}, "details"),
        ("kids_club", "Есть ли в отеле детский клуб?", {}, "details"),
        ("included", "Что включено?", {}, "details"),
        ("cancellation", "Что известно про отмену?", {}, "details"),
        ("alternatives", "Предложи альтернативы", {}, "alternatives"),
        ("other_hotels", "Покажи другие отели", {}, "alternatives"),
        ("local_pet", "Добавь собаку", {"pets": True}, None),
        ("local_restore", "Верни первоначальные даты", {}, "restore"),
        ("local_select", "Выбери второй вариант", {}, "select_offer"),
        ("local_checkout", "Оформи поездку", {}, "prepare_checkout"),
    ]


def fixture():
    return compile_state(new_state(), ParsedIntent(recognized=True, patch={
        "destination": "Сочи", "check_in": (local_today() + timedelta(days=55)).isoformat(),
        "nights": 7, "adults": 2, "budget": 500000, "breakfast": True,
    }))


def percentile(values, q):
    return round(sorted(values)[max(0, math.ceil(len(values) * q) - 1)], 3) if values else None


def summarize(rows):
    summary = {}
    for model in dict.fromkeys(row["model"] for row in rows):
        group = [r for r in rows if r["model"] == model]
        eligible = [r for r in group if r["llm_required"]]
        successful = [r for r in eligible if r["llm_success"]]
        core = [r for r in eligible if r["quality_ok"] and (
            r["explanation_mode"] == "llm" if r["expected_tool"] else r["parser_mode"] == "llm")]
        tools = [r for r in group if r["expected_tool"]]
        summary[model] = {
            "requests": len(group), "llm_required": len(eligible),
            "llm_successes": len(successful),
            "llm_success_pct": round(100 * len(successful) / len(eligible), 2) if eligible else 0,
            "core_llm_successes": len(core),
            "core_llm_success_pct": round(100 * len(core) / len(eligible), 2) if eligible else 0,
            "parser_llm_successes": sum(r["parser_mode"] == "llm" and r["quality_ok"] and not r["expected_tool"] for r in eligible),
            "narration_llm_successes": sum(r["explanation_mode"] == "llm" and r["quality_ok"] for r in eligible),
            "quality_passes": sum(r["quality_ok"] for r in group),
            "tool_correct": sum(r["tool_ok"] for r in tools), "tool_cases": len(tools),
            "tool_accuracy_pct": round(100 * sum(r["tool_ok"] for r in tools) / len(tools), 2) if tools else None,
            "p50_full_seconds": percentile([r["seconds"] for r in eligible], .5),
            "p95_full_seconds": percentile([r["seconds"] for r in eligible], .95),
            "p50_llm_success_seconds": percentile([r["seconds"] for r in successful], .5),
            "p95_llm_success_seconds": percentile([r["seconds"] for r in successful], .95),
            "p50_initial_results_seconds": percentile([r["initial_seconds"] for r in eligible], .5),
            "p95_initial_results_seconds": percentile([r["initial_seconds"] for r in eligible], .95),
            "unsafe_changes": sum(r["unsafe"] for r in group),
            "deadline_overruns": sum(r["seconds"] > r["limit_seconds"] + .25 for r in group),
            "http_calls": sum(len(r["http_calls"]) for r in group),
        }
    return summary


async def measure(model, case):
    name, message, expected, tool = case
    state = new_state() if name == "initial_search" else fixture()
    before = deepcopy(state)
    local = name.startswith("local_") or name == "whatif"
    row = {"model": model, "case": name, "limit_seconds": request_seconds(state, message),
           "llm_required": not local, "expected_tool": tool, "http_calls": []}
    real_client = httpx.AsyncClient
    pool = shared_provider_client.get()
    pool_post = pool.post if pool is not None else None

    async def observed_post(*args, **kwargs):
        call = {}
        row["http_calls"].append(call)
        started = time.monotonic()
        try:
            response = await pool_post(*args, **kwargs)
            call["http"] = response.status_code
            return response
        except (httpx.HTTPError, asyncio.CancelledError) as exc:
            call["error_type"] = type(exc).__name__
            raise
        finally:
            call["seconds"] = round(time.monotonic() - started, 3)

    class ObservedClient(real_client):
        async def post(self, *args, **kwargs):
            call = {}
            row["http_calls"].append(call)
            started = time.monotonic()
            try:
                response = await super().post(*args, **kwargs)
                call["http"] = response.status_code
                return response
            except (httpx.HTTPError, asyncio.CancelledError) as exc:
                call["error_type"] = type(exc).__name__
                raise
            finally:
                call["seconds"] = round(time.monotonic() - started, 3)

    started = time.monotonic()
    observer = patch.object(pool, "post", observed_post) if pool is not None else nullcontext()
    with patch.dict(os.environ, {"LLM_MODEL": model, "TRAVEL_MODE": "connected", "AGENT_ENABLED": "1"}), patch("httpx.AsyncClient", ObservedClient), observer:
        result = await process_message(state, message)
        row["initial_seconds"] = round(time.monotonic() - started, 3)
        parser_ok = result.get("parser_mode") == "llm"
        narration_ok = False
        if result.get("_explanation"):
            agent = await explain_snapshot(deepcopy(result))
            result["agent"] = agent
            narration_ok = agent["mode"] == "llm"
        elif (result.get("agent") or {}).get("mode") == "llm":
            narration_ok = True
    row["seconds"] = round(time.monotonic() - started, 3)
    row["parser_mode"] = result.get("parser_mode")
    row["explanation_mode"] = (result.get("agent") or {}).get("mode")
    row["timed_out"] = result.get("response_timing", {}).get("timed_out", False) or (result.get("agent") or {}).get("explanation_status") == "timeout"
    actual = result["requirements"]
    failures = []
    for key, value in expected.items():
        if key == "preference_modes":
            if any(actual[key].get(k) != v for k, v in value.items()):
                failures.append(key)
        elif actual[key] != value:
            failures.append(key)
    allowed = set(expected) | {"assumptions"} | ({"preference_modes"} if any(k in expected for k in ("breakfast", "pets", "pool", "quiet", "refundable")) else set())
    unexpected = [k for k in before["requirements"] if k not in allowed and actual[k] != before["requirements"][k]]
    known = {f["id"]: f for f in facts_for(result, (result.get("agent") or {}).get("offer_indices") or None,
                                          alternatives=(result.get("agent") or {}).get("tool") == "alternatives")}
    facts_ok = all(f == known.get(f["id"]) for f in (result.get("agent") or {}).get("facts", []))
    actual_tool = (result.get("agent") or {}).get("tool")
    if tool in {"restore", "select_offer", "prepare_checkout"}:
        actual_tool = local_decision(before, message).tool
    row["tool_ok"] = tool is None or actual_tool == tool
    row["unsafe"] = bool(unexpected or not facts_ok or result.get("order"))
    row["quality_ok"] = not failures and not row["unsafe"] and row["tool_ok"]
    row["failures"] = failures + ["unrequested:" + key for key in unexpected] + ([] if facts_ok else ["ungrounded_facts"])
    # Read tools need narration; edits need successful extraction AND narration
    # whenever requested. A correct local fallback never satisfies this flag.
    row["llm_success"] = not local and row["quality_ok"] and not row["timed_out"] and (
        narration_ok if tool else parser_ok and (narration_ok if result.get("_explanation") else True))
    return row


async def run(output, models, selected=None):
    load_dotenv(ROOT / ".env")
    async with provider_session():
        return await run_with_pool(output, models, selected)


async def run_with_pool(output, models, selected=None):
    load_dotenv(ROOT / ".env")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("app.parser").setLevel(logging.ERROR)
    rows = []
    report = {"generated_at": datetime.now(ZoneInfo("Europe/Moscow")).isoformat(),
        "method": "40 diverse synthetic user turns per model; paired sequential runs, alternating model order. Production parser, tools, deadlines and evidence validation. No API/DB persistence. Nearest-rank percentiles; full latency includes timeouts/fallback, LLM-success percentiles exclude failures. Local operations excluded from LLM denominator. This is not an SLA, independent load test or exhaustive semantic evaluation.", "results": rows}
    for index, case in enumerate(c for c in cases() if selected is None or c[0] in selected):
        for model in models if index % 2 == 0 else list(reversed(models)):
            row = await measure(model, case)
            rows.append(row)
            report["summary"] = summarize(rows)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: row[k] for k in ("model", "case", "seconds", "llm_success", "quality_ok")}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/haiku-luna-latency-40.json")
    parser.add_argument("--models", nargs="+", default=["claude-haiku-5-5", "gpt-5.6-luna"])
    parser.add_argument("--cases", nargs="+")
    args = parser.parse_args()
    asyncio.run(run(args.output, args.models, args.cases))
