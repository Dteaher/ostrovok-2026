(() => {
  'use strict';

  const STORAGE_KEY = 'oplan-session-v1';
  const main = document.querySelector('#main');
  const live = document.querySelector('#live-status');
  const newTrip = document.querySelector('#new-trip');
  const money = value => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(Number(value) || 0) + ' ₽';
  const date = value => value ? new Date(value + 'T12:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' }) : 'даты уточним';
  const dateTime = value => {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  };
  const plural = (n, one, few, many) => n % 10 === 1 && n % 100 !== 11 ? one : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? few : many;
  const nights = n => `${n} ${plural(n, 'ночь', 'ночи', 'ночей')}`;
  const state = { session: null, config: null, pending: false, restoring: false, error: '', showResults: false, draft: '', checkout: { name: '', email: '', accepted: false } };
  const examples = [
    'В Сочи на неделю вдвоём, до 150 тысяч, с завтраками и рядом с морем',
    'Семьёй в Сочи: двое взрослых и ребёнок 7 лет, нужен бассейн',
    'Хочу к морю из Москвы, тихий отель и прямой перелёт'
  ];

  function node(tag, attrs = {}, ...children) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === 'class') element.className = value;
      else if (key.startsWith('on') && typeof value === 'function') element.addEventListener(key.slice(2), value);
      else if (value !== false && value != null) element.setAttribute(key, value === true ? '' : String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child != null && child !== false) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return element;
  }

  const button = (label, action, className = 'button', attrs = {}) => node('button', { type: 'button', class: className, onclick: action, ...attrs }, label);
  const smallLabel = text => node('p', { class: 'eyebrow' }, text);
  const arrow = () => node('span', { 'aria-hidden': 'true' }, '↗');
  const announce = text => { live.textContent = text; };

  function saveSession() {
    try {
      if (state.session) localStorage.setItem(STORAGE_KEY, state.session.id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch { /* The current trip still works when browser storage is unavailable. */ }
  }

  async function request(path, options = {}) {
    let response;
    try {
      response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
    } catch {
      throw new Error('Не удалось связаться с сервисом. Проверьте соединение и попробуйте ещё раз — ваш текст сохранён.');
    }
    let data;
    try { data = await response.json(); } catch { throw new Error('Сервис вернул неполный ответ. Попробуйте ещё раз чуть позже.'); }
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : 'Проверьте введённые данные и попробуйте ещё раз.');
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function mutate(path, body, method = 'POST') {
    if (state.pending) return;
    state.pending = true;
    state.error = '';
    setPending(true);
    announce('Собираем ваш план. Пожалуйста, подождите.');
    try {
      const session = await request(path, { method, body: JSON.stringify(body) });
      state.session = session;
      state.showResults = false;
      state.draft = '';
      saveSession();
      announce(session.stage === 'booked' ? 'Демонстрационная заявка создана.' : 'План обновлён.');
    } catch (error) {
      if (error.status === 409 && state.session) {
        try {
          state.session = await request(`/api/sessions/${encodeURIComponent(state.session.id)}`);
          state.error = 'План изменился в другой вкладке. Мы загрузили свежую версию. Проверьте условия и повторите действие.';
        } catch { state.error = 'Не удалось обновить план. Перезагрузите страницу и повторите действие.'; }
      } else if (error.status === 404 && state.session) {
        state.error = 'Этот план больше недоступен. Начните новую поездку — исходный запрос можно скопировать из истории ниже.';
      } else state.error = error.message;
      announce(state.error);
    } finally {
      state.pending = false;
      render();
      if (state.error) document.querySelector('.alert-error')?.focus();
      else document.querySelector('[data-view-heading]')?.focus();
    }
  }

  function setPending(pending) {
    main.setAttribute('aria-busy', String(pending));
    newTrip.disabled = pending;
    for (const control of main.querySelectorAll('button, textarea, input')) control.disabled = pending;
    const submit = main.querySelector('.composer-submit');
    if (submit) {
      submit.classList.toggle('is-loading', pending);
      submit.textContent = pending ? 'Собираем план…' : state.session ? 'Обновить план ↗' : 'Собрать поездку ↗';
    }
    const checkout = main.querySelector('.checkout-submit');
    if (checkout && pending) checkout.textContent = 'Создаём демозаявку…';
  }

  function sendMessage(message) {
    const cleaned = message.trim();
    if (!cleaned || state.pending) return;
    state.draft = cleaned;
    if (state.session) return mutate(`/api/sessions/${encodeURIComponent(state.session.id)}/messages`, { message: cleaned, revision: state.session.revision });
    return mutate('/api/sessions', { message: cleaned });
  }

  function patchRequirements(patch) {
    if (!state.session) return;
    return mutate(`/api/sessions/${encodeURIComponent(state.session.id)}/requirements`, { patch, revision: state.session.revision }, 'PATCH');
  }

  function renderError() {
    if (!state.error) return null;
    return node('div', { class: 'alert alert-error', role: 'alert', tabindex: '-1' },
      node('span', {}, state.error), button('Закрыть', () => { state.error = ''; render(); }, 'text-button'));
  }

  function parserNote() {
    return (state.session?.parser_mode || state.config?.parser_mode) === 'llm'
      ? 'Запрос разбирает языковая модель. Условия и цены проверяет сервис.'
      : 'Демоверсия: запрос разбирается по ключевым условиям. Проверьте, что мы всё поняли верно.';
  }

  function composer(compact = false) {
    const input = node('textarea', {
      id: compact ? 'refine-message' : 'trip-message', name: 'message', rows: compact ? 2 : 3,
      maxlength: '3000', required: true, 'aria-label': compact ? 'Что изменить в поездке' : 'Расскажите о своей поездке',
      placeholder: compact ? 'Например: «А если на 2 ночи меньше и с бассейном?»' : 'Например: в Сочи на неделю вдвоём, до 150 тысяч. Хочется завтраки, тишину и море рядом.',
      oninput: event => { state.draft = event.target.value; },
      onkeydown: event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); sendMessage(input.value); } }
    });
    input.value = state.draft;
    return node('form', { class: `composer ${compact ? 'composer-compact' : ''}`, onsubmit: event => { event.preventDefault(); sendMessage(input.value); } },
      node('label', { for: input.id, class: 'composer-label' }, compact ? 'Давайте сделаем план ещё ближе к вам' : 'Какую поездку вы задумали?'),
      input,
      node('div', { class: 'composer-bottom' }, node('span', { class: 'composer-hint' }, compact ? 'Остальные пожелания сохраним' : 'Куда, когда, с кем и что для вас важно'),
        node('button', { type: 'submit', class: 'button composer-submit' }, compact ? 'Обновить план ↗' : 'Собрать поездку ↗')));
  }

  function landing() {
    const prompts = state.config?.examples?.length ? state.config.examples.slice(0, 3) : examples;
    return node('div', { class: 'landing enter' },
      node('section', { class: 'hero', 'aria-labelledby': 'hero-title' },
        node('div', { class: 'hero-content' }, smallLabel('Хорошая поездка начинается с желания'),
          node('h1', { id: 'hero-title', tabindex: '-1', 'data-view-heading': true }, 'Вы мечтаете.', node('br'), node('span', {}, 'Остальное — план.')),
          node('p', { class: 'hero-description' }, 'Расскажите, как хотите отдохнуть. Мы соберём дорогу, отель и полную стоимость — в одну понятную поездку.'),
          composer(),
          node('p', { class: 'parser-note' }, parserNote())),
        node('figure', { class: 'hero-art' }, node('img', { src: '/static/media/coast.svg', alt: 'Иллюстрация черноморского побережья: горы, тёплое море и маленький парусник', width: 900, height: 1100 }),
          node('figcaption', {}, node('span', {}, 'Чуть ближе к морю'), node('span', { class: 'art-coordinate' }, '43°35′ с. ш. / 39°43′ в. д.')))),
      node('section', { class: 'examples', 'aria-label': 'Примеры запросов' },
        smallLabel('Или начните с идеи'),
        node('div', { class: 'example-grid' }, prompts.map((prompt, index) => button(node('span', {}, node('span', { class: 'example-number' }, `0${index + 1}`), node('span', {}, prompt), arrow()), () => sendMessage(prompt), 'example-button')))),
      node('section', { class: 'how', id: 'how', 'aria-labelledby': 'how-title' },
        node('div', {}, smallLabel('Без десятков вкладок'), node('h2', { id: 'how-title' }, 'От «хочу к морю»', node('br'), 'до «всё продумано».')),
        node('ol', {}, node('li', {}, node('strong', {}, 'Расскажите о главном'), node('p', {}, 'О желаниях, бюджете, спутниках. Обычными словами.')),
          node('li', {}, node('strong', {}, 'Выберите свой вариант'), node('p', {}, 'Сравните полную стоимость, преимущества и компромиссы.')),
          node('li', {}, node('strong', {}, 'Поменяйте одной фразой'), node('p', {}, 'Уточните пожелания — мы пересоберём поездку, сохранив остальное.')))),
      node('p', { class: 'demo-footnote' }, 'Сейчас работаем с демонстрационным каталогом Сочи. Отели, наличие мест и цены учебные. Оформление создаёт демозаявку без оплаты.'));
  }

  function conditions(requirements) {
    const r = requirements;
    const people = [`${r.adults} ${plural(r.adults, 'взрослый', 'взрослых', 'взрослых')}`];
    if (r.children_ages?.length) people.push(`${r.children_ages.length} ${plural(r.children_ages.length, 'ребёнок', 'ребёнка', 'детей')} (${r.children_ages.join(', ')} лет)`);
    const transport = { flight: 'Перелёт', train: 'Поезд', self: 'Своим ходом' }[r.transport] || 'Дорога';
    const terms = [r.destination || 'Куда — уточним', `${date(r.check_in)} · ${nights(r.nights)}`, people.join(' + '), r.budget ? `До ${money(r.budget)}${r.budget_scope === 'hotel' ? ' на отель' : ' за всё'}` : 'Бюджет не задан', `${transport}${r.origin ? ' · ' + r.origin : ''}`];
    const flags = [['breakfast', 'Завтраки'], ['pool', 'Бассейн'], ['pets', 'С питомцем'], ['refundable', 'С отменой'], ['direct_only', 'Без пересадок'], ['quiet', 'Тихий отдых'], ['accessible', 'Доступная среда']];
    flags.forEach(([key, label]) => { if (r[key]) terms.push(label); });
    if (r.max_beach_m) terms.push(`Море до ${r.max_beach_m} м`);
    if (r.min_rating) terms.push(`Оценка от ${r.min_rating}`);
    if (r.stars) terms.push(`От ${r.stars} звёзд`);
    return node('section', { class: 'conditions', 'aria-label': 'Сохранённые условия поездки' }, smallLabel('Ваши условия · сохраняем при изменениях'), node('ul', { class: 'condition-list' }, terms.map(term => node('li', {}, term))));
  }

  function sessionIntro() {
    const session = state.session;
    const assumptions = [...new Set([...(session.assumptions || []), ...(session.requirements.assumptions || [])])];
    return node('section', { class: 'session-intro' },
      node('div', { class: 'session-title-row' }, node('div', {}, smallLabel('От желания к маршруту'),
        node('h1', { class: 'results-title', tabindex: '-1', 'data-view-heading': true }, session.stage === 'clarify' ? 'Пара деталей — и в путь.' : session.stage === 'booked' ? 'Ваш отдых обрёл план.' : 'Кажется, море зовёт.')),
        node('span', { class: 'demo-tag' }, node('span', { class: 'status-dot' }), 'Демопоездка')),
      conditions(session.requirements),
      node('div', { class: 'assistant-message' }, node('span', { class: 'assistant-mark', 'aria-hidden': 'true' }, 'О!'), node('p', {}, session.assistant_message || 'Подобрали варианты под ваши условия.')),
      session.changes?.length ? node('p', { class: 'changes-note' }, 'Обновили: ', session.changes.map(change => change.label || change.field).join(', '), '. Остальные условия сохранены.') : null,
      assumptions.length || session.requirements.unsupported?.length ? node('details', { class: 'assumptions' }, node('summary', {}, 'Что мы приняли за основу', node('span', { 'aria-hidden': 'true' }, ' +')), node('ul', {}, assumptions.map(value => node('li', {}, value)), (session.requirements.unsupported || []).map(value => node('li', {}, 'Пока не можем учесть: ' + value)))) : null);
  }

  function clarification() {
    return node('section', { class: 'clarify-section' },
      (state.session.clarifications || []).map(question => node('div', { class: 'clarify-item' }, node('h2', {}, question.question),
        node('div', { class: 'chip-row' }, (question.options || []).map(option => button(option.label, () => patchRequirements({ [question.field]: option.value }), 'choice-chip'))))),
      composer(true), node('p', { class: 'parser-note' }, parserNote()));
  }

  function hotelCard(plan, index) {
    const hotel = plan.hotel;
    const imagePath = typeof hotel.image === 'string' && hotel.image.startsWith('/static/') ? hotel.image : '/static/media/coast.svg';
    const badge = state.session.plan_labels?.[plan.id] || (index === 0 ? 'Подходит вашим условиям' : null);
    return node('article', { class: 'hotel-card' },
      node('div', { class: `hotel-image hotel-image-${index}` }, node('img', { src: imagePath, alt: '', loading: 'lazy', width: 900, height: 1100 }),
        node('span', { class: 'image-note' }, 'Иллюстрация · демокаталог'), badge ? node('span', { class: 'recommendation' }, badge) : null),
      node('div', { class: 'hotel-body' },
        node('div', { class: 'hotel-meta' }, node('span', {}, hotel.area || 'Сочи', hotel.stars ? ` · ${hotel.stars}★` : ''), node('span', { class: 'rating' }, hotel.rating ? String(hotel.rating).replace('.', ',') : '—', node('span', { class: 'sr-only' }, ' — оценка отеля'))),
        node('h3', {}, hotel.name),
        node('p', { class: 'hotel-logistics' }, `${hotel.beach_m} м до моря · ${plan.meal || 'Питание уточняется'}`),
        node('div', { class: 'fit-list' }, (plan.reasons || []).slice(0, 3).map(reason => node('p', {}, node('span', { 'aria-hidden': 'true' }, '✓'), reason))),
        node('p', { class: 'compromise' }, node('span', {}, 'Учтите: '), plan.compromises?.length ? plan.compromises.join(' · ') : 'Цены и доступность демонстрационные.'),
        node('div', { class: 'card-bottom' }, node('p', { class: 'total-price' }, money(plan.price.total), node('span', {}, `За всех · ${nights(plan.dates.nights)} · с дорогой`)),
          button(node('span', {}, 'Посмотреть план ', arrow()), () => mutate(`/api/sessions/${encodeURIComponent(state.session.id)}/select`, { plan_id: plan.id, revision: state.session.revision }), 'button button-full'))));
  }

  function suggestionButton(suggestion) {
    return button(node('span', {}, suggestion.label, suggestion.saving > 0 ? node('span', { class: 'saving' }, `−${money(suggestion.saving)}`) : null,
      suggestion.baseline_total != null && suggestion.alternative_total != null ? node('span', { class: 'saving-comparison' }, `Самая доступная поездка: ${money(suggestion.baseline_total)} → ${money(suggestion.alternative_total)}`) : null),
      () => patchRequirements({ [suggestion.field]: suggestion.value }), 'change-chip', { title: suggestion.note || null });
  }

  function alternatives() {
    const session = state.session;
    const all = [...(session.suggestions || [])];
    for (const counter of session.counterfactuals || []) {
      // A counterfactual is only actionable when the API supplies an explicit patch value.
      if (counter.value !== undefined && !all.some(item => item.field === counter.field && item.value === counter.value)) all.push(counter);
    }
    const counterWithoutValue = (session.counterfactuals || []).filter(counter => counter.value === undefined);
    if (!all.length && !counterWithoutValue.length) return null;
    return node('section', { class: 'alternatives', 'aria-label': 'Варианты изменения поездки' },
      node('div', {}, smallLabel(session.counterfactuals?.length ? 'Где можно сэкономить' : 'А если немного иначе?'), node('p', {}, 'Посмотрите, как меняется поездка. Остальные условия сохраним.'),
        session.counterfactuals?.length ? node('p', { class: 'economy-note' }, 'Сравниваем минимальные цены до и после изменения. Отель может измениться. Экономия разных вариантов не складывается.') : null),
      node('div', { class: 'chip-row' }, all.map(suggestionButton), counterWithoutValue.map(counter => button(node('span', {}, counter.label, counter.saving > 0 ? node('span', { class: 'saving' }, `−${money(counter.saving)}`) : null), () => sendMessage(counter.label), 'change-chip'))));
  }

  function results() {
    const session = state.session;
    return node('div', { class: 'results-content' },
      node('div', { class: 'section-heading' }, node('h2', {}, session.plans.length ? 'Выберите свой ритм' : 'Такой поездке нужно чуть больше свободы'),
        session.plans.length ? node('p', {}, `${session.plans.length} ${plural(session.plans.length, 'вариант', 'варианта', 'вариантов')} из ${session.total_matches} подходящих`) : null),
      session.plans.length ? node('div', { class: 'hotel-grid' }, session.plans.slice(0, 3).map(hotelCard)) : node('div', { class: 'empty-state' },
        node('span', { class: 'empty-symbol', 'aria-hidden': 'true' }, '↝'), node('h3', {}, 'Все пожелания вместе пока не совпали'), node('p', {}, 'Попробуйте увеличить бюджет, сдвинуть даты или убрать одно из обязательных условий. Мы покажем только подходящие варианты.')),
      alternatives(), composer(true), node('p', { class: 'parser-note' }, parserNote()), history());
  }

  function priceBreakdown(plan) {
    const entries = [['Проживание', plan.price.hotel], ['Дорога туда и обратно', plan.price.transport], ['Трансфер', plan.price.transfer], ['Дополнительно', plan.price.extras]];
    return node('div', { class: 'price-breakdown' },
      node('h3', {}, 'Вся поездка, одна сумма'),
      node('dl', {}, entries.map(([label, value]) => node('div', {}, node('dt', {}, label), node('dd', {}, money(value))))),
      node('div', { class: 'breakdown-total' }, node('span', {}, 'Итого за всех'), node('strong', {}, money(plan.price.total))),
      node('p', { class: 'muted small' }, `${nights(plan.dates.nights)} · ${plan.guests.adults} взр.${plan.guests.children_ages.length ? ` + ${plan.guests.children_ages.length} дет.` : ''} · рубли`));
  }

  function tripDetails(plan) {
    const transport = plan.transport;
    return node('div', { class: 'trip-detail-content' },
      node('section', { class: 'detail-summary' }, smallLabel('Ваш вариант'), node('h2', {}, plan.hotel.name),
        node('p', { class: 'detail-location' }, `${plan.hotel.area} · ${plan.hotel.stars}★ · оценка ${String(plan.hotel.rating).replace('.', ',')} · ${plan.hotel.beach_m} м до моря`),
        node('p', {}, plan.hotel.description),
        node('dl', { class: 'detail-facts' },
          node('div', {}, node('dt', {}, 'Когда'), node('dd', {}, `${date(plan.dates.check_in)} — ${date(plan.dates.check_out)} · ${nights(plan.dates.nights)}`)),
          node('div', {}, node('dt', {}, 'Проживание'), node('dd', {}, `${plan.room.name} · ${plan.room.rooms} ${plural(plan.room.rooms, 'номер', 'номера', 'номеров')}`)),
          node('div', {}, node('dt', {}, 'Питание'), node('dd', {}, plan.meal)),
          node('div', {}, node('dt', {}, 'Дорога'), node('dd', {}, transport.title)),
          node('div', {}, node('dt', {}, 'Трансфер'), node('dd', {}, plan.transfer.title))),
        node('div', { class: 'detail-reasons' }, node('h3', {}, 'Почему этот вариант'), node('ul', {}, (plan.reasons || []).map(reason => node('li', {}, reason)))),
        plan.compromises?.length ? node('div', { class: 'detail-compromises' }, node('h3', {}, 'О чём стоит знать'), node('ul', {}, plan.compromises.map(value => node('li', {}, value)))) : null),
      node('section', { class: 'timeline-section' }, node('h3', {}, 'Как всё сложится'),
        node('ol', { class: 'timeline' }, (plan.timeline || []).map(item => node('li', {}, node('span', { class: 'timeline-time' }, dateTime(item.time)), node('div', {}, node('strong', {}, item.title), node('p', {}, item.detail))))),
        node('div', { class: 'policy-note' }, node('h3', {}, 'Условия и ограничения'), node('p', {}, plan.policy), (plan.warnings || []).map(warning => node('p', {}, warning)), node('p', {}, plan.data_label || 'Демонстрационные данные. Не является предложением бронирования.'))));
  }

  function checkoutForm(plan) {
    const name = node('input', { id: 'traveler-name', name: 'name', autocomplete: 'name', required: true, minlength: 2, maxlength: 100, placeholder: 'Имя и фамилия', oninput: event => { state.checkout.name = event.target.value; } });
    const email = node('input', { id: 'traveler-email', name: 'email', type: 'email', autocomplete: 'email', required: true, maxlength: 254, placeholder: 'you@example.ru', oninput: event => { state.checkout.email = event.target.value; } });
    const agreement = node('input', { id: 'demo-agreement', type: 'checkbox', required: true, onchange: event => { state.checkout.accepted = event.target.checked; } });
    name.value = state.checkout.name;
    email.value = state.checkout.email;
    agreement.checked = state.checkout.accepted;
    return node('aside', { id: 'checkout', class: 'checkout-panel', 'aria-label': 'Оформление демонстрационной заявки' }, priceBreakdown(plan),
      node('form', { class: 'checkout-form', onsubmit: event => {
        event.preventDefault();
        if (!name.value.trim() || name.value.trim().length < 2) { name.setCustomValidity('Введите имя длиной от 2 символов.'); name.reportValidity(); name.addEventListener('input', () => name.setCustomValidity(''), { once: true }); return; }
        mutate(`/api/sessions/${encodeURIComponent(state.session.id)}/checkout`, { revision: state.session.revision, accept_demo: agreement.checked, traveler_name: name.value.trim(), email: email.value.trim() });
      } },
        node('span', { class: 'demo-tag demo-tag-small' }, 'Демооформление'), node('h3', {}, 'Осталось назвать себя'), node('p', { class: 'small muted' }, 'Создадим заявку с вашим планом. Без оплаты и реального бронирования.'),
        node('label', { for: name.id }, 'Ваше имя'), name, node('label', { for: email.id }, 'Электронная почта'), email,
        node('p', { class: 'form-note' }, 'Почта сохранится в демозаявке. Письма не отправляем. Используйте тестовые данные.'),
        node('label', { class: 'checkbox-label', for: agreement.id }, agreement, node('span', {}, 'Я понимаю, что это демонстрация. Бронь не создаётся, деньги не списываются.')),
        node('button', { type: 'submit', class: 'button button-full checkout-submit' }, 'Оформить демозаявку ↗')));
  }

  function selected() {
    const plan = state.session.selected_plan;
    if (!plan) return results();
    return node('div', { class: 'selected-content' }, button('← К вариантам поездки', () => { state.showResults = true; render(); document.querySelector('.section-heading')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 'back-button'),
      node('div', { class: 'mobile-checkout-link' }, node('p', {}, money(plan.price.total), node('span', {}, 'За всю поездку · за всех')), node('a', { href: '#checkout', class: 'button' }, 'К оформлению ↓')),
      node('div', { class: 'selected-layout' }, tripDetails(plan), checkoutForm(plan)), history());
  }

  function downloadOrder() {
    const order = state.session.order;
    if (!order) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(order, null, 2)], { type: 'application/json;charset=utf-8' }));
    const link = node('a', { href: url, download: `oplan-${String(order.reference).replace(/[^a-zA-Z0-9А-Яа-я_-]/g, '')}.json` });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function booked() {
    const order = state.session.order;
    if (!order) return selected();
    const plan = order.plan;
    return node('section', { class: 'booked-section' }, node('div', { class: 'success-mark', 'aria-hidden': 'true' }, '✓'),
      smallLabel('План сохранён. Можно выдохнуть.'), node('h2', {}, 'Ваша демозаявка готова'), node('p', { class: 'order-reference' }, '№ ', order.reference),
      node('p', { class: 'booked-description' }, order.notice || 'Это демонстрационное оформление. Реальная бронь не создана, оплата не требуется.'),
      node('div', { class: 'order-overview' }, node('div', {}, node('span', {}, 'Поездка'), node('strong', {}, plan.hotel.name), node('p', {}, `${date(plan.dates.check_in)} — ${date(plan.dates.check_out)}`)),
        node('div', {}, node('span', {}, 'На имя'), node('strong', {}, order.traveler_name), node('p', {}, order.email)),
        node('div', {}, node('span', {}, 'За всех'), node('strong', {}, money(order.total)), node('p', {}, 'Ничего не списано'))),
      node('div', { class: 'order-actions' }, button('Скачать заявку ↓', downloadOrder), button('Спланировать ещё поездку ↗', resetTrip, 'button button-secondary')),
      node('details', { class: 'order-details' }, node('summary', {}, 'Весь маршрут и стоимость'), node('div', { class: 'selected-layout' }, tripDetails(plan), priceBreakdown(plan))));
  }

  function history() {
    const messages = state.session.messages || [];
    if (!messages.length) return null;
    return node('details', { class: 'history' }, node('summary', {}, 'История пожеланий', node('span', { 'aria-hidden': 'true' }, ' +')),
      node('ol', {}, messages.map(message => node('li', { class: message.role === 'user' ? 'history-user' : 'history-assistant' }, node('strong', {}, message.role === 'user' ? 'Вы' : 'О!План'), node('p', {}, message.content)))));
  }

  function render() {
    main.replaceChildren();
    main.setAttribute('aria-busy', String(state.pending));
    document.body.classList.toggle('has-session', Boolean(state.session));
    newTrip.hidden = !state.session;
    newTrip.disabled = state.pending;
    document.querySelector('#how-link').hidden = Boolean(state.session);
    if (state.error) main.append(renderError());
    if (state.restoring) main.append(node('section', { class: 'restore-state', role: 'status' }, smallLabel('Возвращаемся к вашим планам'), node('h1', {}, 'Ваша поездка уже рядом.'), node('p', {}, 'Загружаем сохранённые пожелания и маршрут…')));
    else if (!state.session) main.append(landing());
    else {
      main.append(sessionIntro());
      if (state.session.stage === 'booked') main.append(booked());
      else if (state.session.stage === 'clarify') main.append(clarification());
      else if (state.session.stage === 'selected' && !state.showResults) main.append(selected());
      else main.append(results());
    }
  }

  function resetTrip() {
    if (state.pending) return;
    state.session = null;
    state.draft = '';
    state.error = '';
    state.showResults = false;
    state.checkout = { name: '', email: '', accepted: false };
    saveSession();
    render();
    document.querySelector('#trip-message')?.focus();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  newTrip.addEventListener('click', resetTrip);
  async function boot() {
    let sessionId;
    try { sessionId = localStorage.getItem(STORAGE_KEY); } catch { /* Storage is optional. */ }
    state.restoring = Boolean(sessionId);
    render();
    const results = await Promise.allSettled([
      request('/api/config'),
      sessionId ? request(`/api/sessions/${encodeURIComponent(sessionId)}`) : Promise.resolve(null)
    ]);
    if (results[0].status === 'fulfilled') state.config = results[0].value;
    if (results[1].status === 'fulfilled') state.session = results[1].value;
    else {
      state.error = results[1].reason.status === 404 ? 'Предыдущая поездка больше недоступна. Расскажите о ней ещё раз — соберём новый план.' : 'Не удалось восстановить поездку. Обновите страницу, чтобы попробовать снова.';
      if (results[1].reason.status === 404) saveSession();
    }
    state.restoring = false;
    render();
  }
  boot();
})();
