from scripts.benchmark_latency import cases, percentile, summarize


def test_benchmark_covers_forty_cases_and_percentiles_include_failures():
    assert len(cases()) == 40
    assert len({case[0] for case in cases()}) == 40
    assert percentile([2, 3, 10], .95) == 10


def test_fallback_and_local_operations_never_count_as_llm_success():
    base = {"model": "test", "llm_required": True, "llm_success": False,
            "quality_ok": True, "expected_tool": None, "tool_ok": True,
            "seconds": 10, "initial_seconds": 10, "limit_seconds": 10,
            "unsafe": False, "http_calls": [], "parser_mode": "fallback", "explanation_mode": "local"}
    rows = [base, base | {"llm_required": False, "seconds": .01},
            base | {"parser_mode": "llm", "seconds": 4, "initial_seconds": 3}]
    result = summarize(rows)["test"]
    assert result["llm_required"] == 2
    assert result["llm_successes"] == 0  # optional narration never completed
    assert result["core_llm_successes"] == 1  # extraction alone completed
    assert result["core_llm_success_pct"] == 50
    assert result["p95_full_seconds"] == 10
