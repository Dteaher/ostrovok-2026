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

export function assignStayImages(hotels) {
  const images = {}, used = new Set();
  for (const hotel of [...hotels].sort((a, b) => a.id.localeCompare(b.id))) {
    const preferred = hotel.stars <= 3 ? 'room' : hotel.beach_m >= 500 ? 'garden' : (hotel.features || []).includes('pool') ? 'coastal' : 'courtyard';
    const candidates = [...new Set([preferred, 'garden', 'courtyard', 'room', ...((hotel.features || []).includes('pool') ? ['coastal'] : [])])];
    const choice = candidates.find(name => !used.has(name)) || preferred;
    used.add(choice);
    images[hotel.id] = `/static/media/stays/demo-${choice}.webp`;
  }
  return images;
}

export function readablePolicy(policy = '') {
  return policy.replace(/(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?::\d{2})? \(Москва\)/g, (_, day, time) => {
    const date = new Date(`${day}T12:00:00Z`);
    if (Number.isNaN(date.getTime())) return `${day}, ${time} МСК`;
    return `${date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' })}, ${time} МСК`;
  });
}
