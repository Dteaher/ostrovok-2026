"""Ephemeral narration jobs: no database writes, no authority over trip state."""

import asyncio
import time
from copy import deepcopy

from app.agent import presentation
from app.request_budget import RequestBudget, current_budget, run_until


def unavailable(state, status="timeout"):
    agent = deepcopy(state.get("agent"))
    if agent:
        agent.update(mode="local", explanation_status=status,
            notice="Персональное AI-объяснение не успело загрузиться. Показаны проверенные факты и доступные варианты.")
    return agent


async def explain_snapshot(state):
    spec = state["_explanation"]
    if spec["deadline"] <= time.monotonic():
        return unavailable(state)
    # The deadline belongs to the original user turn, not this later HTTP call.
    token = current_budget.set(RequestBudget(spec["deadline"], 0))
    try:
        result = await run_until(presentation(state, spec["message"], spec["tool"],
            indices=spec["indices"], deadline=spec["deadline"], defer=False), spec["deadline"])
        if state.get("agent", {}).get("requested"):
            result["requested"] = True
        if result["mode"] != "llm":
            result["explanation_status"] = "unavailable"
        return result
    except TimeoutError:
        return unavailable(state)
    finally:
        current_budget.reset(token)


class ExplanationJobs:
    def __init__(self):
        self.jobs = {}
        self.expires = {}
        self.loop = None

    def start(self, state):
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            # Synchronous PATCH/select endpoints run in FastAPI's thread pool.
            if self.loop is not None:
                self.loop.call_soon_threadsafe(self.start, deepcopy(state))
            return
        key = (state["id"], state["revision"])
        for old, task in list(self.jobs.items()):
            if (old[0] == key[0] and old != key) or self.expires[old] < time.monotonic():
                if not task.done():
                    task.cancel()
                del self.jobs[old]
                del self.expires[old]
        if state.get("_explanation") and key not in self.jobs and len(self.jobs) < 256:
            self.jobs[key] = asyncio.create_task(explain_snapshot(deepcopy(state)))
            self.expires[key] = state["_explanation"]["deadline"] + 30

    async def get(self, state):
        task = self.jobs.get((state["id"], state["revision"]))
        if task is None or task.cancelled():
            # A process restart, expired job, or stale page never starts a new
            # paid generation with a fresh budget.
            return unavailable(state)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                return unavailable(state)
            raise

    async def close(self):
        for task in self.jobs.values():
            task.cancel()
        await asyncio.gather(*self.jobs.values(), return_exceptions=True)
        self.jobs.clear()
        self.expires.clear()
