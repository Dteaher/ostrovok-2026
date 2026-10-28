"""One monotonic budget shared by every stage of a user turn."""

import asyncio
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from functools import partial


@dataclass(frozen=True)
class RequestBudget:
    started: float
    seconds: float

    @property
    def deadline(self):
        return self.started + self.seconds


current_budget: ContextVar[RequestBudget | None] = ContextVar("request_budget", default=None)
local_only: ContextVar[bool] = ContextVar("local_only", default=False)


def request_seconds(state, message):
    text = message.lower()
    if re.search(r"покажи.*друг|другие отели|предложи.*альтернатив|какие.*альтернатив", text):
        return 20
    if state.get("plans") and re.search(r"пересобер|пересобрать|перепланир|перестро", text):
        return 15
    # Multiple explicit dimensions of an existing trip constitute a rebuild.
    dimensions = sum(bool(re.search(pattern, text)) for pattern in (
        r"дат|заезд|январ|феврал|март|апрел|ма[йяе]|июн|июл|август|сентябр|октябр|ноябр|декабр", r"ноч|длитель|сократ|недел",
        r"бюджет|тысяч|тыщ", r"взросл|ребен|ребён|гост|детей",
    ))
    return 15 if state.get("plans") and dimensions >= 2 else 10


def deadline_or(seconds):
    budget = current_budget.get()
    return budget.deadline if budget else time.monotonic() + seconds


async def run_sync(function, *args, **kwargs):
    """Keep catalogue work cancellable without blocking the HTTP event loop.

    Callers use a detached working state: a cancelled thread can never publish
    changes to the live trip or the database.
    """
    if current_budget.get() is None:
        return function(*args, **kwargs)
    return await asyncio.to_thread(partial(function, *args, **kwargs))


async def run_until(coroutine, deadline):
    """Return at the deadline even if a provider takes time to close its socket.

    Detached work has no write authority. Cancellation cleanup may continue,
    but it cannot extend the user-visible wait or publish a late result.
    """
    if deadline <= time.monotonic():
        coroutine.close()
        raise TimeoutError("Request deadline reached")
    task = asyncio.create_task(coroutine)
    try:
        done, _ = await asyncio.wait({task}, timeout=max(0, deadline - time.monotonic()))
        if task not in done:
            raise TimeoutError("Request deadline reached")
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
