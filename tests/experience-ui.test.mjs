import test from 'node:test';
import assert from 'node:assert/strict';
import * as ui from '../static/trip-ui.js';

const cheap = { id: 'cheap', hotel: { name: 'Доступный', beach_m: 350, rating: 8.1, stars: 2 }, price: { total: 52888 }, meal: 'Без питания', refundable: false, preference_matches: [] };
const premium = { id: 'premium', hotel: { name: 'У моря', beach_m: 70, rating: 9.5, stars: 5 }, price: { total: 104396 }, meal: 'Завтрак включён', refundable: false, preference_matches: ['Завтрак включён'] };

test('price comparison gives exact premium and factual differences, not invented value', () => {
  assert.equal(typeof ui.offerComparison, 'function');
  const result = ui.offerComparison(premium, [premium, cheap]);
  assert.equal(result.premium, 51508);
  assert.equal(result.baselineName, 'Доступный');
  assert.ok(result.facts.some(text => text.includes('70') && text.includes('350')));
  assert.ok(result.facts.some(text => text.includes('9,5') && text.includes('8,1')));
  assert.deepEqual(result.preferenceGains, ['Завтрак включён']);
});

test('a more expensive option with no wishlist gains is not presented as a better match', () => {
  assert.equal(typeof ui.offerComparison, 'function');
  const result = ui.offerComparison({ ...premium, preference_matches: [] }, [premium, cheap]);
  assert.deepEqual(result.preferenceGains, []);
  assert.equal(ui.offerComparison(cheap, [premium, cheap]).premium, 0);
  assert.equal(ui.offerComparison(premium, [premium]).premium, 0);
});

test('preference labels distinguish desirable from mandatory without weakening pet/access needs', () => {
  assert.equal(typeof ui.preferenceLabels, 'function');
  assert.deepEqual(ui.preferenceLabels({ breakfast: true, direct_only: true, pets: true, preference_modes: { breakfast: 'preferred' } }), [
    'Завтрак — желательно', 'С питомцем — обязательно', 'Без пересадок — обязательно',
  ]);
  assert.deepEqual(ui.preferenceLabels({ breakfast: false, quiet: true }), ['Тишина — желательно']);
});
