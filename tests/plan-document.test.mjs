import test from 'node:test';
import assert from 'node:assert/strict';
import { planDocument } from '../static/plan-document.js';

test('saved plan includes factual prices, children, policy and printable route without executable input', () => {
  const order = { reference: 'PLAN-1', total: 53000, traveler_name: '<script>alert(1)</script>', plan: {
    hotel: { name: 'Море & сад', area: 'Сочи', stars: 4 },
    room: { name: 'Семейный', rooms: 1 },
    dates: { check_in: '2026-11-06', check_out: '2026-11-13', nights: 7 },
    guests: { adults: 2, children_ages: [0, 7] }, meal: 'Завтрак включён', policy: 'Невозвратный тариф',
    transport: { mode: 'self', title: 'Самостоятельная дорога' },
    price: { hotel: 53000, transport: 0, transfer: 0, extras: 0, total: 53000 },
    timeline: [{ time: '2026-11-06T14:00:00', title: 'Заселение', detail: 'После 14:00' }], warnings: ['Ужин не включён'],
  }};
  const html = planDocument(order, { breakfast: true, preference_modes: { breakfast: 'required' } });
  for (const text of ['Море &amp; сад', '53', 'возраст детей: 0, 7', 'Невозвратный тариф', 'Заселение', 'Завтрак — обязательно', '@media print', 'Бронирование и оплата не выполнены']) assert.ok(html.includes(text), text);
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('Не включено'));
});
