// Values from the direct editor are normalized before the existing PATCH API.
// Only changed basics are sent; preferences and their priorities remain intact.
export function requirementsPatch(current, values) {
  const integer = (value, min, max, label) => {
    const number = Number(value);
    if (String(value).trim() === '' || !Number.isInteger(number) || number < min || number > max) {
      throw new Error(`${label}: укажите целое число от ${min} до ${max}.`);
    }
    return number;
  };
  const parsedDate = new Date(`${values.check_in}T12:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(values.check_in) || Number.isNaN(parsedDate.getTime()) || parsedDate.toISOString().slice(0, 10) !== values.check_in) {
    throw new Error('Укажите корректную дату заезда.');
  }
  const origin = values.origin.trim();
  if (values.transport !== 'self' && !origin) throw new Error('Укажите город отправления.');
  if (!['flight', 'train', 'self'].includes(values.transport)) throw new Error('Выберите способ поездки.');
  if (!['trip', 'hotel'].includes(values.budget_scope)) throw new Error('Уточните, на что рассчитан бюджет.');
  if (!values.destination.trim()) throw new Error('Выберите направление.');
  if (values.children_ages.length > 6) throw new Error('Можно указать до 6 детей.');
  const normalized = {
    destination: values.destination.trim(), check_in: values.check_in,
    nights: integer(values.nights, 1, 30, 'Количество ночей'),
    adults: integer(values.adults, 1, 8, 'Количество взрослых'),
    children_ages: values.children_ages.map(age => integer(age, 0, 17, 'Возраст ребёнка')),
    budget: String(values.budget).trim() === '' ? null : integer(values.budget, 1000, 10000000, 'Бюджет'),
    budget_scope: values.budget_scope, transport: values.transport, origin: origin || current.origin,
  };
  return Object.fromEntries(Object.entries(normalized).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(current[key])));
}

export function assignStayImages(hotels, previous = {}) {
  const images = {}, used = new Set();
  const uniqueHotels = [...new Map(hotels.map(hotel => [hotel.id, hotel])).values()].sort((a, b) => a.id.localeCompare(b.id));
  for (const hotel of uniqueHotels) {
    const existing = previous[hotel.id];
    if (existing) { images[hotel.id] = existing; used.add(existing); }
  }
  for (const hotel of uniqueHotels) {
    if (images[hotel.id]) continue;
    const preferred = hotel.stars <= 3 ? 'room' : hotel.beach_m >= 500 ? 'garden' : (hotel.features || []).includes('pool') ? 'coastal' : 'courtyard';
    const candidates = [...new Set([preferred, 'garden', 'courtyard', 'room', ...((hotel.features || []).includes('pool') ? ['coastal'] : [])])];
    const paths = candidates.map(name => `/static/media/stays/demo-${name}.webp`);
    const choice = paths.find(path => !used.has(path)) || paths[0];
    used.add(choice);
    images[hotel.id] = choice;
  }
  return images;
}

export function restoreStayImages(saved) {
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return {};
  return Object.fromEntries(Object.entries(saved).filter(([id, path]) => /^h\d{2}$/.test(id) && typeof path === 'string' && /^\/static\/media\/stays\/demo-(coastal|garden|room|courtyard)\.webp$/.test(path)));
}

export function readablePolicy(policy = '') {
  return policy.replace(/(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?::\d{2})? \(Москва\)/g, (_, day, time) => {
    const date = new Date(`${day}T12:00:00Z`);
    if (Number.isNaN(date.getTime())) return `${day}, ${time} МСК`;
    return `${date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' })}, ${time} МСК`;
  });
}

export function journeyView(session, hash = '') {
  if (!session) return 'landing';
  if (session.stage === 'booked' && session.order) return 'confirmation';
  if (session.stage === 'clarify') return 'clarify';
  if (session.stage === 'selected' && session.selected_plan) {
    if (hash === '#options') return 'results';
    if (hash === '#checkout' && session.request_status !== 'needs_clarification' && !session.clarifications?.length) return 'checkout';
    return 'trip';
  }
  return 'results';
}

