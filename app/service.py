"""The small travel agent: extract → merge → clarify → search → validate.

Each transition produces persistent, inspectable state. Model output never
controls tools, purchases, inventory, or monetary arithmetic.
"""

import re
import secrets
import time
from copy import deepcopy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.catalog import HOTELS
from app.models import TripRequirements, search_terms
from app.parser import (
    ALLOWED_PATCH,
    NUMBER,
    ParsedIntent,
    configured_mode,
    count,
    extract_intent,
    parse_rules,
)
from app.request_budget import (
    RequestBudget,
    current_budget,
    local_only,
    request_seconds,
    run_sync,
    run_until,
)
from app.search import find_plan, search, validate_plan

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
    "preference_modes": "Обязательные условия и пожелания",
}


def local_today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def new_state() -> dict:
    return {
        "schema_version": 2,
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
        "hotel_intent": None,
        "hotel_alternative": None,
        "diagnostic": None,
        "hypothetical": None,
        "request_status": "idle",
        "order": None,
        "changes": [],
        "change_receipt": None,
        "parser_mode": configured_mode(),
        "data_label": DATA_LABEL,
        "assumptions": [],
        "_pending": {},
        "_hypothetical_pending": None,
        "_explicit": [],
        "_month_hint": None,
        "_metrics": {"turns": 0, "searches": 0, "clarifications": 0},
        "_initial_values": {},
        "_requirement_history": [],
        "_ranking": "balanced",
        "_ranking_version": 1,
        "agent": None,
    }


def public_state(state: dict) -> dict:
    return {key: value for key, value in state.items() if not key.startswith("_")} | {"ranking": state.get("_ranking", "balanced")}


def hotel_id(state: dict) -> str | None:
    return (state.get("hotel_intent") or {}).get("id")


def choose_offer(state: dict, plan: dict) -> dict:
    """One validated selection operation shared by HTTP and explicit chat intent."""
    if state.get("order") or state.get("clarifications") or state["stage"] not in {"results", "selected"}:
        raise ValueError("Сначала уточните условия поездки")
    req = TripRequirements.model_validate(state["requirements"])
    errors = validate_plan(plan, req)
    if errors:
        raise ValueError("Поездка не прошла проверку: " + "; ".join(errors))
    state.pop("_explanation", None)
    state.update(stage="selected", selected_plan=plan,
        hotel_intent={"id": plan["hotel"]["id"], "name": plan["hotel"]["name"]},
        request_status="idle", hypothetical=None, _hypothetical_pending=None,
        changes=[], change_receipt=None, agent=None,
        assistant_message="Вы выбрали поездку. Проверьте состав и полную стоимость, затем можно оформить демонстрационный заказ.")
    state["counterfactuals"] = search(req, hotel_id=hotel_id(state))["counterfactuals"]
    return state


def normalize_state(state: dict) -> dict:
    """Read older JSON sessions without trusting their historical priced offers.

    Booked orders remain historical records. Unbooked legacy choices retain the
    hotel intention and require confirmation of a freshly calculated offer.
    """
    legacy = state.get("schema_version", 1) < 2 or state.get("_ranking_version") != 1
    state.setdefault("_initial_values", {})
    state.setdefault("_requirement_history", [])
    state.setdefault("_ranking", "balanced")
    state.setdefault("agent", None)
    state.setdefault("change_receipt", None)
    state.setdefault("hotel_intent", None)
    state.setdefault("hotel_alternative", None)
    state.setdefault("diagnostic", None)
    state.setdefault("hypothetical", None)
    state.setdefault("request_status", "idle")
    state.setdefault("_hypothetical_pending", None)
    req = TripRequirements.model_validate(state["requirements"])
    state["requirements"] = req.model_dump(mode="json")
    if legacy and not state.get("order"):
        if state.get("selected_plan"):
            hotel = state["selected_plan"]["hotel"]
            state["hotel_intent"] = {"id": hotel["id"], "name": hotel["name"]}
        refresh_search(state, req)
        state["stage"] = "results" if not state.get("clarifications") else "clarify"
        state["assistant_message"] = (
            "Сохранённые условия перепроверены: выберите новое предложение "
            "с актуальной демонстрационной стоимостью."
        )
    state["schema_version"] = 2
    state["_ranking_version"] = 1
    return state


