"""Deterministic offline planning with hard constraints and auditable totals."""

import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, time, timedelta
from hashlib import sha256
from itertools import combinations
from math import ceil
from zoneinfo import ZoneInfo

from app.catalog import CATALOG_VERSION, DATA_LABEL, HOTELS, HOTELS_BY_ID
from app.models import TripRequirements, is_required, search_terms

_MOSCOW = ZoneInfo("Europe/Moscow")

_RELAXATIONS = {
    "breakfast": (False, "Без обязательного завтрака"),
    "refundable": (False, "Без обязательной бесплатной отмены"),
    "pool": (False, "Без обязательного бассейна"),
    "quiet": (False, "Без обязательной тишины"),
    "direct_only": (False, "Без обязательного прямого маршрута"),
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
        if is_required(req, feature) and feature not in hotel["features"]:
            failures.append(feature)
    if is_required(req, "max_beach_m") and hotel["beach_m"] > req.max_beach_m:
        failures.append("max_beach_m")
    if is_required(req, "min_rating") and hotel["rating"] < req.min_rating:
        failures.append("min_rating")
    if is_required(req, "stars") and hotel["stars"] < req.stars:
        failures.append("stars")
    if is_required(req, "quiet") and hotel["quietness"] < 8:
        failures.append("quiet")
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
        + _digest(
            [
                CATALOG_VERSION,
                search_terms(req),
                hotel["id"],
                rate_id,
                rooms,
            ]
        )[:24]
    )
    reasons = [f"{hotel['beach_m']} м до пляжа", f"Рейтинг {hotel['rating']:.1f} из 10"]
    if req.breakfast and breakfast:
        reasons.append("Завтрак включён для всех гостей от 6 лет; до 6 лет бесплатно")
    if req.refundable and refundable:
        reasons.append("Бесплатная отмена до срока, указанного в тарифе")
    if req.quiet and hotel["quietness"] >= 8:
        reasons.insert(0, "Тихий район и спокойная территория по демо-каталогу")
    for field, label in (
        ("pets", "Размещение с питомцем учтено в цене"),
        ("pool", "Бассейн на территории"),
        ("accessible", "Адаптированный номер и безбарьерный вход"),
    ):
        if getattr(req, field) and field in hotel["features"]:
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
    preference_matches, preference_compromises = _preferences(hotel, req, breakfast, refundable)
    reasons.extend(text for text in preference_matches if text not in reasons)
    compromises.extend(text for text in preference_compromises if text not in compromises)
    score = round(
        hotel["rating"] * 10 - total / 12000 + (hotel["quietness"] * 3 if req.quiet else 0),
        3,
    )
    score += len(preference_matches) * 30
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
        "preference_matches": preference_matches,
        "preference_compromises": preference_compromises,
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


def _preferences(hotel, req, breakfast, refundable):
    conditions = {
        "breakfast": (breakfast, "Завтрак включён", "Завтрак не включён"),
        "refundable": (
            refundable,
            "Возвратный тариф",
            "Возвратный тариф недоступен в этом варианте",
        ),
        "pool": ("pool" in hotel["features"], "Бассейн на территории", "Нет бассейна"),
        "quiet": (hotel["quietness"] >= 8, "Спокойная территория", "Оживлённый район"),
        "direct_only": (True, "Прямой маршрут", "Маршрут с пересадкой"),
        "max_beach_m": (
            req.max_beach_m is None or hotel["beach_m"] <= req.max_beach_m,
            "Расстояние до пляжа в пределах пожелания",
            "До пляжа дальше желаемого",
        ),
        "min_rating": (
            hotel["rating"] >= req.min_rating,
            "Рейтинг соответствует пожеланию",
            "Рейтинг ниже желаемого",
        ),
        "stars": (
            hotel["stars"] >= req.stars,
            "Звёздность соответствует пожеланию",
            "Звёздность ниже желаемой",
        ),
    }
    matches, compromises = [], []
    for field, (satisfied, matched, missed) in conditions.items():
        if _active_requirement(req, field) and not is_required(req, field):
            (matches if satisfied else compromises).append(matched if satisfied else missed)
    return matches, compromises


