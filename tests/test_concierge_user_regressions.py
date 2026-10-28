"""User-reported concierge regressions: commands address the actual visible trip."""
import asyncio
from copy import deepcopy

import pytest

from app.agent import handle_turn
from app.service import choose_offer, process_message
from tests.test_agent_tools import ready


def test_composite_sort_applies_required_breakfast_and_preserves_other_conditions():
    state = ready(breakfast=False, pets=True)
    before = deepcopy(state['requirements'])
    result = asyncio.run(process_message(state, 'Сначала покажи дешевле, но завтрак обязателен'))
    assert result['requirements']['breakfast'] is True
    assert result['requirements']['preference_modes'].get('breakfast', 'required') == 'required'
    assert result['_ranking'] == 'price'
    assert result['requirements']['pets'] == before['pets']
    assert result['requirements']['budget'] == before['budget']
    assert result['plans']
    prices = [p['price']['total'] for p in result['plans']]
    assert prices == sorted(prices)


@pytest.mark.parametrize('message,indices', [
    ('Сравни второй и третий', [2, 3]),
    ('Сравни 3 и 1', [3, 1]),
    ('Сравни варианты 2 и 3', [2, 3]),
])
def test_compare_explicit_displayed_indices(message, indices):
    state = ready()
    before = deepcopy(state['requirements'])
    expected_ids = [state['plans'][i - 1]['id'] for i in indices]
    result = asyncio.run(handle_turn(state, message))
    assert result['agent']['offer_indices'] == indices
    price = next(f for f in result['agent']['facts'] if f['id'] == 'comparison_price')
    assert price['source']['plan_ids'] == expected_ids
    assert result['requirements'] == before


def test_compare_by_current_hotel_names():
    state = ready()
    first, second = state['plans'][2], state['plans'][1]
    result = asyncio.run(handle_turn(state, f"Сравни {first['hotel']['name']} и {second['hotel']['name']}"))
    assert result['agent']['offer_indices'] == [3, 2]


@pytest.mark.parametrize('message', ['Сравни 2 и 9', 'Сравни второй', 'Сравни 2 и 2'])
def test_invalid_or_incomplete_comparison_asks_instead_of_comparing_fixed_pair(message):
    state = ready()
    before = deepcopy(state['requirements'])
    result = asyncio.run(handle_turn(state, message))
    assert not result.get('agent')
    assert 'уточн' in result['assistant_message'].lower() or 'номер' in result['assistant_message'].lower()
    assert result['requirements'] == before


def test_sort_after_selection_retains_hotel_intent_but_returns_full_results():
    state = ready()
    chosen = deepcopy(state['plans'][1])
    choose_offer(state, chosen)
    result = asyncio.run(handle_turn(state, 'Покажи сначала дешевле'))
    assert result['stage'] == 'results'
    assert result['hotel_intent']['id'] == chosen['hotel']['id']
    assert result['selected_plan'] == chosen
    assert len({p['hotel']['id'] for p in result['plans']}) == 3
    assert result['ranking'] == 'price'


def test_hypothetical_with_sort_word_never_applies_changes():
    state = ready()
    before = deepcopy(state['requirements'])
    result = asyncio.run(process_message(state, 'Что будет, если покажи дешевле без завтрака?'))
    assert result['requirements'] == before
    assert result['_ranking'] == 'balanced'



def test_saved_plan_chat_answers_read_only_and_blocks_changes(tmp_path):
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.service import local_today
    with TestClient(create_app('sqlite:///' + str(tmp_path / 'saved.db'))) as client:
        state = client.post('/api/sessions', json={'message': f"В Сочи с {(local_today() + timedelta(days=45)).isoformat()} на 7 ночей, бюджет 500 тысяч, с завтраком"}).json()
        base = f"/api/sessions/{state['id']}"
        state = client.post(base + '/select', json={'revision': state['revision'], 'plan_id': state['plans'][1]['id']}).json()
        state = client.post(base + '/checkout', json={'revision': state['revision'], 'accept_demo': True}).json()
        order, requirements = deepcopy(state['order']), deepcopy(state['requirements'])
        for text in ['Что включено?', 'Проверь план', 'Убери завтрак']:
            response = client.post(base + '/messages', json={'revision': state['revision'], 'message': text})
            assert response.status_code == 200
            state = response.json()
            assert state['order'] == order
            assert state['requirements'] == requirements
            assert state['stage'] == 'booked'
        restored = client.get(base).json()
        assert restored['messages'][-2]['content'] == 'Убери завтрак'


