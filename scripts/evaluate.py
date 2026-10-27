"""Reproducible end-to-end evaluation against the running HTTP application.

Uses only the standard library. The cases assert traveler-visible behavior,
including refusal/clarification; a low price alone does not count as success.
"""

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def run(base: str) -> dict:
    day = (datetime.now(ZoneInfo("Europe/Moscow")).date() + timedelta(days=35)).isoformat()

    def call(path, data, method="POST"):
        request = urllib.request.Request(
            base + path,
            data=json.dumps(data, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    cases = [
        (
            "Полная поездка",
            f"В Сочи с {day} на неделю вдвоём до 160 тысяч, с завтраком",
            "results",
            {"breakfast": True, "adults": 2},
        ),
        (
            "Семья",
            f"В Сочи с {day}, 2 взрослых и дети 5 и 9 лет, до 200 тысяч, нужен бассейн",
            "results",
            {"children_ages": [5, 9], "pool": True},
        ),
        ("Без известного возраста", f"В Сочи с {day} с ребёнком", "clarify", {}),
        ("Неизвестное направление", f"В Прагу с {day} на 5 ночей", "clarify", {}),
        ("Идея без даты", "Хочу на море на неделю вдвоем до 140 тысяч", "clarify", {}),
        (
            "Самостоятельная дорога",
            f"В Хосту с {day}, едем на своей машине, с собакой, до 90 тысяч",
            "results",
            {"transport": "self", "pets": True},
        ),
        (
            "Отрицания",
            f"В Сочи с {day}, без завтрака, без бесплатной отмены",
            "results",
            {"breakfast": False, "refundable": False},
        ),
        ("Невозможный бюджет", f"В Сочи с {day}, до 1000 рублей", "empty", {"budget": 1000}),
        ("Неподдерживаемый аэропорт", f"В Сочи из Новосибирска с {day}, до 150 тысяч", "empty", {}),
        (
            "Недоступная характеристика",
            f"В Сочи с {day}, только для взрослых, с завтраком",
            "clarify",
            {},
        ),
        (
            "Условия доступности",
            f"В Сочи с {day}, нужна безбарьерная среда, с завтраком",
            "results",
            {"accessible": True},
        ),
        (
            "Сочи не тёплое море",
            f"Хочу в Сочи с {day}, обязательно тёплое море для купания",
            "clarify",
            {},
        ),
    ]
    results, durations = [], []
    booked = 0
    for title, message, stage, expected in cases:
        started = time.perf_counter()
        try:
            state = call("/api/sessions", {"message": message})
            milliseconds = round((time.perf_counter() - started) * 1000, 2)
            durations.append(milliseconds)
            actual = (
                "empty" if state["stage"] == "results" and not state["plans"] else state["stage"]
            )
            assert actual == stage, f"expected {stage}, got {actual}"
            for field, value in expected.items():
                assert state["requirements"][field] == value, f"wrong {field}"
            if state["plans"]:
                for plan in state["plans"]:
                    p = plan["price"]
                    assert p["total"] == p["hotel"] + p["transport"] + p["transfer"] + p["extras"]
                # Each accepted case reaches an actual persisted demo order.
                state = call(
                    f"/api/sessions/{state['id']}/select",
                    {
                        "revision": state["revision"],
                        "plan_id": state["plans"][0]["id"],
                    },
                )
                state = call(
                    f"/api/sessions/{state['id']}/checkout",
                    {
                        "revision": state["revision"],
                        "accept_demo": True,
                        "traveler_name": "Демо путешественник",
                        "email": "demo@example.com",
                    },
                )
                assert state["order"]["status"] == "demo_confirmed"
                booked += 1
            results.append(
                {"case": title, "passed": True, "outcome": actual, "response_ms": milliseconds}
            )
        except (AssertionError, urllib.error.URLError, KeyError) as exc:
            results.append({"case": title, "passed": False, "error": str(exc)})
    ordered = sorted(durations)
    return {
        "generated_at": datetime.now(ZoneInfo("Europe/Moscow")).isoformat(),
        "catalog": "sochi-demo-v1",
        "parser": "configured application mode",
        "cases": len(cases),
        "passed": sum(case["passed"] for case in results),
        "demo_orders_completed": booked,
        "median_response_ms": round(statistics.median(durations), 2) if durations else None,
        "p95_response_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        if ordered
        else None,
        "note": "Small authored regression set, not an estimate of open-domain language accuracy. Latency excludes external LLM calls if no key is configured.",
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", default="artifacts/evaluation.json")
    args = parser.parse_args()
    report = run(args.url.rstrip("/"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "results"},
            ensure_ascii=False,
            indent=2,
        )
    )
    for case in report["results"]:
        if not case["passed"]:
            print(case)
    raise SystemExit(0 if report["passed"] == report["cases"] else 1)