def _candidates(req, *, enforce_budget=True, hotel_id=None):
    rejected = Counter()
    if errors := _input_errors(req):
        rejected.update(errors)
        return [], dict(rejected)
    plans = []
    if hotel_id is not None and hotel_id not in HOTELS_BY_ID:
        return [], {"hotel_id": 1}
    for hotel in HOTELS:
        if hotel_id is not None and hotel["id"] != hotel_id:
            continue
        if failures := _hotel_failures(hotel, req):
            rejected.update(failures)
            continue
        rooms = _occupancy(hotel, req)
        if rooms is None:
            rejected["occupancy"] += 1
            continue
        # Enumerate actual rates; a request does not silently upgrade cheaper rates.
        for breakfast in [True] if is_required(req, "breakfast") else [False, True]:
            for refundable in [True] if is_required(req, "refundable") else [False, True]:
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
    for plan in sorted(plans, key=lambda p: (-p["score"], p["price"]["total"], p["id"])):
        best.setdefault(plan["hotel"]["id"], plan)
    # A soft preference can reorder eligible options, never remove one.
    return sorted(best.values(), key=lambda p: (-p["score"], p["price"]["total"], p["id"]))


def _representative_choices(ranked, *, minimum_total=None):
    """Keep the best fit, cheapest hotel, and strongest remaining comfort option.

    Canonical plans and their score ranking stay unchanged; only the display
    selection changes. Labels live outside plans so selection and checkout can
    still retrieve and validate the exact canonical object.
    """
    if not ranked:
        return [], {}
    cheapest = min(ranked, key=lambda p: (p["price"]["total"], p["id"]))
    cheapest_label = (
        "Самая низкая цена"
        if minimum_total is None or cheapest["price"]["total"] == minimum_total
        else "Ближе к пожеланиям"
    )
    selected = [ranked[0]]
    labels = {
        ranked[0]["id"]: cheapest_label
        if ranked[0]["id"] == cheapest["id"]
        else "Ближе к пожеланиям"
    }
    if cheapest["id"] != ranked[0]["id"]:
        selected.append(cheapest)
        labels[cheapest["id"]] = cheapest_label
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


def _suggestions(req, *, hotel_id=None):
    """Verify bounded single changes, then pairs if too few singles succeed."""
    errors = _input_errors(req)
    if "check_in" in errors:
        return []
    changes = []
    if "transport_schedule" in errors:
        next_day = datetime.now(_MOSCOW).date() + timedelta(
            days=2 if req.transport == "train" else 1
        )
        changes.append(
            (
                "check_in",
                next_day.isoformat(),
                f"Перенести заселение на {next_day:%d.%m.%Y}: отправление уже прошло",
            )
        )
    if "origin" in errors:
        changes.append(
            ("transport", "self", "Самостоятельная дорога: расходы на дорогу не рассчитаны")
        )
    if "destination" in errors:
        changes.append(("destination", "Сочи", "Рассмотреть Большой Сочи — демо-каталог"))
    if "unsupported" in errors:
        changes.append(("unsupported", [], "Убрать неподдерживаемые условия"))
    if not errors:
        for field, (value, label) in _RELAXATIONS.items():
            if _active_requirement(req, field) and is_required(req, field):
                changes.append((field, value, label))

    def evaluate(patch, labels):
        updated = TripRequirements.model_validate({**req.model_dump(), **patch})
        candidates, _ = _candidates(updated, hotel_id=hotel_id)
        if not candidates:
            return None
        item = {
            "patch": patch,
            "label": "; ".join(labels) + " — только с вашего согласия",
            "total_matches": len(_distinct(candidates)),
            "min_total": min(p["price"]["total"] for p in candidates),
        }
        if len(patch) == 1:
            item["field"], item["value"] = next(iter(patch.items()))
        return item

    def budget_change(patch):
        if req.budget is None:
            return None
        updated = TripRequirements.model_validate({**req.model_dump(), **patch})
        candidates, _ = _candidates(updated, enforce_budget=False, hotel_id=hotel_id)
        if not candidates:
            return None
        minimum = min(_budget_amount(p, updated) for p in candidates)
        if minimum <= req.budget:
            return None
        return minimum, f"Увеличить бюджет до {minimum:,} ₽".replace(",", " ")

    singles = []
    if budget := budget_change({}):
        amount, label = budget
        singles.append(evaluate({"budget": amount}, [label]))
    for field, value, label in changes:
        if item := evaluate({field: value}, [label]):
            singles.append(item)
    suggestions = [item for item in singles if item]
    if len(suggestions) < 4 and not errors:
        for first, second in combinations(changes, 2):
            patch = {first[0]: first[1], second[0]: second[1]}
            if item := evaluate(patch, [first[2], second[2]]):
                suggestions.append(item)
        for field, value, label in changes:
            if budget := budget_change({field: value}):
                amount, budget_label = budget
                if item := evaluate({field: value, "budget": amount}, [label, budget_label]):
                    suggestions.append(item)
    return sorted(
        suggestions, key=lambda item: (len(item["patch"]), item["min_total"], sorted(item["patch"]))
    )[:4]


