"""Deterministic offline planning with hard constraints and auditable totals."""

import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, time, timedelta
from hashlib import sha256
from math import ceil
from zoneinfo import ZoneInfo

from app.catalog import CATALOG_VERSION, DATA_LABEL, HOTELS, HOTELS_BY_ID
from app.models import TripRequirements

_MOSCOW = ZoneInfo("Europe/Moscow")

_RELAXATIONS = {
    "breakfast": (False, "Без обязательного завтрака"),
    "refundable": (False, "Невозвратный тариф"),
    "pets": (False, "Поездка без питомца"),
    "pool": (False, "Без обязательного бассейна"),
    "accessible": (False, "Без требования адаптированного номера"),
    "max_beach_m": (None, "Без ограничения расстояния до пляжа"),
    "min_rating": (0, "Без минимального рейтинга"),
    "stars": (0, "Без ограничения по звёздам"),
}


def _digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _destination_matches(hotel, destination):
    value = (destination or "").strip().casefold().replace("ё", "е")
    if value in {"сочи", "большой сочи", "sochi", "greater sochi"}:
        return True
    aliases = {
        "центр сочи": "сочи центр",
        "центр": "сочи центр",
        "лазаревский": "лазаревское",
    }
    return hotel["area"].casefold() == aliases.get(value, value)


def _outbound_departure(req):
    day = req.check_in - timedelta(days=1) if req.transport == "train" else req.check_in
    return datetime.combine(day, time(9) if req.transport == "train" else time(6, 30))


def _cancellation_cutoff(req):
    return datetime.combine(req.check_in - timedelta(days=3), time(14))


def _input_errors(req):
    errors = []
    if not req.destination or not any(_destination_matches(h, req.destination) for h in HOTELS):
        errors.append("destination")
    if req.check_in is None or req.check_in < datetime.now(_MOSCOW).date():
        errors.append("check_in")
    if req.transport != "self" and req.origin.strip().casefold() not in {
        "москва",
        "moscow",
    }:
        errors.append("origin")
    if (
        req.check_in is not None
        and req.transport != "self"
        and _outbound_departure(req).replace(tzinfo=_MOSCOW) <= datetime.now(_MOSCOW)
    ):
        errors.append("transport_schedule")
    if req.unsupported:
        errors.append("unsupported")
    return errors


def _hotel_failures(hotel, req):
    failures = []
    if not _destination_matches(hotel, req.destination):
        failures.append("destination")
    for feature in ("pets", "pool", "accessible"):
        if getattr(req, feature) and feature not in hotel["features"]:
            failures.append(feature)
    if req.max_beach_m is not None and hotel["beach_m"] > req.max_beach_m:
        failures.append("max_beach_m")
    if hotel["rating"] < req.min_rating:
        failures.append("min_rating")
    if hotel["stars"] < req.stars:
        failures.append("stars")
    return failures


def _occupancy(hotel, req):
    guests = req.adults + len(req.children_ages)
    rooms = ceil(guests / hotel["capacity"])
    if rooms > req.adults:
        return None  # Each booked room must contain an adult.
    available = min(
        hotel["inventory"]
        - int(
            _digest([hotel["id"], (req.check_in + timedelta(days=i)).isoformat()])[:2],
            16,
        )
        % 3
        for i in range(req.nights)
    )
    return rooms if rooms <= available else None


