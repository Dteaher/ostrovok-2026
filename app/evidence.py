"""Auditable claims made only from canonical server offers and calculations."""

from copy import deepcopy

from app.models import TripRequirements
from app.search import validate_plan


def rubles(value):
    return f"{value:,}".replace(",", " ") + " ₽"


def current_offers(state):
    req = TripRequirements.model_validate(state["requirements"])
    offers = list(state.get("plans", []))
    selected = state.get("selected_plan")
    if selected and all(p["id"] != selected["id"] for p in offers):
        offers.append(selected)
    return [p for p in offers if not validate_plan(p, req)]


def facts_for(state, indices=None, *, alternatives=False):
    offers = current_offers(state)
    if indices:
        if any(i < 1 or i > len(offers) for i in indices):
            raise ValueError("Выберите вариант из текущего списка")
        offers = [offers[i - 1] for i in dict.fromkeys(indices)]
    facts = []

    def add(code, text, source):
        facts.append({"id": code, "text": text, "source": source})

    req = state["requirements"]
    add("trip_dates", f"Заезд: {req.get('check_in') or 'ещё не указан'}; срок — {req['nights']} ночей.", {"field": "requirements.check_in,nights"})
    ages = ", ".join(str(age) for age in req["children_ages"])
    add("trip_guests", f"Гости: {req['adults']} взрослых; " + (f"детей — {len(req['children_ages'])}, возраст: {ages}." if ages else "без детей."), {"field": "requirements.adults,children_ages"})
    add("trip_transport", "Дорога: " + {"flight": "перелёт", "train": "поезд", "self": "самостоятельно, стоимость не рассчитана"}[req["transport"]] + f"; отправление — {req['origin']}.", {"field": "requirements.transport,origin"})
    if req.get("budget"):
        add("trip_budget", f"Согласованный бюджет — {rubles(req['budget'])}; " + ("на проживание." if req.get("budget_scope") == "hotel" else "на всю поездку."), {"field": "requirements.budget,budget_scope"})

    labels = {"quiet": "тишину", "pool": "бассейн", "breakfast": "завтрак", "refundable": "бесплатную отмену"}
    for field, label in labels.items():
        mentions = [i for i, item in enumerate(state.get("_preference_sources", [])) if item["values"].get(field) is True]
        if mentions and state["requirements"].get(field):
            add("preference_" + field, f"Вы указали {label}" + (" несколько раз" if len(mentions) > 1 else "") + "; это условие сохранено при подборе.",
                {"field": "requirements." + field, "dialogue_entries": mentions})

    for index, plan in enumerate(offers):
        prefix = "offer_" + str(index + 1)
        name = plan["hotel"]["name"]
        source = {"plan_id": plan["id"], "catalog_version": state.get("catalog_version")}
        add(prefix + "_price", f"«{name}»: {rubles(plan['price']['total'])} за всех гостей и весь срок; проживание — {rubles(plan['price']['hotel'])}.", source | {"field": "price"})
        add(prefix + "_beach", f"«{name}»: {plan['hotel']['beach_m']} м до пляжа по демо-каталогу.", source | {"field": "hotel.beach_m"})
        add(prefix + "_rating", f"«{name}»: рейтинг {plan['hotel']['rating']:.1f} из 10, {plan['hotel']['stars']} звёзд по демо-каталогу.", source | {"field": "hotel.rating"})
        add(prefix + "_meal", f"«{name}»: {plan['meal'].lower()}.", source | {"field": "meal"})
        add(prefix + "_cancel", f"«{name}»: {plan['policy']}", source | {"field": "policy"})
        add(prefix + "_amenities", f"«{name}»: в демо-каталоге указаны " + ", ".join(plan["hotel"]["amenities"]) + ".", source | {"field": "hotel.amenities"})
        add(prefix + "_constraints", f"«{name}»: обязательные условия текущего запроса проверены и выполнены по демо-каталогу.", source | {"field": "canonical_eligibility"})
        if plan.get("preference_matches"):
            add(prefix + "_fit", f"«{name}»: выполнены пожелания — " + "; ".join(plan["preference_matches"]) + ".", source | {"field": "preference_matches"})
        for number, compromise in enumerate(plan.get("preference_compromises", [])):
            add(prefix + "_compromise_" + str(number), f"«{name}»: компромисс — {compromise.lower()}.", source | {"field": "preference_compromises"})
        if plan["transport"]["mode"] == "self":
            add(prefix + "_exclusion", "Самостоятельная дорога и трансфер не рассчитаны и не входят в итог.", source | {"field": "transport.mode"})
    if len(offers) >= 2:
        first, second = offers[:2]
        a, b = first["hotel"]["name"], second["hotel"]["name"]
        delta = first["price"]["total"] - second["price"]["total"]
        text = f"«{a}» и «{b}»: одинаковая полная стоимость." if not delta else (
            f"«{b if delta > 0 else a}» дешевле «{a if delta > 0 else b}» на {rubles(abs(delta))}."
        )
        source = {"plan_ids": [first["id"], second["id"]], "calculation": "pairwise_difference"}
        add("comparison_price", text, source | {"field": "price.total"})
        delta = first["hotel"]["beach_m"] - second["hotel"]["beach_m"]
        if delta:
            add("comparison_beach", f"«{b if delta > 0 else a}» ближе к пляжу на {abs(delta)} м относительно «{a if delta > 0 else b}».", source | {"field": "hotel.beach_m"})
        if first["refundable"] != second["refundable"]:
            add("comparison_cancel", f"У «{a if first['refundable'] else b}» есть бесплатная отмена до срока в тарифе; у другого варианта тариф невозвратный.", source | {"field": "refundable"})
    ranking = state.get("_ranking", "balanced")
    descriptions = {
        "balanced": "Основной порядок: больше выполненных пожеланий, затем выше рейтинг, ниже полная стоимость и меньше расстояние до пляжа. В выдачу также включаем ценовую альтернативу и вариант с высоким рейтингом.",
        "price": "Сначала ниже полная стоимость; обязательные условия сохранены.",
        "beach": "Сначала меньше расстояние до пляжа; обязательные условия сохранены.",
        "rating": "Сначала выше рейтинг; обязательные условия сохранены.",
    }
    add("ranking", descriptions[ranking], {"field": "ranking_policy", "policy": ranking})
    if state["requirements"].get("budget_scope") == "hotel":
        add("budget_scope", "Ограничение бюджета относится к отелю и обязательным доплатам. Дорога показана отдельно и входит в полную стоимость поездки.", {"field": "requirements.budget_scope"})
    if state.get("diagnostic"):
        add("diagnostic", state["diagnostic"]["message"], {"field": "diagnostic"})
    if alternatives:
        from app.negotiation import proposal_facts
        facts.extend(proposal_facts(state))
    add("unknown", "Спа, вид из конкретного номера и другие отсутствующие в каталоге характеристики не подтверждены. Их нельзя считать выполненными.", {"field": "catalog_scope"})
    add("demo", "Отели, наличие, рейтинги, тарифы и транспорт демонстрационные. Реальные бронирование и оплата не выполняются.", {"field": "data_label"})
    return facts


def select_facts(facts, ids):
    mapping = {fact["id"]: fact for fact in facts}
    if not ids or len(ids) > 8 or len(set(ids)) != len(ids) or any(code not in mapping for code in ids):
        raise ValueError("Explanation references unknown or repeated evidence")
    return [deepcopy(mapping[code]) for code in ids]