def merged_requirements(current: TripRequirements, patch: dict) -> TripRequirements:
    values = current.model_dump()
    if "preference_modes" in patch:
        # PATCH means partial update, including the priority map; validation
        # still rejects unknown fields, modes, and non-mapping payloads.
        modes = patch["preference_modes"]
        if not isinstance(modes, dict):
            raise ValueError("Приоритеты условий должны быть объектом")
        patch = patch | {"preference_modes": current.preference_modes | modes}
    return TripRequirements.model_validate(values | patch)


def refresh_search(state: dict, requirements: TripRequirements, *, retain_hotel: bool = True) -> None:
    state.pop("_explanation", None)
    state["agent"] = None
    result = search(requirements, hotel_id=hotel_id(state) if retain_hotel else None, ranking=state.get("_ranking", "balanced"))
    state["_metrics"]["searches"] += 1
    state.update(
        stage="results", selected_plan=None, change_receipt=None,
        **{key: result[key] for key in (
            "plans", "plan_labels", "total_matches", "counterfactuals", "suggestions",
            "catalog_version", "diagnostic",
        )},
    )
    state["hotel_alternative"] = None
    if hotel_id(state) and not result["plans"]:
        elsewhere = search(requirements)
        if elsewhere["total_matches"]:
            state["hotel_alternative"] = {
                "total_matches": elsewhere["total_matches"],
                "min_total": elsewhere["min_total"],
                "label": "Рассмотреть другие отели с теми же условиями",
            }


def record_reply(state: dict, message: str, user_text: str | None) -> dict:
    state["assistant_message"] = message
    if user_text:
        state["messages"].append({"role": "user", "content": user_text})
        state["_metrics"]["turns"] += 1
    state["messages"].append({"role": "assistant", "content": message})
    state["messages"] = state["messages"][-40:]
    return state


def change_summary(key: str, value, req: TripRequirements) -> str:
    label = FIELD_LABELS.get(key, key)
    if key == "preference_modes":
        return ", ".join(
            f"{FIELD_LABELS[field]} — {'желательно' if mode == 'preferred' else 'обязательно'}"
            for field, mode in value.items()
            if getattr(req, field) is not None and bool(getattr(req, field))
        ) or "приоритеты пожеланий"
    if isinstance(value, bool):
        mode = req.preference_modes.get(key, "preferred" if key == "quiet" else "required")
        return f"{label} — " + (
            "без требования" if not value else "желательно" if mode == "preferred" else "обязательно"
        )
    if key == "budget" and value is not None:
        return f"{label} — {value:,} ₽".replace(",", " ")
    if key == "children_ages":
        return f"{label} — " + (", ".join(str(age) for age in value) if value else "без детей")
    if key == "transport":
        value = {"flight": "перелёт", "train": "поезд", "self": "своим ходом"}[value]
    if key == "budget_scope":
        value = "проживание" if value == "hotel" else "вся поездка"
    return f"{label} — {value if value is not None else 'без ограничения'}"


