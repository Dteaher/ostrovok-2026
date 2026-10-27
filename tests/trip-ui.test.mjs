import test from 'node:test';
import assert from 'node:assert/strict';
import { requirementsPatch, assignStayImages, readablePolicy, restoreStayImages } from '../static/trip-ui.js';

const current = {
  destination: 'Сочи', check_in: '2026-11-13', nights: 3, adults: 2,
  children_ages: [0, 7], budget: 80000, budget_scope: 'trip',
  transport: 'flight', origin: 'Москва', refundable: true, quiet: true,
  preference_modes: { refundable: 'required', quiet: 'preferred' },
};
const form = { destination: 'Сочи', check_in: '2026-11-13', nights: '3', adults: '2', children_ages: ['0', '7'], budget: '80000', budget_scope: 'trip', transport: 'flight', origin: 'Москва' };

test('changing dates emits only changed fields and leaves required preferences intact', () => {
  assert.deepEqual(requirementsPatch(current, { ...form, check_in: '2026-11-20', nights: '5' }), { check_in: '2026-11-20', nights: 5 });
  assert.deepEqual(current.preference_modes, { refundable: 'required', quiet: 'preferred' });
});
test('unchanged form does not reprice; clearing the budget removes the limit', () => {
  assert.deepEqual(requirementsPatch(current, form), {});
  assert.deepEqual(requirementsPatch(current, { ...form, budget: '' }), { budget: null });
});
test('child age zero survives editing and removing children sends the empty list', () => {
  assert.deepEqual(requirementsPatch(current, { ...form, children_ages: ['0', '8'] }), { children_ages: [0, 8] });
  assert.deepEqual(requirementsPatch(current, { ...form, children_ages: [] }), { children_ages: [] });
});
test('missing ages, nonintegral guests and out of range values never become valid patches', () => {
  for (const changes of [{ children_ages: [''] }, { children_ages: ['18'] }, { adults: '2.5' }, { adults: '' }, { nights: '31' }, { budget: '999' }, { origin: ' ' }, { check_in: '2026-02-30' }]) {
    assert.throws(() => requirementsPatch(current, { ...form, ...changes }));
  }
});
test('all basics can change together without resetting existing non-form requirements', () => {
  assert.deepEqual(requirementsPatch(current, { ...form, adults: '3', transport: 'self', origin: ' Москва ', budget_scope: 'hotel' }), { adults: 3, budget_scope: 'hotel', transport: 'self' });
  assert.equal(current.refundable, true);
});
test('three shown properties get distinct compatible assets, stable when reordered', () => {
  const hotels = [
    { id: 'h08', stars: 4, beach_m: 1100, features: ['pool'] },
    { id: 'h09', stars: 2, beach_m: 350, features: [] },
    { id: 'h14', stars: 5, beach_m: 70, features: ['pool'] },
  ];
  const images = assignStayImages(hotels);
  assert.equal(new Set(Object.values(images)).size, 3);
  assert.match(images.h08, /garden/);
  assert.match(images.h14, /coastal/);
  assert.deepEqual(assignStayImages([...hotels].reverse()), images);
  const noPools = assignStayImages(hotels.map(hotel => ({ ...hotel, features: [] })));
  assert.equal(new Set(Object.values(noPools)).size, 3);
  assert.ok(Object.values(noPools).every(path => !path.includes('coastal')));
});
test('policy formatting removes machine date syntax but retains the penalty', () => {
  assert.equal(readablePolicy('Бесплатная отмена до 2026-11-10 14:00:00 (Москва); после — стоимость проживания.'), 'Бесплатная отмена до 10 ноября, 14:00 МСК; после — стоимость проживания.');
  assert.equal(readablePolicy('Невозвратный тариф. Стоимость не возвращается.'), 'Невозвратный тариф. Стоимость не возвращается.');
});

test('a retained hotel keeps its illustration after replanning and duplicate offers do not consume assets', () => {
  const first = { id: 'h01', stars: 4, beach_m: 100, features: ['pool'] };
  const second = { id: 'h02', stars: 4, beach_m: 100, features: ['pool'] };
  const images = assignStayImages([first, second]);
  assert.equal(assignStayImages([second], images).h02, images.h02);
  assert.deepEqual(assignStayImages([first, first, second]), images);
});

test('saved image assignments survive browser-storage round trips and ignore untrusted paths', () => {
  const saved = JSON.parse(JSON.stringify({ images: { h01: '/static/media/stays/demo-coastal.webp', h02: '/static/media/stays/demo-garden.webp', h03: 'https://other.example/image.jpg' } }));
  const restored = restoreStayImages(saved.images);
  assert.deepEqual(restored, { h01: '/static/media/stays/demo-coastal.webp', h02: '/static/media/stays/demo-garden.webp' });
  assert.equal(assignStayImages([{ id: 'h02', stars: 4, beach_m: 100, features: ['pool'] }], restored).h02, '/static/media/stays/demo-garden.webp');
  assert.deepEqual(restoreStayImages(null), {});
});