def _transport(req, hotel):
    check_out = req.check_in + timedelta(days=req.nights)

    def at(day, hour, minute=0):
        return datetime.combine(day, time(hour, minute))

    passengers = req.adults + len(req.children_ages)
    vehicles = ceil(passengers / 4)
    if req.transport == "self":
        trip = {
            "mode": "self",
            "title": "Самостоятельная дорога",
            "departure": at(req.check_in, 14).isoformat(),
            "arrival": at(req.check_in, 14).isoformat(),
            "return_departure": at(check_out, 12).isoformat(),
            "duration_minutes": 0,
            "direct": True,
        }
        return trip, {"title": "Самостоятельно до отеля", "minutes": 0, "price": 0}, 0
    flight = req.transport == "flight"
    departure = _outbound_departure(req)
    duration = 230 if flight else 1500
    arrival = departure + timedelta(minutes=duration)
    return_departure = at(check_out, 19, 30) if flight else at(check_out, 18)
    seasonal = 1800 if req.check_in.month in {6, 7, 8} else 0
    per_adult = (13800 + seasonal) if flight else (7600 + seasonal // 2)
    # Two-way fares: children <2 fly without a separate seat; older children 80%.
    fare = req.adults * per_adult
    for age in req.children_ages:
        fare += per_adult // 10 if flight and age < 2 else per_adult * 4 // 5
    transfer_price = vehicles * (1800 + hotel["transfer_minutes"] * 20)
    trip = {
        "mode": req.transport,
        "title": "Демо · Москва → Сочи → Москва, прямой рейс"
        if flight
        else "Демо · Москва → Адлер → Москва, прямой поезд",
        "departure": departure.isoformat(),
        "arrival": arrival.isoformat(),
        "return_departure": return_departure.isoformat(),
        "duration_minutes": duration,
        "direct": True,
    }
    transfer = {
        "title": "Индивидуальный трансфер туда и обратно",
        "minutes": hotel["transfer_minutes"],
        "price": transfer_price,
    }
    return trip, transfer, fare


def _hotel_price(hotel, req, rooms, breakfast, refundable):
    total = 0
    for offset in range(req.nights):
        day = req.check_in + timedelta(days=offset)
        season = 125 if day.month in {6, 7, 8} else 110 if day.month in {5, 9} else 85
        weekend = 110 if day.weekday() in {4, 5} else 100
        nightly = hotel["nightly_rate"] * season * weekend // 10000
        total += nightly * rooms
    # All persons beyond double occupancy have a fixed extra bed charge.
    total += max(0, req.adults + len(req.children_ages) - rooms * 2) * 650 * req.nights
    if breakfast:
        breakfast_guests = req.adults + sum(age >= 6 for age in req.children_ages)
        total += breakfast_guests * 600 * req.nights
    if refundable:
        total = ceil(total * 110 / 100)
    return total


def _plan(hotel, req, rooms, breakfast, refundable):
    check_out = req.check_in + timedelta(days=req.nights)
    transport, transfer, transport_price = _transport(req, hotel)
    hotel_price = _hotel_price(hotel, req, rooms, breakfast, refundable)
    extras = 500 * req.nights if req.pets else 0
    total = hotel_price + transport_price + transfer["price"] + extras
    rate_id = f"{'breakfast' if breakfast else 'room'}-{'flex' if refundable else 'fixed'}"
    plan_id = (
        "plan_"
        + _digest([CATALOG_VERSION, req.model_dump(mode="json"), hotel["id"], rate_id, rooms])[:24]
    )
    reasons = [f"{hotel['beach_m']} м до пляжа", f"Рейтинг {hotel['rating']:.1f} из 10"]
    if req.breakfast:
        reasons.append("Завтрак включён для всех гостей от 6 лет; до 6 лет бесплатно")
    if req.refundable:
        reasons.append("Бесплатная отмена до срока, указанного в тарифе")
    if req.quiet and hotel["quietness"] >= 8:
        reasons.insert(0, "Тихий район и спокойная территория по демо-каталогу")
    for field, label in (
        ("pets", "Размещение с питомцем учтено в цене"),
        ("pool", "Бассейн на территории"),
        ("accessible", "Адаптированный номер и безбарьерный вход"),
    ):
        if getattr(req, field):
            reasons.append(label)
    compromises = []
    if not breakfast:
        compromises.append("Питание не включено")
    if not refundable:
        compromises.append("Невозвратный тариф")
    if hotel["beach_m"] > 500:
        compromises.append(f"До пляжа около {ceil(hotel['beach_m'] / 75)} минут пешком")
    if hotel["quietness"] < 8:
        compromises.append("Оживлённый район; абсолютная тишина не гарантирована")
    if rooms > 1:
        compromises.append(f"Нужно {rooms} номера; соседние номера не гарантированы")
    warnings = [
        DATA_LABEL,
        "Цены указаны за всех гостей и весь срок. Обеды, ужины и личные расходы не включены.",
    ]
    if req.budget_scope == "hotel":
        warnings.append(
            "Бюджет проверен для проживания с обязательными доплатами; общая стоимость поездки показана отдельно."
        )
    if req.transport == "self":
        warnings.append(
            "Стоимость и время самостоятельной дороги не оценены: транспорт и трансфер — 0 ₽, расходы на дорогу сверх итога."
        )
    else:
        warnings.append(
            "Билеты и трансфер рассчитаны в обе стороны; расписание вымышленное, часовой пояс — Москва."
        )
    arrival = datetime.fromisoformat(transport["arrival"]) + timedelta(
        minutes=transfer["minutes"]
        + (45 if req.transport == "flight" else 15 if req.transport == "train" else 0)
    )
    checkin = datetime.combine(req.check_in, time(14))
    if arrival < checkin:
        warnings.append(
            f"Прибытие к отелю около {arrival:%H:%M}, заселение с 14:00. Раннее заселение не включено; хранение багажа нужно уточнить."
        )
    timeline = []
    if req.transport != "self":
        timeline.extend(
            [
                {
                    "time": transport["departure"],
                    "title": "Выезд из Москвы",
                    "detail": transport["title"],
                },
                {
                    "time": transport["arrival"],
                    "title": "Прибытие в Сочи",
                    "detail": "Получение багажа и встреча с водителем"
                    if req.transport == "flight"
                    else "Встреча у вокзала Адлера",
                },
                {
                    "time": arrival.isoformat(),
                    "title": "Прибытие к отелю",
                    "detail": f"Трансфер {transfer['minutes']} мин; раннее заселение не гарантировано",
                },
            ]
        )
    timeline.append(
        {
            "time": max(checkin, arrival).isoformat(),
            "title": "Заселение",
            "detail": f"{hotel['name']} · {rooms} ном. · с 14:00",
        }
    )
    timeline.append(
        {
            "time": datetime.combine(check_out, time(12)).isoformat(),
            "title": "Выезд из отеля",
            "detail": "Освободить номера до 12:00; хранение багажа нужно уточнить",
        }
    )
    if req.transport != "self":
        return_time = datetime.fromisoformat(transport["return_departure"])
        leave = return_time - timedelta(
            minutes=transfer["minutes"] + (120 if req.transport == "flight" else 45)
        )
        timeline.extend(
            [
                {
                    "time": leave.isoformat(),
                    "title": "Обратный трансфер",
                    "detail": "Включён в общую стоимость; ожидание после выезда — вне номера",
                },
                {
                    "time": return_time.isoformat(),
                    "title": "Обратная дорога",
                    "detail": transport["title"],
                },
                {
                    "time": (
                        return_time + timedelta(minutes=transport["duration_minutes"])
                    ).isoformat(),
                    "title": "Прибытие в Москву",
                    "detail": "Завершение поездки по демо-расписанию",
                },
            ]
        )
    cancel_until = _cancellation_cutoff(req).isoformat()
    public_hotel = {
        key: deepcopy(hotel[key])
        for key in (
            "id",
            "name",
            "area",
            "stars",
            "rating",
            "beach_m",
            "description",
            "amenities",
            "features",
        )
    }
    score = round(
        hotel["rating"] * 10 - total / 12000 + (hotel["quietness"] * 3 if req.quiet else 0),
        3,
    )
    return {
        "id": plan_id,
        "hotel": public_hotel,
        "room": {
            "name": "Семейный номер"
            if hotel["capacity"] == 4
            else "Стандарт с дополнительным местом",
            "rooms": rooms,
            "capacity": hotel["capacity"],
        },
        "rate_id": rate_id,
        "meal": "Завтрак включён" if breakfast else "Без питания",
        "refundable": refundable,
        "transport": transport,
        "transfer": transfer,
        "dates": {
            "check_in": req.check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "nights": req.nights,
        },
        "guests": {"adults": req.adults, "children_ages": list(req.children_ages)},
        "price": {
            "hotel": hotel_price,
            "transport": transport_price,
            "transfer": transfer["price"],
            "extras": extras,
            "total": total,
            "currency": "RUB",
        },
        "reasons": reasons,
        "compromises": compromises,
        "warnings": warnings,
        "score": score,
        "policy": f"Бесплатная отмена до {cancel_until.replace('T', ' ')} (Москва); после — стоимость проживания."
        if refundable
        else "При отмене или незаезде удерживается вся стоимость проживания.",
        "timeline": timeline,
        "data_label": DATA_LABEL,
    }


def _budget_amount(plan, req):
    price = plan["price"]
    return price["hotel"] + price["extras"] if req.budget_scope == "hotel" else price["total"]


def _candidates(req, *, enforce_budget=True):
    rejected = Counter()
    if errors := _input_errors(req):
        rejected.update(errors)
        return [], dict(rejected)
    plans = []
    for hotel in HOTELS:
        if failures := _hotel_failures(hotel, req):
            rejected.update(failures)
            continue
        rooms = _occupancy(hotel, req)
        if rooms is None:
            rejected["occupancy"] += 1
            continue
        # Enumerate actual rates; a request does not silently upgrade cheaper rates.
        for breakfast in [True] if req.breakfast else [False, True]:
            for refundable in [True] if req.refundable else [False, True]:
                if refundable and _cancellation_cutoff(req).replace(tzinfo=_MOSCOW) <= datetime.now(
                    _MOSCOW
                ):
                    rejected["refundable"] += 1
                    continue
                plan = _plan(hotel, req, rooms, breakfast, refundable)
                budget_price = _budget_amount(plan, req)
                if enforce_budget and req.budget is not None and budget_price > req.budget:
                    rejected["budget"] += 1
                else:
                    plans.append(plan)
    return plans, dict(rejected)


def _distinct(plans):
    best = {}
    for plan in sorted(plans, key=lambda p: (p["price"]["total"], p["id"])):
        best.setdefault(plan["hotel"]["id"], plan)
    # A soft preference can reorder eligible options, never remove one.
    return sorted(best.values(), key=lambda p: (-p["score"], p["price"]["total"], p["id"]))


def _representative_choices(ranked):
    """Keep the best fit, cheapest hotel, and strongest remaining comfort option.

    Canonical plans and their score ranking stay unchanged; only the display
    selection changes. Labels live outside plans so selection and checkout can
    still retrieve and validate the exact canonical object.
    """
    if not ranked:
        return [], {}
    cheapest = min(ranked, key=lambda p: (p["price"]["total"], p["id"]))
    selected = [ranked[0]]
    labels = {
        ranked[0]["id"]: "Самая низкая цена"
        if ranked[0]["id"] == cheapest["id"]
        else "Ближе к пожеланиям"
    }
    if cheapest["id"] != ranked[0]["id"]:
        selected.append(cheapest)
        labels[cheapest["id"]] = "Самая низкая цена"
    selected_ids = {plan["id"] for plan in selected}
    remaining = [plan for plan in ranked if plan["id"] not in selected_ids]
    if remaining:
        comfort = min(
            remaining,
            key=lambda p: (
                -p["hotel"]["rating"],
                -p["hotel"]["stars"],
                -p["score"],
                p["price"]["total"],
                p["id"],
            ),
        )
        selected.append(comfort)
        selected_ids.add(comfort["id"])
        labels[comfort["id"]] = "Высокий рейтинг"
    for plan in ranked:
        if plan["id"] not in selected_ids:
            labels[plan["id"]] = (
                "Ближе к пожеланиям" if len(selected) < 3 else "Другой подходящий вариант"
            )
            selected.append(plan)
            selected_ids.add(plan["id"])
    return selected, labels


def _active_requirement(req, field):
    value = getattr(req, field)
    return value is not None if field == "max_beach_m" else bool(value)


def _suggestions(req):
    errors = _input_errors(req)
    if "origin" in errors:
        return [
            {
                "field": "transport",
                "value": "self",
                "label": "Самостоятельная дорога: для этого города демо-маршрута нет; расходы на дорогу не рассчитаны",
            }
        ]
    if "destination" in errors:
        return [
            {
                "field": "destination",
                "value": "Сочи",
                "label": "Рассмотреть Большой Сочи — доступный демо-каталог",
            }
        ]
    if "transport_schedule" in errors and "check_in" not in errors:
        next_day = datetime.now(_MOSCOW).date() + timedelta(
            days=2 if req.transport == "train" else 1
        )
        return [
            {
                "field": "check_in",
                "value": next_day.isoformat(),
                "label": f"Перенести заселение на {next_day:%d.%m.%Y}: отправление по прежней дате уже прошло",
            }
        ]
    if "check_in" in errors:
        return []  # Clarifications collect an explicit future date.
    if "unsupported" in errors:
        return [
            {
                "field": "unsupported",
                "value": [],
                "label": "Убрать неподдерживаемые условия (только с вашего согласия)",
            }
        ]
    suggestions = []
    without_budget, _ = _candidates(req, enforce_budget=False)
    if without_budget and req.budget is not None:
        key = "hotel" if req.budget_scope == "hotel" else "total"
        cheapest = min(_budget_amount(p, req) for p in without_budget)
        if cheapest > req.budget:
            suggestions.append(
                {
                    "field": "budget",
                    "value": cheapest,
                    "label": f"Увеличить бюджет до {cheapest:,} ₽ за {'отель' if key == 'hotel' else 'поездку'}".replace(
                        ",", " "
                    ),
                }
            )
    for field, (value, label) in _RELAXATIONS.items():
        if not _active_requirement(req, field):
            continue
        relaxed = req.model_copy(update={field: value})
        if _candidates(relaxed)[0]:
            suggestions.append(
                {
                    "field": field,
                    "value": value,
                    "label": label + " — только с вашего согласия",
                }
            )
    return suggestions[:4]


def _counterfactuals(req, strict):
    if not strict:
        return []
    baseline = min(strict, key=lambda p: (p["price"]["total"], p["id"]))
    items = []
    for field, (value, label) in _RELAXATIONS.items():
        # Accessibility is never proposed as an economy lever.
        if field == "accessible" or not _active_requirement(req, field):
            continue
        relaxed = req.model_copy(update={field: value})
        alternatives, _ = _candidates(relaxed)
        if not alternatives:
            continue
        alternative = min(alternatives, key=lambda p: (p["price"]["total"], p["id"]))
        saving = baseline["price"]["total"] - alternative["price"]["total"]
        if saving > 0:
            items.append(
                {
                    "field": field,
                    "value": value,
                    "label": label,
                    "saving": saving,
                    "baseline_total": baseline["price"]["total"],
                    "alternative_total": alternative["price"]["total"],
                    "alternative_plan_id": alternative["id"],
                    "note": "Сравнение с самым дешёвым вариантом при исходных условиях и том же составе расходов. Меняется только одно условие; экономию разных вариантов нельзя складывать. Применяется только после вашего согласия.",
                }
            )
    return sorted(items, key=lambda item: (-item["saving"], item["field"]))[:3]


def search(requirements: TripRequirements, limit: int = 3) -> dict:
    plans, rejected = _candidates(requirements)
    distinct = _distinct(plans)
    ordered, labels = _representative_choices(distinct)
    displayed = ordered[: max(0, limit)]
    return {
        "plans": displayed,
        "plan_labels": {plan["id"]: labels[plan["id"]] for plan in displayed},
        "total_matches": len(distinct),
        "rejected": rejected,
        "suggestions": _suggestions(requirements) if not distinct else [],
        "counterfactuals": _counterfactuals(requirements, plans),
        "catalog_version": CATALOG_VERSION,
    }


def find_plan(requirements: TripRequirements, plan_id: str) -> dict | None:
    plans, _ = _candidates(requirements)
    return next((plan for plan in plans if plan["id"] == plan_id), None)


def validate_plan(plan: dict, requirements: TripRequirements) -> list[str]:
    """Recheck supplied state against immutable inventory, requirements and pricing.

    Never trust a browser's hotel attributes, price, ID, or itinerary. Validation
    enumerates eligible tariff state again, independently of the display limit.
    """
    errors = []
    try:
        if _input_errors(requirements):
            return ["Условия поездки неполны или не поддерживаются демо-каталогом"]
        hotel = HOTELS_BY_ID.get(plan["hotel"]["id"])
        if hotel is None:
            return ["Отеля нет в каталоге"]
        if _hotel_failures(hotel, requirements):
            errors.append("Отель не соответствует обязательным условиям")
        rooms = plan["room"]["rooms"]
        guests = requirements.adults + len(requirements.children_ages)
        if (
            type(rooms) is not int
            or rooms < 1
            or rooms > requirements.adults
            or rooms * hotel["capacity"] < guests
        ):
            errors.append("Вместимость или состав номеров не соответствует гостям")
        if rooms != _occupancy(hotel, requirements):
            errors.append("Номера недоступны на весь срок")
        if requirements.breakfast and plan["meal"] != "Завтрак включён":
            errors.append("Требуется завтрак")
        if requirements.refundable and not plan["refundable"]:
            errors.append("Требуется возвратный тариф")
        if requirements.direct_only and not plan["transport"]["direct"]:
            errors.append("Требуется прямой маршрут")
        expected_out = requirements.check_in + timedelta(days=requirements.nights)
        if plan["dates"] != {
            "check_in": requirements.check_in.isoformat(),
            "check_out": expected_out.isoformat(),
            "nights": requirements.nights,
        }:
            errors.append("Даты проживания не соответствуют запросу")
        if plan["guests"] != {
            "adults": requirements.adults,
            "children_ages": requirements.children_ages,
        }:
            errors.append("Состав гостей не соответствует запросу")
        price = plan["price"]
        keys = ("hotel", "transport", "transfer", "extras", "total")
        if (
            any(type(price[k]) is not int or price[k] < 0 for k in keys)
            or price["currency"] != "RUB"
        ):
            errors.append("Некорректная цена")
        if price["total"] != sum(price[k] for k in keys[:-1]):
            errors.append("Общая стоимость не сходится")
        if (
            requirements.budget is not None
            and _budget_amount(plan, requirements) > requirements.budget
        ):
            errors.append("Стоимость превышает бюджет")
        departure = datetime.fromisoformat(plan["transport"]["departure"])
        arrival = datetime.fromisoformat(plan["transport"]["arrival"])
        return_departure = datetime.fromisoformat(plan["transport"]["return_departure"])
        if (
            arrival - departure != timedelta(minutes=plan["transport"]["duration_minutes"])
            or arrival.date() != requirements.check_in
            or return_departure.date() != expected_out
            or return_departure <= arrival
        ):
            errors.append("Расписание транспорта не согласовано с проживанием")
        expected = find_plan(requirements, plan["id"])
        if expected is None:
            errors.append("Вариант или тариф больше не соответствует условиям")
        else:
            for field in (
                "hotel",
                "room",
                "rate_id",
                "meal",
                "refundable",
                "transport",
                "transfer",
                "dates",
                "guests",
                "price",
                "policy",
                "timeline",
                "data_label",
                "warnings",
                "reasons",
                "compromises",
                "score",
            ):
                if plan.get(field) != expected[field]:
                    errors.append(f"Данные варианта изменены: {field}")
    except (KeyError, TypeError, ValueError, OverflowError):
        errors.append("Повреждены данные варианта поездки")
    return list(dict.fromkeys(errors))