def hypothetical_reply(state: dict, intent: ParsedIntent, user_text: str | None) -> dict:
    """Evaluate a branch without touching the live trip, pending questions or offer."""
    state["changes"] = []
    req = TripRequirements.model_validate(state["requirements"])
    branch = merged_requirements(req, intent.hypothetical_patch or {})
    if state["clarifications"]:
        state["hypothetical"] = None
        state["_hypothetical_pending"] = None
        return record_reply(state,
            "Для корректного сравнения сначала уточним текущую поездку. "
            + state["clarifications"][0]["question"] + " Условия и выбор сохранены.", user_text)
    if req.destination is None or req.check_in is None:
        return record_reply(state,
            "Для сравнения сначала опишите поездку: направление, дату заезда и состав гостей. "
            "Ваши условия пока не меняю.", user_text)
    if not intent.hypothetical_patch or intent.questions:
        state["hypothetical"] = None
        state["_hypothetical_pending"] = (
            {"patch": intent.hypothetical_patch or {}, "questions": intent.questions}
            if intent.questions else None
        )
        question = intent.questions[0]["question"] if intent.questions else (
            "Укажите, какое условие сравнить: например, «что изменится, если убрать завтрак?»"
        )
        return record_reply(state,
            "Это уточнение только для сравнения; поездку не меняю. " + question, user_text)
    state["_hypothetical_pending"] = None
    before = search(req, hotel_id=hotel_id(state))
    after = search(branch, hotel_id=hotel_id(state))
    state["hypothetical"] = {
        "patch": intent.hypothetical_patch,
        "total_matches": after["total_matches"],
        "min_total": after["min_total"],
        "baseline_min_total": before["min_total"],
        "diagnostic": after["diagnostic"],
        "hotel_id": hotel_id(state),
    }
    if after["total_matches"]:
        price = f"{after['min_total']:,}".replace(",", " ")
        message = (
            f"Проверил без изменения вашей поездки: при таком изменении доступно "
            f"{after['total_matches']} отелей, минимальная полная стоимость — {price} ₽."
        )
        if before["min_total"] is not None:
            difference = after["min_total"] - before["min_total"]
            amount = f"{abs(difference):,}".replace(",", " ")
            message += (
                f" Минимум {'выше' if difference > 0 else 'ниже'} на {amount} ₽."
                if difference else " Минимальная стоимость не изменилась."
            )
    else:
        message = "Проверил без изменения вашей поездки: " + after["diagnostic"]["message"]
    message += " Сравнение в пределах демо-каталога; это не доплата за услугу в выбранном тарифе."
    if hotel_id(state):
        message += " Сравнивал только сохранённый отель."
    if req.transport == "self":
        message += " Самостоятельная дорога не рассчитана и не входит в стоимость."
    return record_reply(state, message, user_text)


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
    normalize_state(state)
    state["agent"] = None
    if intent.hypothetical:
        return hypothetical_reply(state, intent, user_text)
    state["_hypothetical_pending"] = None
    state["hypothetical"] = None
    previous_selection = state["selected_plan"]
    previous_offer = previous_selection or (
        state["plans"][0] if state.get("hotel_intent") and state.get("plans") else None
    )
    state["change_receipt"] = None
    old = TripRequirements.model_validate(state["requirements"])
    allowed = ALLOWED_PATCH | {"unsupported"}
    if set(intent.patch) - allowed:
        raise ValueError("Неизвестное условие поездки")
    requirements = merged_requirements(old, intent.patch)
    child_question = state["_pending"].get("children_ages", {})
    expected_count = child_question.get("expected_count")
    ages = requirements.children_ages if "children_ages" in intent.patch else None
    if expected_count and ages and len(ages) != expected_count:
        explicit_count = re.search(
            rf"({NUMBER})\s*(?:дет[еьи]|реб[её]н)", (user_text or "").lower(),
        )
        if not explicit_count or count(explicit_count[1]) != len(ages):
            intent.patch = {key: value for key, value in intent.patch.items() if key != "children_ages"}
            requirements = merged_requirements(old, intent.patch)
            intent.questions = [q for q in intent.questions if q["field"] != "children_ages"] + [
                child_question | {
                    "question": f"Укажите возраст каждого из {expected_count} детей: пока известны не все возрасты.",
                    "options": [],
                },
            ]
    changed = search_terms(old) != search_terms(requirements)
    if changed:
        state["_agent_pending"] = None
        changed_fields = sorted(key for key in intent.patch if old.model_dump(mode="json")[key] != requirements.model_dump(mode="json")[key])
        values = requirements.model_dump(mode="json", exclude={"assumptions", "unsupported"})
        if not state["_requirement_history"]:
            # Defaults shown on the first trip are part of its initial state too.
            state["_initial_values"] = values
        else:
            for key in intent.patch:
                if key in values and state["_initial_values"].get(key) is None:
                    state["_initial_values"][key] = values[key]
        state["_requirement_history"].append({"before": old.model_dump(mode="json"),
                                             "after": requirements.model_dump(mode="json"), "fields": changed_fields})
        state["_requirement_history"] = state["_requirement_history"][-30:]
    if intent.release_hotel:
        state["hotel_intent"] = None
        previous_selection = None
    elif previous_selection:
        hotel = previous_selection["hotel"]
        state["hotel_intent"] = {"id": hotel["id"], "name": hotel["name"]}
    explicit = set(state["_explicit"]) | set(intent.patch)
    requirements.assumptions = assumptions_for(requirements, explicit)
    state["_explicit"] = sorted(explicit)
    state["requirements"] = requirements.model_dump(mode="json")
    if user_text and intent.recognized:
        preference_fields = {"quiet", "pool", "breakfast", "refundable", "max_beach_m", "min_rating", "stars", "preference_modes"}
        confirmed = {key: state["requirements"][key] for key in intent.patch if key in preference_fields}
        if confirmed:
            state.setdefault("_preference_sources", []).append({"values": confirmed, "message": user_text[:1000]})
            state["_preference_sources"] = state["_preference_sources"][-30:]
    state["assumptions"] = requirements.assumptions
    state["changes"] = [
        {
            "field": key,
            "label": FIELD_LABELS.get(key, key),
            "before": old.model_dump(mode="json")[key],
            "after": state["requirements"][key],
            "summary": change_summary(key, state["requirements"][key], requirements),
        }
        for key in intent.patch
        if old.model_dump(mode="json")[key] != state["requirements"][key]
    ]
    if not state["messages"] or not changed:
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
    state["request_status"] = "needs_clarification" if questions else "idle"
    if changed:
        state["selected_plan"] = None
    valid_selection = (
        previous_selection is not None
        and not changed
        and find_plan(requirements, previous_selection["id"], hotel_id=hotel_id(state))
        == previous_selection
    )
    notices = " ".join(intent.notices)
    if intent.keep_hotel and not hotel_id(state):
        state["request_status"] = "needs_clarification"
        assistant = "Сначала выберите отель из предложений — тогда смогу сохранить его при пересчёте."
        if changed:
            refresh_search(state, requirements)
    elif questions:
        if valid_selection:
            state["stage"] = "selected"
        else:
            state.update(
                stage="clarify", plans=[], plan_labels={}, total_matches=0,
                counterfactuals=[], suggestions=[], selected_plan=None,
                diagnostic=None, hotel_alternative=None,
            )
        state["_metrics"]["clarifications"] += 1
        assistant = questions[0]["question"] + " Текущие условия сохранены."
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
                + ". Сравниваю допустимые планы одного демо-каталога. Это не доплата за услугу в выбранном отеле. Экономию разных изменений нельзя складывать."
            )
            assistant += (
                " Сравнивал только сохранённый отель." if hotel_id(state)
                else " При сравнении отель может измениться."
            )
        elif intent.price_question == "direct_only":
            assistant = "В демо-каталоге нет сопоставимого маршрута с пересадкой: все рейсы прямые. Поэтому цену этого пожелания не рассчитываю и сумму не придумываю. Условия и выбранный план сохранены."
        else:
            assistant = "Для этого условия нет рассчитанного сопоставимого варианта с меньшей минимальной стоимостью в текущем сравнении. Сумму не придумываю. Условия и выбранный план сохранены."
    elif not intent.recognized and user_text:
        assistant = "Не удалось надёжно понять изменение. Напишите конкретное условие: например, «бюджет 120 тысяч», «на два дня позже» или «с собакой». Текущие условия сохранены."
    elif not changed and not intent.release_hotel and (
        valid_selection or (state["stage"] == "results" and not intent.keep_hotel)
    ):
        if valid_selection:
            state["stage"] = "selected"
        assistant = "Эти условия уже действуют. Условия поездки и ваш выбор сохранены."
    else:
        refresh_search(state, requirements)
        if state["plans"]:
            assistant = f"Нашёл {state['total_matches']} подходящих отелей; показываю {len(state['plans'])}. Проверил размещение, даты и обязательные условия. Стоимость указана за всех гостей и весь срок."
            if hotel_id(state):
                assistant = (
                    "Сохранил отель «" + state["hotel_intent"]["name"]
                    + "» и пересчитал предложение. Проверьте новую стоимость и подтвердите выбор."
                )
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
            assistant = state["diagnostic"]["message"]
            if state["suggestions"]:
                assistant += " Ниже — проверенные поиском изменения; применю только после вашего выбора."
            if state["hotel_alternative"]:
                assistant += " При тех же условиях есть другие отели. Могу показать их с вашего согласия."
    if not questions and (state.get("plans") or state.get("diagnostic")):
        from app.agent import local_presentation
        state["agent"] = local_presentation(state)
    if changed and previous_offer and state.get("plans") and not questions:
        after = state["plans"][0]
        preserved = after["hotel"]["id"] == previous_offer["hotel"]["id"]
        state["change_receipt"] = {
            "before_total": previous_offer["price"]["total"],
            "after_total": after["price"]["total"],
            "before_nights": previous_offer["dates"]["nights"],
            "after_nights": after["dates"]["nights"],
            "before_check_in": previous_offer["dates"]["check_in"],
            "after_check_in": after["dates"]["check_in"],
            "hotel_preserved": preserved,
            "hotel_name": after["hotel"]["name"],
        }
    return record_reply(state, (notices + " " + assistant).strip(), user_text)


