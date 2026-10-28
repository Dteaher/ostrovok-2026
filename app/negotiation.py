"""Bounded counterfactual exploration; proposals never mutate the live trip."""
from copy import deepcopy
from datetime import timedelta

from app.models import TripRequirements
from app.search import search


def explore(state):
    req = TripRequirements.model_validate(state["requirements"])
    scope = (state.get("hotel_intent") or {}).get("id")
    candidates = [(s["patch"], s["label"]) for s in state.get("suggestions", [])[:4]]
    if req.check_in and not state.get("clarifications"):
        candidates += [({"check_in": (req.check_in + timedelta(days=d)).isoformat()}, f"Сдвинуть заезд на {d} дн.") for d in (1, 3)]
        if req.nights > 1:
            candidates.append(({"nights": req.nights - 1}, f"Сократить поездку до {req.nights - 1} ночей"))
    results, seen = [], set()
    for patch, label in candidates[:7]:
        signature = repr(sorted(patch.items()))
        if signature in seen:
            continue
        seen.add(signature)
        # Never propose removing unrepresented/unsupported wishes, pets or accessibility.
        if set(patch) & {"unsupported", "pets", "accessible", "adults", "children_ages"}:
            continue
        if set(patch) & set(state.get("_agent_locks", [])):
            continue
        branch = TripRequirements.model_validate(req.model_dump() | patch)
        checked = search(branch, hotel_id=scope)
        if not checked["total_matches"]:
            continue
        results.append({"patch": deepcopy(patch), "label": label,
                        "total_matches": checked["total_matches"], "min_total": checked["min_total"],
                        "changes": {k: {"before": state["requirements"].get(k), "after": v} for k, v in patch.items()}})
    return results[:7]


def proposal_facts(state):
    labels = {"check_in": "Заезд", "nights": "Ночей", "budget": "Бюджет", "breakfast": "Завтрак",
              "pool": "Бассейн", "stars": "Звёздность", "max_beach_m": "До пляжа, м",
              "refundable": "Бесплатная отмена", "min_rating": "Минимальный рейтинг",
              "destination": "Направление", "transport": "Дорога", "direct_only": "Прямой маршрут"}
    def display(value):
        if isinstance(value, bool):
            return "да" if value else "нет"
        if value is None:
            return "без ограничения"
        if isinstance(value, str) and len(value) == 10 and value[4] == "-":
            return ".".join(reversed(value.split("-")))
        return str(value)

    proposals = explore(state)
    state["_agent_proposals"] = {"requirements": deepcopy(state["requirements"]),
                                 "hotel_intent": deepcopy(state.get("hotel_intent")), "items": proposals}
    return [{"id": f"alternative_{i}",
             "text": f"{p['label']}: {p['total_matches']} отелей, полная стоимость от {p['min_total']:,} ₽ за всех и весь срок. Меняются только: " +
                     "; ".join(f"{labels.get(k, k)}: {display(v['before'])} → {display(v['after'])}" for k, v in p["changes"].items()) + ". Только после вашего согласия.",
             "source": {"field": "verified_alternative", "patch": deepcopy(p["patch"])}}
            for i, p in enumerate(proposals)]


def actions_for(facts):
    return [{"label": "Применить: " + f["text"].split(": ")[0],
             "message": "Подтверждаю компромисс " + str(int(f["id"].split("_")[1]) + 1)}
            for f in facts if f["id"].startswith("alternative_")][:3]
