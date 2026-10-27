"""The small travel agent: extract → merge → clarify → search → validate.

Each transition produces persistent, inspectable state. Model output never
controls tools, purchases, inventory, or monetary arithmetic.
"""

import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.catalog import HOTELS
from app.models import TripRequirements
from app.parser import ALLOWED_PATCH, ParsedIntent, configured_mode, extract_intent
from app.search import search

DATA_LABEL = "Демонстрационные отели, цены и расписания. Реальное бронирование не выполняется."
FIELD_LABELS = {
    "destination": "Направление",
    "origin": "Выезд из",
    "check_in": "Заезд",
    "nights": "Ночей",
    "adults": "Взрослых",
    "children_ages": "Возраст детей",
    "budget": "Бюджет",
    "transport": "Транспорт",
    "direct_only": "Без пересадок",
    "breakfast": "Завтрак",
    "refundable": "Бесплатная отмена",
    "pets": "С питомцем",
    "pool": "Бассейн",
    "quiet": "Тихое место",
    "accessible": "Безбарьерная среда",
    "max_beach_m": "До пляжа, м",
    "min_rating": "Рейтинг от",
    "stars": "Звёзд от",
    "unsupported": "Неподтверждённые пожелания",
    "budget_scope": "На что бюджет",
}


def local_today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def new_state() -> dict:
    return {
        "id": secrets.token_urlsafe(32),
        "revision": 1,
        "stage": "clarify",
        "requirements": TripRequirements().model_dump(mode="json"),
        "messages": [],
        "assistant_message": "",
        "clarifications": [],
        "plans": [],
        "plan_labels": {},
        "total_matches": 0,
        "counterfactuals": [],
        "suggestions": [],
        "selected_plan": None,
        "order": None,
        "changes": [],
        "parser_mode": configured_mode(),
        "data_label": DATA_LABEL,
        "assumptions": [],
        "_pending": {},
        "_explicit": [],
        "_month_hint": None,
        "_metrics": {"turns": 0, "searches": 0, "clarifications": 0},
    }


def public_state(state: dict) -> dict:
    return {key: value for key, value in state.items() if not key.startswith("_")}


def proposed_dates(month_hint: int | None, today: date) -> list[dict]:
    if month_hint:
        year = today.year + (month_hint < today.month)
        first = date(year, month_hint, 1)
        if first <= today:
            first = today + timedelta(days=3) if month_hint == today.month else first
    else:
        first = today + timedelta(days=7)
    friday = first + timedelta(days=(4 - first.weekday()) % 7)
    return [
        {"label": day.strftime("%d.%m.%Y"), "value": day.isoformat()}
        for day in (friday + timedelta(days=7 * n) for n in range(3))
    ]


def assumptions_for(req: TripRequirements, explicit: set[str]) -> list[str]:
    assumptions = []
    if "adults" not in explicit:
        assumptions.append("Пока считаю на двоих взрослых.")
    if "nights" not in explicit:
        assumptions.append("Пока считаю 7 ночей.")
    if req.transport != "self" and "origin" not in explicit:
        assumptions.append("Выезд из Москвы; напишите другой город, если нужно.")
    if "transport" not in explicit:
        assumptions.append("В расчёт включены авиабилеты туда и обратно и трансфер.")
    if req.budget is None:
        assumptions.append("Бюджет пока не ограничен.")
    if req.transport == "self":
        assumptions.append(
            "Добираетесь самостоятельно. Дорога и расходы на неё не включены в расчёт."
        )
    if req.budget_scope == "hotel":
        assumptions.append(
            "Указанный бюджет проверяю только на проживание; полную стоимость показываю отдельно."
        )
    return assumptions