def contextual_answer(req: TripRequirements, questions: list[dict], message: str) -> ParsedIntent | None:
    """Resolve bounded answers only against the question that actually asked them."""
    pending = {q["field"] for q in questions}
    text = message.strip().lower().replace("ё", "е")
    if "children_ages" in pending:
        text = re.sub(r"^(?:ему|ей|ребенку|сыну|дочери|младшему|младшей)\s+", "", text)
    # Only tightly bounded answers acquire context. Free text is still parsed
    # normally, so a bare number cannot silently become a budget or an age.
    if "children_ages" in pending and (
        re.fullmatch(r"\d{1,2}(?:\s*(?:,|и)\s*\d{1,2})*\s*(?:лет|год|года)", text)
        or (pending == {"children_ages"} and re.fullmatch(r"\d{1,2}(?:\s*(?:,|и)\s*\d{1,2})*", text))
    ):
        ages = [int(age) for age in re.findall(r"\d+", text)]
        child_context = next(q for q in questions if q["field"] == "children_ages")
        existing = child_context.get("existing_ages", [])
        additional = child_context.get("additional_count")
        if existing and (additional is None or len(ages) == additional):
            ages = existing + ages
        return ParsedIntent(patch={"children_ages": ages}, recognized=True)
    elif pending == {"budget"} and re.fullmatch(r"\d[\d ]{2,}", text):
        return ParsedIntent(patch={"budget": int(text.replace(" ", ""))}, recognized=True)
    elif pending == {"budget"} and re.fullmatch(
        r"(?:бюджет )?(?:тот же|оставь как есть|не меняй|без изменений)", text
    ):
        return ParsedIntent(patch={"budget": req.budget}, recognized=True)
    elif len(pending) == 1 and next(iter(pending)) in {
        "breakfast", "pool", "refundable", "quiet", "direct_only",
    } and re.fullmatch(r"обязательно|желательно|неважно|не важно|не нужно", text):
        field = next(iter(pending))
        neutral = text in {"неважно", "не важно", "не нужно"}
        return ParsedIntent(patch={
            field: not neutral,
            "preference_modes": req.preference_modes | {
                field: "preferred" if text == "желательно" else "required",
            },
        }, recognized=True)
    return None


