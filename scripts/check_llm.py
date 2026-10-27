"""One explicit model request using the application's actual extraction path.

Run as `python scripts/check_llm.py` or `docker compose exec app python -m scripts.check_llm`.
Never prints keys, raw provider bodies, or exceptions. No search/session/order writes.
"""

import asyncio
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.llm_config import LLMConfig  # noqa: E402
from app.models import TripRequirements  # noqa: E402
from app.parser import configured_mode, extract_intent  # noqa: E402


async def check():
    load_dotenv(ROOT / ".env", override=False)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if configured_mode() != "llm":
        print(json.dumps({"ok": False, "reason": "Заполните LLM_API_KEY и LLM_MODEL в локальном .env. Ключ не присылайте в чат."}, ensure_ascii=False))
        return 2
    try:
        config = LLMConfig.from_env()
    except (ValueError, TypeError):
        print(json.dumps({"ok": False, "reason": "Проверьте адрес API, таймаут и лимит ответа в .env."}, ensure_ascii=False))
        return 2
    today = date.today()
    req = TripRequirements(destination="Сочи", check_in=today + timedelta(days=35), budget=180000)
    result = await extract_intent("Установи бюджет 160 тысяч рублей", req, today)
    success = result.mode == "llm" and result.patch.get("budget") == 160000
    # Successful mode means the provider reply passed the real extraction gates,
    # not just that the offline interpreter recognized the test budget.
    print(json.dumps({
        "ok": success, "model": config.model, "mode": result.mode,
        "reason": "API ответил, JSON и изменения прошли проверку приложения."
        if success else " ".join(result.notices) or "Не получен корректный ответ AI.",
        "note": "Это проверка подключения, не оценка качества произвольного диалога.",
    }, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check()))