def compile_state(state: dict, intent: ParsedIntent, *, user_text: str | None = None) -> dict:
    old = TripRequirements.model_validate(state["requirements"])
    allowed = ALLOWED_PATCH | {"unsupported"}
    if set(intent.patch) - allowed:
        raise ValueError("Неизвестное условие поездки")
    requirements = TripRequirements.model_validate(old.model_dump() | intent.patch)
    explicit = set(state["_explicit"]) | set(intent.patch)
    requirements.assumptions = assumptions_for(requirements, explicit)
    state["_explicit"] = sorted(explicit)
    state["requirements"] = requirements.model_dump(mode="json")
    state["assumptions"] = requirements.assumptions
    state["changes"] = [
        {
            "field": key,
            "label": FIELD_LABELS.get(key, key),
            "before": old.model_dump(mode="json")[key],
            "after": state["requirements"][key],
        }
        for key in intent.patch
        if old.model_dump(mode="json")[key] != state["requirements"][key]
    ]
    if not state["messages"]:
        state["changes"] = []
    if intent.month_hint:
        state["_month_hint"] = intent.month_hint
    pending = state["_pending"]
    for field in intent.patch:
        pending.pop(field, None)
    for question in intent.questions:
        pending[question["field"]] = question
    questions = list(pending.values())
    today = local_today()
    supported_destinations = {"Сочи", "Большой Сочи"} | {hotel["area"] for hotel in HOTELS}
    if requirements.destination not in supported_destinations:
        if requirements.destination:
            question = f"В демонстрационном каталоге пока только Большой Сочи. Для {requirements.destination} предложений нет. Посмотреть Сочи?"
        else:
            question = "Предлагаю Большой Сочи: море, прогулки и разные районы для отдыха. В демо подробно покрыта эта локация. Рассмотрим её?"
        questions.insert(
            0,
            {
                "field": "destination",
                "question": question,
                "options": [{"label": "Посмотреть Большой Сочи", "value": "Сочи"}],
            },
        )
    if requirements.check_in is None or requirements.check_in < today:
        questions.append(
            {
                "field": "check_in",
                "question": "Когда хотите заехать? Выберите дату или напишите свою."
                if requirements.check_in is None
                else "Эта дата уже прошла. Выберите новый заезд.",
                "options": proposed_dates(state.get("_month_hint"), today),
            }
        )
    if requirements.unsupported:
        sea_note = (
            " Сочи в ноябре подойдёт для прогулок; тёплое море не обещаю."
            if "тёплое море для купания" in requirements.unsupported
            else ""
        )
        questions.insert(
            0,
            {
                "field": "unsupported",
                "question": "Не могу подтвердить в этом каталоге: "
                + ", ".join(requirements.unsupported)
                + "."
                + sea_note
                + " Продолжить без этих обязательных условий?",
                "options": [{"label": "Продолжить без этих условий", "value": []}],
            },
        )
    state["clarifications"] = questions
    state["parser_mode"] = intent.mode
    if user_text:
        state["messages"].append({"role": "user", "content": user_text})
        state["_metrics"]["turns"] += 1
    if state["changes"]:
        state["selected_plan"] = None
    notices = " ".join(intent.notices)
    if questions:
        state.update(
            stage="clarify",
            plans=[],
            plan_labels={},
            total_matches=0,
            counterfactuals=[],
            suggestions=[],
            selected_plan=None,
        )
        state["_metrics"]["clarifications"] += 1
        assistant = "Уточним условия ниже, чтобы не выбрать неподходящий вариант. Остальные пожелания сохранены."
    elif intent.price_question:
        comparison = next(
            (item for item in state["counterfactuals"] if item["field"] == intent.price_question),
            None,
        )
        if comparison:

            def rubles(amount):
                return f"{amount:,}".replace(",", " ") + " ₽"

            assistant = (
                "При текущих условиях минимальная стоимость поездки — "
                + rubles(comparison["baseline_total"])
                + ". Если изменить только это условие («"
                + comparison["label"]
                + "»), минимальная стоимость — "
                + rubles(comparison["alternative_total"])
                + ". Разница — "
                + rubles(comparison["saving"])
                + ". Сравниваю допустимые планы одного демо-каталога: отель может измениться. Это не доплата за услугу в выбранном отеле. Экономию разных изменений нельзя складывать."
            )
        elif intent.price_question == "direct_only":
            assistant = "В демо-каталоге нет сопоставимого маршрута с пересадкой: все рейсы прямые. Поэтому цену этого пожелания не рассчитываю и сумму не придумываю. Условия и выбранный план сохранены."
        else:
            assistant = "Для этого условия нет рассчитанного сопоставимого варианта с меньшей минимальной стоимостью в текущем сравнении. Сумму не придумываю. Условия и выбранный план сохранены."
    elif not intent.recognized and user_text:
        assistant = "Не удалось надёжно понять изменение. Напишите конкретное условие: например, «бюджет 120 тысяч», «на два дня позже» или «с собакой». Текущие условия сохранены."
    else:
        result = search(requirements)
        state["_metrics"]["searches"] += 1
        state.update(
            stage="results",
            selected_plan=None,
            **{
                key: result[key]
                for key in ("plans", "total_matches", "counterfactuals", "suggestions")
            },
        )
        state["catalog_version"] = result["catalog_version"]
        state["plan_labels"] = result.get("plan_labels", {})
        if result["plans"]:
            assistant = f"Нашёл {len(result['plans'])} варианта для вашей поездки. Проверил размещение, даты и обязательные условия. Стоимость указана за всех гостей и весь срок."
            assistant += (
                " Самостоятельная дорога не рассчитана и не входит в сумму."
                if requirements.transport == "self"
                else " Дорога туда и обратно и трансфер включены."
            )
            if requirements.budget_scope == "hotel":
                assistant += (
                    " Бюджет применён к отелю; транспорт показан отдельно в полной стоимости."
                )
            if state["changes"] and len(state["messages"]) > 1:
                assistant = "Пересобрал поездку. Остальные условия сохранил. " + assistant
        else:
            assistant = "Точных совпадений нет. Не стал нарушать ваши условия. Можно изменить одно из условий ниже — пересчитаю после вашего выбора."
    state["assistant_message"] = (notices + " " + assistant).strip()
    state["messages"].append({"role": "assistant", "content": state["assistant_message"]})
    state["messages"] = state["messages"][-40:]
    return state


async def process_message(state: dict, message: str) -> dict:
    req = TripRequirements.model_validate(state["requirements"])
    intent = await extract_intent(message, req, local_today())
    return compile_state(state, intent, user_text=message)


def apply_patch_to_state(state: dict, patch: dict) -> dict:
    return compile_state(
        state,
        ParsedIntent(patch=patch, recognized=True, mode=state["parser_mode"]),
        user_text="Изменено: " + ", ".join(FIELD_LABELS.get(key, key) for key in patch),
    )