async def process_message(state: dict, message: str, *, budget=None, response_reserve=0) -> dict:
    # The timer starts before parsing, normalization or catalogue work.
    budget = budget or RequestBudget(time.monotonic(), request_seconds(state, message))
    started = budget.started
    token = current_budget.set(budget)
    working = deepcopy(state)
    working.pop("_explanation", None)
    fallback = None
    async def execute():
        nonlocal fallback
        from app.agent import handle_turn, local_decision
        if configured_mode() == "llm":
            if local_decision(state, message) is None:
                fallback = await run_sync(_offline_result, deepcopy(state), message)
            else:
                offline_token = local_only.set(True)
                try:
                    fallback = await handle_turn(deepcopy(state), message)
                finally:
                    local_only.reset(offline_token)
        return await _process_message(working, message)
    try:
        result = await run_until(execute(), budget.deadline - response_reserve)
        result["response_timing"] = {"limit_seconds": budget.seconds,
            "elapsed_seconds": round(time.monotonic() - started, 3), "timed_out": False}
        return result
    except TimeoutError:
        # Interrupted state transitions are rolled back. Previously verified
        # results remain available, even when a detached search worker finishes.
        result = deepcopy(fallback if fallback is not None else state)
        result.pop("_explanation", None)
        text = "AI не успел ответить за отведённое время."
        text += (" Показаны условия, распознанные локально; проверьте их перед выбором."
                 if fallback is not None else " Условия поездки сохранены.")
        if result.get("plans"):
            text += " Доступные проверенные варианты показаны ниже; можно выбрать их или повторить запрос."
        else:
            text += " Повторите запрос или задайте условия через форму."
        if result.get("agent"):
            result["agent"].update(mode="local", notice=text, explanation_status="timeout")
        result["parser_mode"] = "fallback"
        result["response_timing"] = {"limit_seconds": budget.seconds,
            "elapsed_seconds": round(time.monotonic() - started, 3), "timed_out": True}
        return record_reply(result, text, message)
    finally:
        current_budget.reset(token)