def _diagnostic(req, rejected, *, hotel_id=None):
    errors = _input_errors(req)
    if errors:
        kind = "unsupported_destination" if "destination" in errors else "unsupported_input"
        return {
            "kind": kind,
            "fields": errors,
            "message": "Условия не поддерживаются демо-каталогом Большого Сочи; уточните запрос.",
        }
    if hotel_id is not None and (
        "hotel_id" in rejected or _hotel_failures(HOTELS_BY_ID[hotel_id], req)
    ):
        return {
            "kind": "pinned_hotel_conflict",
            "hotel_id": hotel_id,
            "fields": list(rejected),
            "message": "Выбранный отель не соответствует условиям демо-каталога. Отель сохранён.",
        }
    if "budget" in rejected:
        return {
            "kind": "budget",
            "fields": ["budget"],
            "message": "Подходящие варианты демо-каталога превышают бюджет.",
        }
    if "occupancy" in rejected and not any(
        not _hotel_failures(h, req) and _occupancy(h, req) is not None
        for h in HOTELS
        if hotel_id is None or h["id"] == hotel_id
    ):
        return {
            "kind": "availability",
            "fields": ["occupancy"],
            "message": "В демо-каталоге нет доступных номеров для всех гостей на весь срок.",
        }
    return {
        "kind": "constraints",
        "fields": list(rejected),
        "message": "В демо-каталоге нет вариантов со всеми обязательными условиями.",
    }


def _counterfactuals(req, strict, *, hotel_id=None):
    if not strict:
        return []
    baseline = min(strict, key=lambda p: (p["price"]["total"], p["id"]))
    items = []
    for field, (value, label) in _RELAXATIONS.items():
        # Accessibility is never proposed as an economy lever.
        if field == "accessible" or not _active_requirement(req, field):
            continue
        relaxed = req.model_copy(update={field: value})
        alternatives, _ = _candidates(relaxed, hotel_id=hotel_id)
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


def search(requirements: TripRequirements, limit: int = 3, *, hotel_id: str | None = None) -> dict:
    plans, rejected = _candidates(requirements, hotel_id=hotel_id)
    distinct = _distinct(plans)
    ordered, labels = _representative_choices(
        distinct, minimum_total=min((p["price"]["total"] for p in plans), default=None)
    )
    displayed = ordered[: max(0, limit)]
    return {
        "plans": displayed,
        "plan_labels": {plan["id"]: labels[plan["id"]] for plan in displayed},
        "total_matches": len(distinct),
        "min_total": min((plan["price"]["total"] for plan in plans), default=None),
        "rejected": rejected,
        "diagnostic": _diagnostic(requirements, rejected, hotel_id=hotel_id)
        if not distinct
        else None,
        "suggestions": _suggestions(requirements, hotel_id=hotel_id) if not distinct else [],
        "counterfactuals": _counterfactuals(requirements, plans, hotel_id=hotel_id),
        "catalog_version": CATALOG_VERSION,
    }


def find_plan(
    requirements: TripRequirements, plan_id: str, *, hotel_id: str | None = None
) -> dict | None:
    plans, _ = _candidates(requirements, hotel_id=hotel_id)
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
        if is_required(requirements, "breakfast") and plan["meal"] != "Завтрак включён":
            errors.append("Требуется завтрак")
        if is_required(requirements, "refundable") and not plan["refundable"]:
            errors.append("Требуется возвратный тариф")
        if is_required(requirements, "direct_only") and not plan["transport"]["direct"]:
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
                "preference_matches",
                "preference_compromises",
                "score",
            ):
                if plan.get(field) != expected[field]:
                    errors.append(f"Данные варианта изменены: {field}")
    except (KeyError, TypeError, ValueError, OverflowError):
        errors.append("Повреждены данные варианта поездки")
    return list(dict.fromkeys(errors))
