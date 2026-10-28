"""Local-first travel agent HTTP boundary."""

import asyncio
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.agent_transport import provider_session, shared_provider_client
from app.destination_context import DestinationContext
from app.explanations import ExplanationJobs
from app.models import (
    CheckoutRequest,
    MessageRequest,
    PatchRequest,
    RevisionRequest,
    SelectRequest,
    TripRequirements,
    UpdateMessageRequest,
)
from app.parser import configured_mode
from app.request_budget import RequestBudget, request_seconds, run_until
from app.search import find_plan, validate_plan
from app.service import (
    DATA_LABEL,
    apply_patch_to_state,
    choose_offer,
    hotel_id,
    new_state,
    normalize_state,
    process_message,
    public_state,
)
from app.storage import Database, StaleRevision

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def create_app(db_url: str | None = None) -> FastAPI:
    database = Database(db_url or os.getenv("DB_URL", "sqlite:///data/oplan.db"))
    explanations = ExplanationJobs()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        logger.info("О!План ready; interpreter=%s; port=8080", configured_mode())
        async with provider_session() as provider, httpx.AsyncClient(
            follow_redirects=False, headers={"User-Agent": "ORIVANE/1.0 (travel demo; public-data client)"}
        ) as public_client:
            application.state.provider = provider
            application.state.destination_context = DestinationContext(public_client)
            try:
                yield
            finally:
                await explanations.close()
                await application.state.destination_context.close()
        database.close()

    application = FastAPI(
        title="О!План", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    application.state.db = database

    @application.middleware("http")
    async def headers_and_limits(request: Request, call_next):
        request.state.started = time.monotonic()
        length = request.headers.get("content-length", "0")
        if length.isdigit() and int(length) > 32768:
            return JSONResponse(
                {"detail": "Запрос слишком большой. Сократите описание до 4000 символов."},
                status_code=413,
            )
        token = shared_provider_client.set(getattr(application.state, "provider", None))
        try:
            response = await call_next(request)
        finally:
            shared_provider_client.reset(token)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-src https://www.openstreetmap.org; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/") or request.url.path == "/health":
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        messages = [str(error["msg"]).removeprefix("Value error, ") for error in exc.errors()[:3]]
        return JSONResponse(
            {"detail": "Проверьте введённые данные: " + "; ".join(messages)},
            status_code=422,
        )

    @application.exception_handler(ValidationError)
    async def invalid_requirements(request: Request, exc: ValidationError):
        messages = [str(error["msg"]).removeprefix("Value error, ") for error in exc.errors()[:3]]
        return JSONResponse(
            {"detail": "Не получилось применить условия: " + "; ".join(messages)},
            status_code=422,
        )

    @application.exception_handler(StaleRevision)
    async def stale(request: Request, exc: StaleRevision):
        return JSONResponse(
            {
                "detail": "Поездка уже изменилась в другой вкладке. Обновите данные и повторите действие."
            },
            status_code=409,
        )

    @application.exception_handler(ValueError)
    async def invalid_value(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def load(session_id: str, *, deadline=None) -> dict:
        if len(session_id) > 64:
            raise HTTPException(404, "Поездка не найдена. Начните новый подбор.")
        state = database.load(session_id, deadline=deadline)
        if state is None:
            raise HTTPException(404, "Поездка не найдена. Начните новый подбор.")
        return normalize_state(state)

    def guard(state: dict, revision: int) -> None:
        if state["revision"] != revision:
            raise StaleRevision
        if state["stage"] == "booked":
            raise HTTPException(
                409,
                "Демонстрационный заказ уже оформлен. Для другой поездки начните новый подбор.",
            )

    def save(state: dict, previous: int, order: dict | None = None) -> dict:
        state["revision"] = previous + 1
        database.save(state, expected=previous, order=order)
        explanations.start(state)
        return public_state(state)

    @application.get("/health")
    def health():
        if not database.health():
            raise HTTPException(503, "База данных пока недоступна")
        return {"status": "ok"}

    @application.get("/api/config")
    def config():
        return {
            "name": "О!План",
            "parser_mode": configured_mode(),
            "catalog_label": DATA_LABEL,
            "destinations": [
                {
                    "id": "sochi",
                    "name": "Большой Сочи",
                    "description": "От тихой Хосты до набережных Сириуса. Один регион, разные варианты отдыха.",
                    "weather": "Осенью — для прогулок. Климатическое описание ориентировочное, без прогноза; тёплое море в ноябре не обещаем.",
                    "travel": "Демонстрационный прямой перелёт из Москвы — 3 ч 50 мин; есть поезд и самостоятельная дорога.",
                }
            ],
            "examples": [
                "В Сочи с 6 ноября 2026 на неделю вдвоём, до 160 тысяч, с завтраком и прямым перелётом",
                "Тихий уикенд в Сочи с 13 ноября 2026 на 3 ночи вдвоём, до 80 тысяч, бесплатная отмена",
                "В Сочи с 20 ноября 2026 на 7 ночей, 2 взрослых и ребёнок 6 лет, с бассейном, до 180 тысяч",
            ],
        }

    @application.get("/docs", include_in_schema=False)
    def api_schema():
        # The machine-readable contract works offline and under the same CSP as
        # the main UI; no externally hosted Swagger scripts are required.
        return RedirectResponse("/openapi.json")

    async def message_response(payload, request, session_id=None):
        # Include loading, normalization, persistence and JSON encoding in the
        # same budget. Reserve a short final slice for the transactional save.
        budget = RequestBudget(request.state.started,
            request_seconds({"plans": [True]} if session_id else {}, payload.message))
        async def execute():
            if session_id:
                state = await asyncio.to_thread(load, session_id, deadline=budget.deadline)
                # Saved plans remain open to factual chat; handle_turn rejects
                # every mutation. Keep optimistic concurrency for that history.
                if state["revision"] != payload.revision:
                    raise StaleRevision
            else:
                state = new_state()
            state = await process_message(state, payload.message, budget=budget,
                response_reserve=min(.25, budget.seconds * .1))
            if session_id:
                state["revision"] = payload.revision + 1
                await asyncio.to_thread(database.save, state, expected=payload.revision,
                                        deadline=budget.deadline)
            else:
                await asyncio.to_thread(database.create, state, deadline=budget.deadline)
            explanations.start(state)
            state["response_timing"]["elapsed_seconds"] = round(time.monotonic() - budget.started, 3)
            return await asyncio.to_thread(JSONResponse, public_state(state))
        try:
            return await run_until(execute(), budget.deadline)
        except TimeoutError as exc:
            raise HTTPException(504, "Время ожидания истекло. Проверенные варианты текущей поездки сохранены. Обновите поездку и повторите запрос.") from exc

    @application.post("/api/sessions")
    async def create_session(payload: MessageRequest, request: Request):
        return await message_response(payload, request)

    @application.get("/api/sessions/{session_id}")
    def get_session(session_id: str):
        return public_state(load(session_id))

    @application.post("/api/sessions/{session_id}/messages")
    async def update_message(session_id: str, payload: UpdateMessageRequest, request: Request):
        return await message_response(payload, request, session_id)

    @application.post("/api/sessions/{session_id}/explanation")
    async def get_explanation(session_id: str, payload: RevisionRequest):
        state = await asyncio.to_thread(load, session_id)
        if state["revision"] != payload.revision:
            raise StaleRevision
        agent = await explanations.get(state)
        if (await asyncio.to_thread(load, session_id))["revision"] != payload.revision:
            raise StaleRevision
        return {"revision": payload.revision, "agent": agent}

    @application.get("/api/sessions/{session_id}/destination-context")
    async def get_destination_context(session_id: str, revision: int):
        state = await asyncio.to_thread(load, session_id)
        if state["revision"] != revision:
            raise StaleRevision
        req = TripRequirements.model_validate(state["requirements"])
        if not req.destination:
            return {"revision": revision, "status": "needs_destination", "location": None}
        try:
            async with asyncio.timeout(10):
                result = await application.state.destination_context.get(
                    req.destination, req.check_in, req.nights, req.origin)
        except TimeoutError:
            result = {"status": "unavailable", "location": None}
        if (await asyncio.to_thread(load, session_id))["revision"] != revision:
            raise StaleRevision
        return {"revision": revision, **result}

    @application.patch("/api/sessions/{session_id}/requirements")
    def update_requirements(session_id: str, payload: PatchRequest):
        state = load(session_id)
        guard(state, payload.revision)
        if not payload.patch:
            raise HTTPException(422, "Укажите хотя бы одно изменение")
        state = apply_patch_to_state(state, payload.patch)
        return save(state, payload.revision)

    @application.post("/api/sessions/{session_id}/select")
    def select_plan(session_id: str, payload: SelectRequest):
        state = load(session_id)
        guard(state, payload.revision)
        if state["stage"] not in {"results", "selected"}:
            raise HTTPException(409, "Сначала уточните условия поездки")
        if state["clarifications"]:
            raise HTTPException(409, "Сначала ответьте на уточнение — предложение может измениться")
        req = TripRequirements.model_validate(state["requirements"])
        # Selecting a different offer is explicit user consent to change hotel.
        # Automatic replans remain scoped to the retained hotel intention.
        plan = find_plan(req, payload.plan_id)
        if plan is None:
            raise HTTPException(404, "Предложение не найдено в текущих условиях. Обновите подбор.")
        try:
            choose_offer(state, plan)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return save(state, payload.revision)

    @application.post("/api/sessions/{session_id}/checkout")
    def checkout(session_id: str, payload: CheckoutRequest):
        state = load(session_id)
        if state["order"]:
            return public_state(state)  # Safe retry after a lost HTTP response.
        guard(state, payload.revision)
        if state["stage"] != "selected" or not state["selected_plan"]:
            raise HTTPException(409, "Сначала выберите поездку")
        if state["request_status"] == "needs_clarification" or state["clarifications"]:
            raise HTTPException(409, "Сначала ответьте на уточнение и проверьте состав поездки")
        req = TripRequirements.model_validate(state["requirements"])
        selected = state["selected_plan"]
        current = find_plan(req, selected["id"], hotel_id=hotel_id(state))
        if current is None or current["price"] != selected["price"]:
            raise HTTPException(409, "Условия предложения изменились. Выполните новый подбор.")
        errors = validate_plan(selected, req)
        if errors:
            raise HTTPException(409, "Оформление остановлено: " + "; ".join(errors))
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        order = {
            "id": secrets.token_urlsafe(24),
            "reference": "DEMO-" + secrets.token_hex(3).upper(),
            "status": "demo_confirmed",
            "created_at": now.isoformat(),
            "total": selected["price"]["total"],
            "currency": "RUB",
            "traveler_name": payload.traveler_name,
            "email": payload.email,
            "plan": selected,
            "notice": "Это демонстрационный заказ. Деньги не списаны, места не забронированы; письмо не отправляется.",
        }
        state.update(
            stage="booked",
            order=order,
            hypothetical=None,
            _hypothetical_pending=None,
            changes=[],
            assistant_message="Демонстрационная поездка оформлена. Номер заказа сохранён; подтверждение можно скачать. Реальной оплаты и бронирования нет.",
        )
        state["messages"].append({"role": "assistant", "content": state["assistant_message"]})
        logger.info("Simulated order confirmed; total=%s RUB", order["total"])
        try:
            return save(state, payload.revision, order)
        except StaleRevision:
            latest = load(session_id)
            if latest["order"]:
                return public_state(latest)
            raise

    application.mount(
        "/static",
        StaticFiles(directory=ROOT / "static", check_dir=False),
        name="static",
    )

    @application.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "static" / "index.html", media_type="text/html")

    @application.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(ROOT / "static" / "media" / "mark.svg", media_type="image/svg+xml")

    return application


app = create_app()