// Viewing alternatives is independent of the hotel retained for later edits.
export function nextJourneyHash(session, previousHash, selecting = false) {
  if (session.stage === 'booked' && session.order) return '#confirmation';
  if (selecting && session.selected_plan) return '#trip';
  if (previousHash === '#options') return '#options';
  return session.stage === 'selected' && session.selected_plan ? '#trip' : '#options';
}

export function preserveMessageDraft(session) {
  return session.parser_mode === 'fallback' || session.response_timing?.timed_out === true;
}

export function priceAudience(guests) {
  const count = (n, one, few, many) => n % 10 === 1 && n % 100 !== 11 ? one : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? few : many;
  const children = guests.children_ages?.length || 0;
  return `Для ${guests.adults} ${count(guests.adults, 'взрослого', 'взрослых', 'взрослых')}${children ? ` и ${children} ${count(children, 'ребёнка', 'детей', 'детей')}` : ''}`;
}

export function travelLabels(mode) {
  if (mode === 'flight') return { service: 'Перелёт туда и обратно', scope: 'перелёт и трансфер включены', departure: 'Вылет', arrival: 'Прилёт' };
  if (mode === 'train') return { service: 'Поезд туда и обратно', scope: 'поезд и трансфер включены', departure: 'Отправление поезда', arrival: 'Прибытие поезда' };
  return { service: 'Самостоятельная дорога', scope: 'дорога и трансфер не включены', departure: 'Выезд', arrival: 'Прибытие' };
}

export function priceEntries(plan) {
  const selfTravel = plan.transport.mode === 'self';
  return [
    ['Проживание', plan.price.hotel],
    [travelLabels(plan.transport.mode).service, selfTravel ? null : plan.price.transport],
    ['Трансфер', selfTravel ? null : plan.price.transfer],
    ...(plan.price.extras ? [['Обязательные доплаты', plan.price.extras]] : []),
  ];
}

export function readableDates(text) {
  return String(text).replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (day) => {
    const value = new Date(`${day}T12:00:00Z`);
    return Number.isNaN(value.getTime()) ? day : value.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' });
  });
}

export function preferenceLabels(r) {
  const mode = key => ['pets', 'accessible'].includes(key) ? 'обязательно' :
    r.preference_modes?.[key] === 'preferred' || (key === 'quiet' && !r.preference_modes?.quiet) ? 'желательно' : 'обязательно';
  const values = [['breakfast', 'Завтрак'], ['pool', 'Бассейн'], ['pets', 'С питомцем'], ['refundable', 'Бесплатная отмена'], ['direct_only', 'Без пересадок'], ['quiet', 'Тишина'], ['accessible', 'Доступная среда']]
    .filter(([key]) => r[key]).map(([key, label]) => `${label} — ${mode(key)}`);
  if (r.max_beach_m != null) values.push(`Море до ${r.max_beach_m} м — ${mode('max_beach_m')}`);
  if (r.min_rating) values.push(`Оценка от ${String(r.min_rating).replace('.', ',')} — ${mode('min_rating')}`);
  if (r.stars) values.push(`От ${r.stars} звёзд — ${mode('stars')}`);
  return values;
}

export function offerComparison(plan, plans) {
  const baseline = [...plans, plan].reduce((best, value) => value.price.total < best.price.total ? value : best, plan);
  const facts = [];
  const number = value => String(value).replace('.', ',');
  if (plan.hotel.beach_m < baseline.hotel.beach_m) facts.push(`До моря ${plan.hotel.beach_m} м вместо ${baseline.hotel.beach_m} м`);
  if (plan.hotel.rating > baseline.hotel.rating) facts.push(`Оценка ${number(plan.hotel.rating)} вместо ${number(baseline.hotel.rating)}`);
  if (plan.refundable && !baseline.refundable) facts.push('Есть бесплатная отмена вместо невозвратного тарифа');
  if (plan.meal === 'Завтрак включён' && baseline.meal !== plan.meal) facts.push('Завтрак включён вместо тарифа без питания');
  return {
    premium: plan.price.total - baseline.price.total, baselineName: baseline.hotel.name, facts,
    preferenceGains: (plan.preference_matches || []).filter(value => !(baseline.preference_matches || []).includes(value)),
    preferenceLosses: (baseline.preference_matches || []).filter(value => !(plan.preference_matches || []).includes(value)),
  };
}