def test_model_receives_current_trip_stage_selection_and_bounded_chat_history(monkeypatch):
    import json

    from app.agent import presentation
    state = ready(children_ages=[6])
    choose_offer(state, state['plans'][1])
    state['messages'] = [{'role': 'user', 'content': 'Тихий семейный отдых'}]
    monkeypatch.setenv('AGENT_ENABLED', '1')
    monkeypatch.setenv('LLM_MODEL', 'fake')
    monkeypatch.setenv('LLM_API_KEY', 'fake-secret')
    async def fake(messages, **kwargs):
        payload = json.loads(messages[-1]['content'])
        assert payload['context']['requirements']['children_ages'] == [6]
        assert payload['context']['stage'] == 'selected'
        assert payload['context']['selected_plan_id'] == state['selected_plan']['id']
        assert payload['context']['history'][-1]['content'] == 'Тихий семейный отдых'
        return {'title': 'Что важно знать', 'fact_ids': ['trip_dates', 'trip_guests'], 'ask_priority': False}
    monkeypatch.setattr('app.agent.model_json', fake)
    result = asyncio.run(presentation(state, 'Какие даты и кто едет?', 'details', defer=False))
    assert result['mode'] == 'llm'
    assert '6' in result['facts'][1]['text']


def test_factual_second_offer_policy_and_total_is_not_counterfactual_price():
    state = ready()
    second = deepcopy(state['plans'][1])
    before = deepcopy(state['requirements'])
    result = asyncio.run(process_message(state, 'Расскажи, какие условия отмены у второго варианта и сколько он стоит?'))
    assert result['agent']['tool'] == 'details'
    assert result['agent']['offer_indices'] == [2]
    assert result['requirements'] == before
    facts = result['agent']['facts']
    assert any(f['source'].get('plan_id') == second['id'] and f['source'].get('field') == 'price' for f in facts)
    assert any(f['source'].get('plan_id') == second['id'] and f['source'].get('field') == 'policy' for f in facts)


def test_factual_answer_keeps_requested_price_and_policy_if_model_omits_them(monkeypatch):
    from app.agent import presentation
    monkeypatch.setenv('AGENT_ENABLED', '1')
    monkeypatch.setenv('LLM_MODEL', 'fake')
    monkeypatch.setenv('LLM_API_KEY', 'fake-secret')
    async def fake(*args, **kwargs):
        return {'title': 'Что важно знать', 'fact_ids': ['unknown', 'demo'], 'ask_priority': False}
    monkeypatch.setattr('app.agent.model_json', fake)
    result = asyncio.run(presentation(ready(), 'Какие условия отмены у второго и сколько он стоит?', 'details', indices=[2], defer=False))
    assert result['mode'] == 'llm'
    assert [f['id'] for f in result['facts'][:2]] == ['offer_1_price', 'offer_1_cancel']


def test_observed_nested_preference_evidence_is_validated_as_source_quotes():
    from app.models import TripRequirements
    from app.parser import parse_rules, validated_model_intent
    text = 'В Сочи, завтрак желателен'
    proposal = {'action': 'change', 'patch': {'breakfast': True, 'preference_modes': {'breakfast': 'preferred'}}, 'evidence': {'breakfast': 'завтрак желателен', 'preference_modes': {'breakfast': 'завтрак желателен'}}, 'questions': []}
    req = TripRequirements()
    result = validated_model_intent(proposal, text, req, parse_rules(text, req))
    assert result.mode == 'llm'
    assert result.patch['preference_modes']['breakfast'] == 'preferred'
    assert result.patch['breakfast'] is True


@pytest.mark.parametrize('nested', [
    {'breakfast': 'бассейн желателен'},
    {'breakfast': 'выдуманная цитата'},
    {'budget': 'завтрак желателен'},
    {'breakfast': {'quote': 'завтрак желателен'}},
])
def test_nested_evidence_never_bypasses_quote_or_field_validation(nested):
    from app.models import TripRequirements
    from app.parser import parse_rules, validated_model_intent
    text = 'В Сочи, завтрак желателен'
    proposal = {'action': 'change', 'patch': {'breakfast': True, 'preference_modes': {'breakfast': 'preferred'}}, 'evidence': {'preference_modes': nested}, 'questions': []}
    req = TripRequirements()
    with pytest.raises(ValueError):
        validated_model_intent(proposal, text, req, parse_rules(text, req))
