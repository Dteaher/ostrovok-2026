"""Local-first travel agent HTTP boundary."""

import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.models import (
    CheckoutRequest,
    MessageRequest,
    PatchRequest,
    SelectRequest,
    TripRequirements,
    UpdateMessageRequest,
)
from app.parser import configured_mode
from app.search import find_plan, search, validate_plan
from app.service import (
    DATA_LABEL,
    apply_patch_to_state,
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

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        logger.info("О!План ready; interpreter=%s; port=8080", configured_mode())
        yield
        database.close()

    application = FastAPI(
        title="О!План", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    application.state.db = database

    @application.middleware("http")
    async def headers_and_limits(request: Request, call_next):
        length = request.headers.get("content-length", "0")
        if length.isdigit() and int(length) > 32768:
            return JSONResponse(
                {"detail": "Запрос слишком большой. Сократите описание до 4000 символов."},
                status_code=413,
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
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

    def load(session_id: str) -> dict:
        if len(session_id) > 64:
            raise HTTPException(404, "Поездка не найдена. Начните новый подбор.")
        state = database.load(session_id)
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

    @application.post("/api/sessions")
    async def create_session(payload: MessageRequest):
        state = await process_message(new_state(), payload.message)
        database.create(state)
        logger.info("Trip created; stage=%s matches=%s", state["stage"], state["total_matches"])
        return public_state(state)

    @application.get("/api/sessions/{session_id}")
    def get_session(session_id: str):
        return public_state(load(session_id))

    @application.post("/api/sessions/{session_id}/messages")
    async def update_message(session_id: str, payload: UpdateMessageRequest):
        state = load(session_id)
        guard(state, payload.revision)
        state = await process_message(state, payload.message)
        return save(state, payload.revision)

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
        errors = validate_plan(plan, req)
        if errors:
            raise HTTPException(409, "Поездка не прошла проверку: " + "; ".join(errors))
        state.update(
            stage="selected",
            selected_plan=plan,
            hotel_intent={"id": plan["hotel"]["id"], "name": plan["hotel"]["name"]},
            request_status="idle",
            hypothetical=None,
            _hypothetical_pending=None,
            changes=[],
            assistant_message="Вы выбрали поездку. Проверьте состав и полную стоимость, затем можно оформить демонстрационный заказ.",
        )
        state["counterfactuals"] = search(req, hotel_id=hotel_id(state))["counterfactuals"]
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