def _offline_result(state, message):
    normalize_state(state)
    req = TripRequirements.model_validate(state["requirements"])
    rules = contextual_answer(req, state["clarifications"], message)
    if rules is None:
        rules = parse_rules(message, req, today=local_today())
    if not rules.recognized or state.get("_hypothetical_pending"):
        return None
    return compile_state(state, rules, user_text=message)


async def _process_message(state: dict, message: str) -> dict:
    await run_sync(normalize_state, state)
    from app.agent import enrich_results, handle_turn
    handled = await handle_turn(state, message)
    if handled is not None:
        return handled
    if state.get("order"):
        return record_reply(state, "Сохранённый план не изменён. Задайте вопрос о датах, гостях, цене или составе поездки; для новых условий начните другой подбор.", message)
    state["agent"] = None
    req = TripRequirements.model_validate(state["requirements"])
    branch = state.get("_hypothetical_pending")
    if branch and not state["clarifications"]:
        answer = contextual_answer(req, branch["questions"], message)
        contextual = answer is not None
        if answer is None:
            answer = parse_rules(message, merged_requirements(req, branch["patch"]), today=local_today())
        fields = {q["field"] for q in branch["questions"]}
        if answer.hypothetical:
            return await run_sync(compile_state, state, answer, user_text=message)
        if fields.intersection(answer.patch):
            questions = []
            child_question = next(
                (q for q in branch["questions"] if q["field"] == "children_ages"), {},
            )
            expected = child_question.get("expected_count")
            existing = child_question.get("existing_ages", [])
            ages = answer.patch.get("children_ages")
            if not contextual and existing and ages and (
                child_question.get("additional_count") is None
                or len(ages) == child_question["additional_count"]
            ):
                answer.patch["children_ages"] = existing + ages
            if expected and len(answer.patch.get("children_ages", [])) != expected:
                questions = branch["questions"]
            intent = ParsedIntent(
                hypothetical=True, recognized=True, questions=questions,
                hypothetical_patch=branch["patch"] | answer.patch,
            )
            return await run_sync(compile_state, state, intent, user_text=message)
        if not answer.recognized:
            return await run_sync(compile_state, state, ParsedIntent(
                hypothetical=True, recognized=True,
                hypothetical_patch=branch["patch"], questions=branch["questions"],
            ), user_text=message)
    intent = contextual_answer(req, state["clarifications"], message)
    if intent is None:
        intent = await extract_intent(message, req, local_today())
    if branch and not state["clarifications"] and not intent.recognized:
        # An unrecognized acknowledgement must not lose the scope of a pending
        # what-if answer and turn its next age/budget into a live edit.
        intent = ParsedIntent(
            hypothetical=True, recognized=True,
            hypothetical_patch=branch["patch"], questions=branch["questions"],
        )
    result = await run_sync(compile_state, state, intent, user_text=message)
    if not intent.recognized:
        return result
    return await enrich_results(result, message)


def apply_patch_to_state(state: dict, patch: dict) -> dict:
    return compile_state(
        state,
        ParsedIntent(patch=patch, recognized=True, mode=state["parser_mode"]),
        user_text="Изменено: " + ", ".join(FIELD_LABELS.get(key, key) for key in patch),
    )
