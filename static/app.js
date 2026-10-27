import { requirementsPatch, assignStayImages, readablePolicy } from './trip-ui.js';

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

  const TRIPS_KEY = 'rivane-trips-v1';
  function closeNavigation() {
    document.body.classList.remove('menu-open');
    const toggle = document.querySelector('#mobile-menu');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Открыть навигацию');
  }
  const destinations = [
    { name: 'Сочи', label: 'Сочи', image: 'sochi', description: 'Море · Набережные · Культура', prompt: 'В Сочи' },
    { name: 'Адлер', label: 'Адлер', image: 'adler', description: 'Пляжи · Прогулки · Семья', prompt: 'В Адлере' },
    { name: 'Хоста', label: 'Хоста', image: 'khosta', description: 'Тишина · Зелень · Море', prompt: 'В Хосту' },
    { name: 'Сириус', label: 'Сириус', image: 'sirius', description: 'Побережье · Простор · Отдых', prompt: 'В Сириус' },
    { name: 'Дагомыс', label: 'Дагомыс', image: 'dagomys', description: 'Природа · Спокойствие · Горы', prompt: 'В Дагомыс' },
    { name: 'Лазаревское', label: 'Лазаревское', image: 'lazarevskoe', description: 'Пляжи · Зелёные холмы · Уют', prompt: 'В Лазаревское' }
  ];

  function icon(name, size = 22) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const paths = {
      spark: 'm12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5Z M19 2v4 M17 4h4',
      heart: 'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z',
      people: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M22 21v-2a4 4 0 0 0-3-3.9 M16 3.1a4 4 0 0 1 0 7.8 M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
      sea: 'M2 18c2-3 4 3 6 0s4 3 6 0 4 3 8 0 M2 22c2-3 4 3 6 0s4 3 6 0 4 3 8 0 M12 3v11 M5 8l7-5 7 5',
      mountain: 'M2 21 10 5l9 16Z M12 9l3-6 7 18 M7 11l3 2 3-2',
      arrow: 'M3 12h18 M15 6l6 6-6 6',
      close: 'm6 6 12 12 M6 18 18 6',
      bag: 'M4 7h16v14H4Z M9 7V3h6v4 M9 11v6 M15 11v6',
      check: 'm4 12 5 5L20 6'
    };
    for (const [key, value] of Object.entries({ width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) svg.setAttribute(key, value);
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', paths[name] || paths.arrow);
    svg.append(path);
    return svg;
  }

  function savedTrips() {
    try {
      const values = JSON.parse(localStorage.getItem(TRIPS_KEY) || '[]');
      return Array.isArray(values) ? values.filter(item => item && typeof item.id === 'string').slice(0, 20) : [];
    } catch { return []; }
  }

  function rememberTrip(session) {
    const plan = session.order?.plan || session.selected_plan || session.plans?.[0];
    const entry = { id: session.id, destination: session.requirements.destination || 'Новое путешествие', date: session.requirements.check_in, stage: session.stage, title: plan?.hotel.name || 'Ваш персональный подбор', total: session.order?.total || plan?.price.total || null, thumbnail: plan ? stayImage(plan) : null };
    try { localStorage.setItem(TRIPS_KEY, JSON.stringify([entry, ...savedTrips().filter(item => item.id !== entry.id)].slice(0, 20))); } catch { /* History is optional; API state still persists. */ }
  }

  function futureDate(days = 14) {
    const value = new Date();
    value.setDate(value.getDate() + days);
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
  }

  function seedIdea(message) {
    if (state.pending) return;
    if (state.session) resetTrip();
    state.draft = message;
    render();
    const input = document.querySelector('#trip-message');
    input?.focus({ preventScroll: true });
    input?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    announce('Идея добавлена в запрос. Уточните пожелания и спланируйте путешествие.');
  }

  function navigateSection(id) {
    if (state.pending) return;
    if (state.session) resetTrip();
    closeNavigation();
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function showTrips() {
    if (state.pending) return;
    closeNavigation();
    const dialog = node('dialog', { class: 'trips-dialog', 'aria-labelledby': 'trips-title' });
    const list = node('div', { class: 'saved-trip-list' });
    const notice = node('p', { class: 'saved-trip-error', role: 'status' });
    const close = () => dialog.close();
    const trips = savedTrips();
    dialog.append(node('div', { class: 'dialog-heading' }, node('div', {}, smallLabel('Вернёмся к вашим планам'), node('h2', { id: 'trips-title' }, 'Мои поездки')), button(icon('close'), close, 'dialog-close', { 'aria-label': 'Закрыть мои поездки' })), node('p', { class: 'dialog-description' }, 'Ваши подборы и демозаявки. Сохранены в этом браузере.'), notice, list);
    if (!trips.length) list.append(node('div', { class: 'trips-empty' }, icon('bag', 40), node('h3', {}, 'Ваша первая история ещё впереди'), node('p', {}, 'Расскажите об отдыхе — здесь останутся ваши подборы и планы.'), button('Начать путешествие', () => { close(); seedIdea(''); }, 'button')));
    trips.forEach(trip => {
      const thumbnail = typeof trip.thumbnail === 'string' && /^\/static\/media\/stays\/demo-(coastal|garden|room|courtyard)\.webp$/.test(trip.thumbnail) ? trip.thumbnail : '/static/media/stays/demo-garden.webp';
      const action = button(node('span', { class: 'saved-trip-inner' }, node('span', { class: 'saved-trip-thumbnail' }, node('img', { src: thumbnail, alt: '', width: 120, height: 90, loading: 'lazy' })), node('span', { class: 'saved-trip-copy' }, node('span', { class: 'saved-trip-status' }, trip.stage === 'booked' ? 'Демозаявка оформлена' : 'Подбор сохранён'), node('strong', {}, trip.title), node('span', {}, `${trip.destination} · ${date(trip.date)}`)), node('span', { class: 'saved-trip-price' }, trip.total ? money(trip.total) : 'Продолжить', icon('arrow'))), async () => {
        list.querySelectorAll('button').forEach(control => { control.disabled = true; });
        notice.textContent = 'Возвращаем ваш план…';
        try {
          const restored = await request(`/api/sessions/${encodeURIComponent(trip.id)}`);
          if (!dialog.open || !dialog.isConnected) return;
          if (state.session?.id !== restored.id) state.checkout = { name: '', email: '', accepted: false };
          state.session = restored;
          state.error = ''; state.draft = ''; state.showResults = false;
          saveSession(); close(); render(); window.scrollTo({ top: 0, behavior: 'smooth' });
          document.querySelector('[data-view-heading]')?.focus();
        } catch (error) {
          if (dialog.open) notice.textContent = error.status === 404 ? 'Этот подбор больше недоступен. Начните новую поездку.' : error.message;
        } finally { list.querySelectorAll('button').forEach(control => { control.disabled = false; }); }
      }, 'saved-trip-button');
      list.append(action);
    });
    dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
    dialog.addEventListener('close', () => {
      dialog.remove();
      if (document.activeElement === document.body) {
        const toggle = document.querySelector('#mobile-menu');
        (toggle.getClientRects().length ? toggle : document.querySelector('#trips-link')).focus();
      }
    });
    document.body.append(dialog);
    dialog.showModal();
  }

  function saveSession() {
    try {
      if (state.session) { localStorage.setItem(STORAGE_KEY, state.session.id); rememberTrip(state.session); }
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
    let updated = null;
    setPending(true);
    announce('Собираем ваш план. Пожалуйста, подождите.');
    try {
      const session = await request(path, { method, body: JSON.stringify(body) });
      if (session.selected_plan?.id !== state.session?.selected_plan?.id) state.checkout.accepted = false;
      state.session = session;
      updated = session;
      state.showResults = false;
      state.draft = '';
      saveSession();
      announce(session.stage === 'booked' ? 'Демонстрационная заявка создана.' : 'План обновлён.');
    } catch (error) {
      if (error.status === 409 && state.session) {
        try {
          state.session = await request(`/api/sessions/${encodeURIComponent(state.session.id)}`);
          state.error = error.message.includes('другой вкладке') ? 'План изменился в другой вкладке. Мы загрузили свежую версию. Проверьте условия и повторите действие.' : error.message;
        } catch { state.error = 'Не удалось обновить план. Перезагрузите страницу и повторите действие.'; }
      } else if (error.status === 404 && state.session) {
        state.error = 'Этот план больше недоступен. Начните новую поездку — исходный запрос можно скопировать из истории ниже.';
      } else state.error = error.message;
      announce(state.error);
    } finally {
      state.pending = false;
      render();
      if (!document.querySelector('.trip-editor[open]')) {
        if (state.error) document.querySelector('.alert-error')?.focus();
        else {
          document.querySelector('[data-view-heading]')?.focus({ preventScroll: true });
          window.scrollTo({ top: 0, behavior: 'instant' });
        }
      }
    }
    return updated;
  }

  function setPending(pending) {
    main.setAttribute('aria-busy', String(pending));
    newTrip.disabled = pending;
    for (const control of main.querySelectorAll('button, textarea, input, select')) control.disabled = pending;
    const submit = main.querySelector('.composer-submit');
    if (submit) {
      submit.classList.toggle('is-loading', pending);
      submit.textContent = pending ? 'Планируем путешествие…' : state.session ? 'Обновить план ↗' : 'Спланировать путешествие →';
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
      id: compact ? 'refine-message' : 'trip-message', name: 'message', rows: 2,
      maxlength: '3000', required: true, 'aria-label': compact ? 'Что изменить в поездке' : 'Расскажите о своей поездке',
      placeholder: compact ? 'Например: «А если на 2 ночи меньше и с бассейном?»' : 'Куда вы хотите отправиться? Например: «Хочу в Сочи на неделю, с красивым отелем, завтраками и бюджетом до 160 000 ₽ на двоих»',
      oninput: event => { state.draft = event.target.value; },
      onkeydown: event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); sendMessage(input.value); } }
    });
    input.value = state.draft;
    return node('form', { class: `composer ${compact ? 'composer-compact' : 'hero-composer'}`, onsubmit: event => { event.preventDefault(); sendMessage(input.value); } },
      !compact ? node('span', { class: 'composer-emblem' }, icon('spark', 26)) : null,
      node('label', { for: input.id, class: 'composer-label' }, compact ? 'Давайте сделаем план ещё ближе к вам' : 'Какую поездку вы задумали?'),
      input,
      node('div', { class: 'composer-bottom' }, node('span', { class: 'composer-hint' }, compact ? 'Остальные пожелания сохраним' : 'Куда, когда, с кем и что для вас важно'),
        node('button', { type: 'submit', class: 'button composer-submit' }, compact ? 'Обновить план ↗' : node('span', {}, 'Спланировать путешествие', icon('arrow')))));
  }

  function landing() {
    const prompts = state.config?.examples?.length ? state.config.examples : examples;
    const themes = [
      ['heart', 'Романтическая поездка', prompts[0]],
      ['people', 'Семейный отдых', prompts[2]],
      ['sea', 'Выходные у моря', prompts[1]],
      ['mountain', 'Горы и природа', `В Дагомыс с ${futureDate()} на 5 ночей вдвоём, тихое место, до 130 тысяч, с завтраком`]
    ];
    const steps = [
      ['01', 'Одно желание', 'Расскажите о вашем отдыхе. Обычными словами, без десятка фильтров.'],
      ['02', 'Подбор с объяснением', 'Сравните подходящие отели, полную стоимость и важные компромиссы.'],
      ['03', 'План под вас', 'Измените пожелания одной фразой. Остальные условия сохранятся.'],
      ['04', 'Всё в одном месте', 'Проверьте поездку и завершите демонстрационное оформление.']
    ];
    return node('div', { class: 'landing enter' },
      node('section', { class: 'lux-hero', 'aria-labelledby': 'hero-title' },
        node('img', { class: 'lux-hero-image', src: '/static/media/rivane/hero.webp', alt: 'Закат над морским побережьем и панорамный бассейн в Каше, Турция. Атмосферная фотография.', width: 2000, height: 1334, fetchpriority: 'high' }),
        node('div', { class: 'lux-hero-shade' }),
        node('div', { class: 'lux-hero-inner wrap' },
          node('div', { class: 'lux-intro' }, smallLabel('Больше, чем просто отели'),
            node('h1', { id: 'hero-title', tabindex: '-1', 'data-view-heading': true }, 'Путешествия,', node('br'), 'которые начинаются', node('br'), node('em', {}, 'с одного желания')),
            node('p', { class: 'lux-description' }, 'Расскажите, каким вы представляете свой отдых. ', node('span', {}, 'O!RIVANE поможет выбрать направление, сравнит варианты и составит персональный план путешествия.'))),
          node('aside', { class: 'hero-manifesto', 'aria-label': 'Наш подход' }, smallLabel('Откройте больше возможностей'),
            node('p', { class: 'manifesto-quote' }, 'Больше, чем', node('br'), 'выбор отеля.', node('br'), node('em', {}, 'Ближе к вашему'), node('br'), 'отдыху.'),
            node('span', { class: 'manifesto-rule' }),
            node('div', { class: 'hero-facts' }, node('div', {}, node('strong', {}, '20'), node('span', {}, 'демоотелей')), node('div', {}, node('strong', {}, '6'), node('span', {}, 'районов Сочи')))),
          node('div', { class: 'lux-search' }, composer(),
            node('div', { class: 'theme-chips', id: 'inspiration', 'aria-label': 'Идеи для путешествия' }, themes.map(([name, label, prompt]) => button(node('span', {}, icon(name), label), () => sendMessage(prompt), 'example-button theme-chip'))),
            node('p', { class: 'hero-demo-note' }, 'Подбираем по демонстрационному каталогу Большого Сочи. Без реальной оплаты и бронирования.'))),
        node('p', { class: 'hero-photo-credit' }, 'Атмосфера путешествий · Каш, Турция')),
      node('section', { class: 'destinations-section wrap', id: 'destinations', 'aria-labelledby': 'destinations-title' },
        node('div', { class: 'destination-heading' }, node('div', {}, smallLabel('Откройте Большой Сочи'), node('h2', { id: 'destinations-title' }, 'Идеи для вашего следующего путешествия')),
          button(node('span', {}, 'Помогите выбрать', icon('arrow')), () => seedIdea('Хочу в Большой Сочи, но пока не знаю, какой район выбрать. Важны море и спокойный отдых.'), 'outline-button')),
        node('div', { class: 'destination-grid' }, destinations.map(destination => button(node('span', { class: 'destination-card-content' },
          node('img', { src: `/static/media/rivane/${destination.image}.webp`, alt: '', width: 600, height: 500, loading: 'lazy' }),
          node('span', { class: 'destination-copy' }, node('span', { class: 'destination-name' }, destination.label), node('span', { class: 'destination-description' }, destination.description)),
          node('span', { class: 'destination-arrow' }, icon('arrow'))), () => seedIdea(`${destination.prompt} с ${futureDate()} на неделю вдвоём, до 160 тысяч, с завтраком`), 'destination-card', { 'aria-label': `Спланировать отдых: ${destination.name}` }))),
        node('p', { class: 'destination-note' }, 'Один регион — разные впечатления. Фотографии районов иллюстративные. Отели, наличие и цены в подборе демонстрационные.')),
      node('section', { class: 'journey-section wrap', id: 'how', 'aria-labelledby': 'how-title' },
        node('div', { class: 'journey-heading' }, smallLabel('Всё сложится в путешествие'), node('h2', { id: 'how-title' }, 'От первого «хочу»', node('em', {}, ' до вашего плана.'))),
        node('ol', { class: 'journey-steps' }, steps.map(([number, title, description]) => node('li', {}, node('span', { class: 'step-number' }, number), node('h3', {}, title), node('p', {}, description)))),
        node('p', { class: 'journey-parser-note' }, parserNote())));
  }

  function editConditions() {
    if (state.pending || !state.session || state.session.stage === 'booked' || document.querySelector('.trip-editor')) return;
    const current = state.session.requirements;
    const opener = document.activeElement;
    let saving = false;
    const dialog = node('dialog', { class: 'trip-editor', 'aria-labelledby': 'editor-title', 'aria-describedby': 'editor-description' });
    const select = (name, choices, value, attrs = {}) => node('select', { name, id: `edit-${name}`, ...attrs }, choices.map(([key, label]) => node('option', { value: key, selected: String(key) === String(value) }, label)));
    const input = (name, value, attrs = {}) => node('input', { name, id: `edit-${name}`, value: value ?? '', ...attrs });
    const field = (label, control, hint) => node('div', { class: 'editor-field' }, node('label', { for: control.id }, label), control, hint ? node('span', { class: 'editor-hint' }, hint) : null);
    const directionChoices = [...new Set([current.destination, ...destinations.map(item => item.name)].filter(Boolean))].map(value => [value, value]);
    const destination = select('destination', directionChoices, current.destination || 'Сочи', { required: true });
    const checkIn = input('check_in', current.check_in, { type: 'date', min: futureDate(0), required: true });
    const length = input('nights', current.nights, { type: 'number', min: 1, max: 30, step: 1, required: true, inputmode: 'numeric' });
    const adults = input('adults', current.adults, { type: 'number', min: 1, max: 8, step: 1, required: true, inputmode: 'numeric' });
    const childCount = select('children', Array.from({ length: 7 }, (_, n) => [n, n === 0 ? 'Без детей' : `${n} ${plural(n, 'ребёнок', 'ребёнка', 'детей')}`]), current.children_ages.length);
    const ageFields = node('div', { class: 'editor-ages' });
    let ages = current.children_ages.map(String);
    const renderAges = () => {
      const count = Number(childCount.value);
      ages = Array.from({ length: count }, (_, i) => ages[i] ?? '');
      ageFields.replaceChildren(...ages.map((age, i) => {
        const control = select(`child-${i}`, [['', 'Выберите'], ...Array.from({ length: 18 }, (_, n) => [n, `${n} ${plural(n, 'год', 'года', 'лет')}`])], age, { required: true });
        control.addEventListener('change', () => { ages[i] = control.value; });
        return field(`Возраст ребёнка ${i + 1}`, control);
      }));
      ageFields.hidden = count === 0;
    };
    childCount.addEventListener('change', renderAges);
    renderAges();
    const budget = input('budget', current.budget, { type: 'number', min: 1000, max: 10000000, step: 1, inputmode: 'numeric', placeholder: 'Без ограничения' });
    const scope = select('budget_scope', [['trip', 'На всю поездку'], ['hotel', 'На проживание']], current.budget_scope);
    const transport = select('transport', [['flight', 'Самолёт'], ['train', 'Поезд'], ['self', 'Своим ходом']], current.transport);
    const origin = input('origin', current.origin, { type: 'text', maxlength: 100, required: true, autocomplete: 'off' });
    const travelNote = node('p', { class: 'editor-hint editor-travel-note' });
    const syncTransport = () => {
      origin.disabled = transport.value === 'self';
      origin.required = transport.value !== 'self';
      travelNote.textContent = transport.value === 'self' ? 'Самостоятельная дорога и трансфер не входят в расчёт.' : 'В демокаталоге доступны маршруты из Москвы.';
    };
    transport.addEventListener('change', syncTransport);
    syncTransport();
    const error = node('p', { class: 'editor-error', role: 'alert', tabindex: '-1', hidden: true });
    const close = () => { if (!saving) dialog.close(); };
    const cancel = button('Отмена', close, 'button button-secondary');
    const submit = node('button', { type: 'submit', class: 'button editor-submit' }, 'Применить изменения', icon('arrow', 18));
    const closeButton = button(icon('close'), close, 'dialog-close', { 'aria-label': 'Закрыть условия поездки' });
    const fields = node('fieldset', { class: 'editor-fields' },
      node('legend', { class: 'sr-only' }, 'Основные условия'),
      node('div', { class: 'editor-date-grid' }, field('Направление', destination), field('Дата заезда', checkIn), field('Ночей', length)),
      node('div', { class: 'editor-grid' }, field('Взрослых', adults, 'От 18 лет'), field('Детей', childCount, 'До 17 лет включительно')), ageFields,
      node('div', { class: 'editor-grid' }, field('Бюджет, ₽', budget), field('На что рассчитан', scope)),
      node('div', { class: 'editor-grid' }, field('Как добраться', transport), field('Город отправления', origin)), travelNote);
    const form = node('form', { class: 'editor-form', onsubmit: async event => {
      event.preventDefault();
      if (saving) return;
      error.hidden = true;
      let patch;
      try {
        patch = requirementsPatch(current, { destination: destination.value, check_in: checkIn.value, nights: length.value, adults: adults.value, children_ages: ages, budget: budget.value, budget_scope: scope.value, transport: transport.value, origin: origin.value });
      } catch (problem) { error.textContent = problem.message; error.hidden = false; error.focus(); return; }
      if (!Object.keys(patch).length) { close(); return; }
      saving = true;
      fields.disabled = true; cancel.disabled = true; closeButton.disabled = true; submit.disabled = true;
      submit.textContent = 'Пересчитываем поездку…';
      dialog.setAttribute('aria-busy', 'true');
      const updated = await patchRequirements(patch);
      saving = false;
      if (updated) {
        dialog.close();
        document.querySelector('[data-view-heading]')?.focus({ preventScroll: true });
        window.scrollTo({ top: 0, behavior: 'instant' });
      } else {
        fields.disabled = false; cancel.disabled = false; closeButton.disabled = false; submit.disabled = false;
        submit.replaceChildren('Попробовать снова', icon('arrow', 18));
        dialog.setAttribute('aria-busy', 'false');
        error.textContent = state.error || 'Не удалось сохранить изменения. Попробуйте ещё раз.';
        error.hidden = false;
        error.focus();
      }
    } }, fields, node('p', { class: 'editor-preserved' }, icon('check', 17), 'Пожелания к отелю сохранятся. Проверим наличие и стоимость заново.'), error,
      node('div', { class: 'editor-actions' }, cancel, submit));
    dialog.append(node('div', { class: 'editor-shell' }, node('div', { class: 'dialog-heading' }, node('div', {}, smallLabel('Детали путешествия'), node('h2', { id: 'editor-title' }, 'Ваша поездка')), closeButton), node('p', { id: 'editor-description', class: 'editor-description' }, 'Уточните детали — остальное мы сохраним.'), form));
    dialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
    dialog.addEventListener('click', event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close(); } });
    dialog.addEventListener('close', () => { dialog.remove(); if (opener?.isConnected) opener.focus({ preventScroll: true }); else document.querySelector('#edit-conditions')?.focus({ preventScroll: true }); });
    document.body.append(dialog);
    dialog.showModal();
  }

  function conditions(requirements) {
    const r = requirements;
    const people = [`${r.adults} ${plural(r.adults, 'взрослый', 'взрослых', 'взрослых')}`];
    if (r.children_ages?.length) people.push(`${r.children_ages.length} ${plural(r.children_ages.length, 'ребёнок', 'ребёнка', 'детей')} (${r.children_ages.join(', ')} лет)`);
    const transport = { flight: 'Перелёт', train: 'Поезд', self: 'Своим ходом' }[r.transport] || 'Дорога';
    const terms = [r.destination || 'Куда — уточним', `${date(r.check_in)} · ${nights(r.nights)}`, people.join(' + '), r.budget ? `До ${money(r.budget)}${r.budget_scope === 'hotel' ? ' на отель' : ' за всё'}` : 'Бюджет не задан', `${transport}${r.origin ? ' · ' + r.origin : ''}`];
    const flags = [['breakfast', 'Завтраки'], ['pool', 'Бассейн'], ['pets', 'С питомцем'], ['refundable', 'С отменой'], ['direct_only', 'Без пересадок'], ['quiet', 'Тихий отдых'], ['accessible', 'Доступная среда']];
    const priority = key => r.preference_modes?.[key] === 'preferred' || (key === 'quiet' && !r.preference_modes?.quiet) ? 'желательно' : 'обязательно';
    flags.forEach(([key, label]) => { if (r[key]) terms.push(`${label} · ${['pets', 'accessible'].includes(key) ? 'обязательно' : priority(key)}`); });
    if (r.max_beach_m != null) terms.push(`Море до ${r.max_beach_m} м · ${priority('max_beach_m')}`);
    if (r.min_rating) terms.push(`Оценка от ${r.min_rating} · ${priority('min_rating')}`);
    if (r.stars) terms.push(`От ${r.stars} звёзд · ${priority('stars')}`);
    return node('section', { class: 'conditions', 'aria-label': 'Сохранённые условия поездки' },
      node('div', { class: 'conditions-heading' }, smallLabel('Условия поездки'), button(node('span', {}, 'Изменить условия', icon('arrow', 15)), editConditions, 'text-button edit-conditions', { id: 'edit-conditions', hidden: state.session.stage === 'booked' })),
      node('ul', { class: 'condition-list' }, terms.map((term, index) => node('li', { class: index < 5 ? 'condition-primary' : 'condition-wish' }, term))));
  }

  function sessionIntro() {
    const session = state.session;
    const assumptions = [...new Set([...(session.assumptions || []), ...(session.requirements.assumptions || [])])];
    const selectedView = session.stage === 'selected' && !state.showResults;
    const selectedPlan = selectedView ? session.selected_plan : null;
    const phase = session.stage === 'booked' ? 2 : selectedView ? 1 : 0;
    const title = session.stage === 'clarify' ? 'Уточним вашу поездку' : session.stage === 'booked' ? 'План сохранён' : selectedPlan ? selectedPlan.hotel.name : session.hotel_intent ? 'Новый план в вашем отеле' : 'Отели для вашей поездки';
    const routineReply = /^(Нашёл|Вы выбрали|Пересобрал|Сохранил отель|Эти условия уже действуют)/.test(session.assistant_message || '');
    const requiresAttention = session.clarifications?.length || session.hypothetical || !session.plans.length || !routineReply;
    const reply = node('p', {}, session.assistant_message);
    const context = session.stage !== 'booked' ? node('details', { class: 'session-context' },
      node('summary', {}, icon('check', 16), 'Как подобрали поездку', node('span', { 'aria-hidden': 'true' }, '+')),
      !requiresAttention ? reply : null,
      assumptions.length ? node('ul', {}, assumptions.map(value => node('li', {}, value))) : null,
      (session.requirements.unsupported || []).length ? node('ul', {}, session.requirements.unsupported.map(value => node('li', {}, 'Пока не можем учесть: ' + value))) : null) : null;
    return node('section', { class: `session-intro${selectedView ? ' session-intro-selected' : ''}` },
      node('ol', { class: 'journey-progress', 'aria-label': 'Этапы поездки' }, ['Подбор отелей', 'План и оформление', 'Подтверждение'].map((label, index) => node('li', { class: index === phase ? 'is-current' : index < phase ? 'is-complete' : '', 'aria-current': index === phase ? 'step' : null }, node('span', { 'aria-hidden': 'true' }, index < phase ? '✓' : `0${index + 1}`), label))),
      node('div', { class: 'session-title-row' }, node('div', {}, smallLabel(selectedView ? 'Ваш план поездки' : 'От желания к маршруту'),
        node('h1', { class: 'results-title', tabindex: '-1', 'data-view-heading': true }, title),
        selectedPlan ? node('p', { class: 'selected-location' }, `${selectedPlan.hotel.area} · ${selectedPlan.hotel.stars} звезды · оценка ${String(selectedPlan.hotel.rating).replace('.', ',')}`) : null),
        selectedPlan ? node('div', { class: 'selected-total' }, node('strong', {}, money(selectedPlan.price.total)), node('span', {}, `За всех · ${nights(selectedPlan.dates.nights)} · ${tripScope(selectedPlan)}`)) : node('span', { class: 'demo-tag' }, node('span', { class: 'status-dot' }), 'Демонстрационный подбор')),
      session.stage === 'booked' ? null : conditions(session.requirements),
      session.stage !== 'booked' && !session.clarifications?.length && requiresAttention ? node('div', { class: 'assistant-message', role: 'status' }, node('span', { class: 'assistant-mark', 'aria-hidden': 'true' }, 'О!'), reply) : null,
      session.changes?.length ? node('p', { class: 'changes-note' }, 'Обновили: ', session.changes.map(change => change.summary || change.label || change.field).join('; '), '. Остальные условия сохранены.') : null,
      session.hotel_intent && session.stage !== 'booked' && !selectedView ? node('div', { class: 'hotel-intent-note' }, node('p', {}, 'Сохраняем ', node('strong', {}, session.hotel_intent.name)), button('Рассмотреть другие отели', () => sendMessage('Покажи другие отели'), 'text-button')) : null,
      session.stage !== 'clarify' && session.clarifications?.length ? clarificationQuestions() : null,
      session.hypothetical?.total_matches > 0 ? node('div', { class: 'hypothetical-action' }, button('Применить это изменение', () => patchRequirements(session.hypothetical.patch), 'choice-chip'), node('span', {}, 'Только после нажатия изменим условия и пересчитаем предложение.')) : null,
      context);
  }

  function clarificationQuestions() {
    const questions = (state.session.clarifications || []).map(question => {
      const choices = (question.options || []).map(option => button(option.label, () => patchRequirements({ [question.field]: option.value }), 'choice-chip'));
      return node('div', { class: 'clarify-item' }, node('h2', {}, question.question), node('div', { class: 'chip-row' }, choices));
    });
    return node('div', { class: 'clarification-questions' }, questions);
  }

  function clarification() {
    return node('section', { class: 'clarify-section' }, node('div', { class: 'clarify-preface' }, node('span', { class: 'clarify-symbol', 'aria-hidden': 'true' }, icon('spark', 28)), node('p', {}, 'Пара деталей поможет подобрать подходящий вариант. Уже указанные условия сохранены.')), clarificationQuestions(),
      composer(true), node('p', { class: 'parser-note' }, parserNote()));
  }

  function stayImage(plan) {
    const hotels = (state.session?.plans || []).map(item => item.hotel);
    if (!hotels.some(hotel => hotel.id === plan.hotel.id)) hotels.push(plan.hotel);
    return assignStayImages(hotels)[plan.hotel.id];
  }

  function mealLabel(plan) { return plan.meal === 'Завтрак включён' ? 'Завтрак включён' : 'Без питания'; }

  function cancellationLabel(plan) {
    if (!plan.refundable) return 'Невозвратный тариф';
    const cutoff = /до (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})/.exec(plan.policy || '');
    return cutoff ? `Бесплатно до ${date(cutoff[1])}, ${cutoff[2]} МСК` : 'Смотрите условия тарифа';
  }

  function tripScope(plan) { return plan.transport.mode === 'self' ? 'без самостоятельной дороги' : 'с дорогой'; }

  function hotelCard(plan, index) {
    const hotel = plan.hotel;
    const badge = state.session.plan_labels?.[plan.id] || (index === 0 ? 'Подходит вашим условиям' : null);
    const factLike = /м до пляжа|рейтинг|завтрак включ|бесплатная отмена/i;
    const uniqueReasons = (plan.reasons || []).filter(reason => !factLike.test(reason));
    const mainReason = uniqueReasons[0] || (plan.preference_matches || [])[0] || (badge === 'Самая низкая цена' ? 'Самая доступная поездка в этом подборе' : (hotel.features || []).includes('pool') ? 'Бассейн на территории' : badge === 'Высокий рейтинг' ? 'Один из лучших рейтингов в подборе' : 'Соответствует обязательным условиям');
    const cheapestShown = Math.min(...state.session.plans.map(item => item.price.total));
    const premium = plan.price.total - cheapestShown;
    const compromise = (plan.compromises || []).find(value => /нужно \d.*номер/i.test(value)) || (plan.preference_compromises || [])[0] || (plan.compromises || []).find(value => !/тариф|отмен|данные|демо|питание|завтрак/i.test(value)) || (premium > 0 ? `На ${money(premium)} дороже самого доступного из показанных` : (plan.warnings || []).some(value => /раннее заселение не включено/i.test(value)) ? 'Ранний заезд не включён' : 'Личные расходы не включены');
    const selectLabel = state.session.clarifications?.length ? 'Сначала уточним условия' : state.session.hotel_intent && !state.session.selected_plan ? 'Подтвердить новый план' : 'Посмотреть план';
    return node('article', { class: 'hotel-card' },
      node('div', { class: `hotel-image hotel-image-${index}` }, node('img', { src: stayImage(plan), alt: '', loading: 'lazy', width: 1200, height: 800 }),
        node('span', { class: 'image-note' }, 'Иллюстрация демоотеля'), badge ? node('span', { class: 'recommendation' }, badge) : null),
      node('div', { class: 'hotel-body' },
        node('div', { class: 'hotel-meta' }, node('span', {}, hotel.area || 'Сочи', hotel.stars ? ` · ${hotel.stars}★` : ''), node('span', { class: 'rating' }, hotel.rating ? String(hotel.rating).replace('.', ',') : '—', node('span', { class: 'sr-only' }, ' — оценка отеля'))),
        node('h3', {}, hotel.name),
        node('dl', { class: 'stay-facts' }, [['До моря', `${hotel.beach_m} м`], ['Питание', mealLabel(plan)], ['Отмена', cancellationLabel(plan)]].map(([label, value]) => node('div', {}, node('dt', {}, label), node('dd', {}, value)))),
        node('div', { class: 'fit-list' }, node('p', {}, node('span', { 'aria-hidden': 'true' }, '✓'), mainReason)),
        node('p', { class: 'compromise' }, node('span', {}, 'Учтите: '), compromise),
        node('div', { class: 'card-bottom' }, node('p', { class: 'total-price' }, money(plan.price.total), node('span', {}, `За всех · ${nights(plan.dates.nights)} · ${tripScope(plan)}`)),
          node('details', { class: 'card-price-details' }, node('summary', {}, 'Что входит в стоимость'), node('dl', {}, [['Отель', plan.price.hotel], ['Дорога', plan.price.transport], ['Трансфер', plan.price.transfer], ['Обязательные доплаты', plan.price.extras]].map(([label, value], item) => node('div', {}, node('dt', {}, label), node('dd', {}, plan.transport.mode === 'self' && (item === 1 || item === 2) ? 'Не рассчитано' : money(value)))))),
          button(node('span', {}, selectLabel, arrow()), () => mutate(`/api/sessions/${encodeURIComponent(state.session.id)}/select`, { plan_id: plan.id, revision: state.session.revision }), 'button button-full', { disabled: state.session.clarifications?.length > 0 }))));
  }

  function suggestionButton(suggestion) {
    return button(node('span', {}, suggestion.label, suggestion.saving > 0 ? node('span', { class: 'saving' }, `−${money(suggestion.saving)}`) : null,
      suggestion.total_matches > 0 ? node('span', { class: 'saving-comparison' }, `${suggestion.total_matches} ${plural(suggestion.total_matches, 'отель', 'отеля', 'отелей')} · поездка от ${money(suggestion.min_total)}`) : null,
      suggestion.baseline_total != null && suggestion.alternative_total != null ? node('span', { class: 'saving-comparison' }, `Самая доступная поездка: ${money(suggestion.baseline_total)} → ${money(suggestion.alternative_total)}`) : null),
      () => patchRequirements(suggestion.patch || { [suggestion.field]: suggestion.value }), 'change-chip', { title: suggestion.note || null });
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
        session.counterfactuals?.length ? node('p', { class: 'economy-note' }, `Сравниваем минимальные цены до и после изменения. ${session.hotel_intent ? 'Сохраняем выбранный отель.' : 'Отель может измениться.'} Экономия разных вариантов не складывается.`) : node('p', { class: 'economy-note' }, 'Проверяем изменения одного условия, затем пары. Сначала — меньше изменений, затем ниже полная стоимость. Это проверенные варианты в демо-каталоге.')),
      node('div', { class: 'chip-row' }, all.map(suggestionButton), counterWithoutValue.map(counter => button(node('span', {}, counter.label, counter.saving > 0 ? node('span', { class: 'saving' }, `−${money(counter.saving)}`) : null), () => sendMessage(counter.label), 'change-chip'))));
  }

  function results() {
    const session = state.session;
    return node('div', { class: 'results-content' },
      node('div', { class: 'section-heading' }, node('h2', {}, session.plans.length ? session.hotel_intent ? 'Предложение пересчитано' : 'Сравните и выберите' : 'Условия пока не совпали'),
        session.plans.length ? node('p', {}, `${session.plans.length} ${plural(session.plans.length, 'вариант', 'варианта', 'вариантов')} из ${session.total_matches} подходящих`) : null),
      session.plans.length ? node('div', { class: `hotel-grid${session.plans.length === 1 ? ' hotel-grid-single' : ''}` }, session.plans.slice(0, 3).map(hotelCard)) : node('div', { class: 'empty-state' },
        node('span', { class: 'empty-symbol', 'aria-hidden': 'true' }, '↝'), node('h3', {}, session.hotel_intent ? 'Проверили сохранённый отель' : 'Точных совпадений пока нет'), node('p', {}, session.diagnostic?.message || 'В демонстрационном каталоге нет предложений для этих условий.'),
        session.hotel_alternative ? button(`${session.hotel_alternative.label} · ${session.hotel_alternative.total_matches}`, () => sendMessage('Покажи другие отели'), 'button button-secondary') : null),
      alternatives(), composer(true), node('p', { class: 'parser-note' }, parserNote()), history());
  }

  function priceBreakdown(plan) {
    const selfTravel = plan.transport.mode === 'self';
    const entries = [['Проживание', plan.price.hotel], ['Дорога туда и обратно', plan.price.transport], ['Трансфер', plan.price.transfer], ['Дополнительно', plan.price.extras]];
    return node('div', { class: 'price-breakdown' },
      node('h3', {}, selfTravel ? 'Стоимость включённых услуг' : 'Вся поездка, одна сумма'),
      selfTravel ? node('p', { class: 'muted small price-exclusion-note' }, 'Стоимость самостоятельной дороги и трансфера не рассчитана и не включена в сумму.') : null,
      node('dl', {}, entries.map(([label, value], index) => node('div', {}, node('dt', {}, label), node('dd', {}, selfTravel && (index === 1 || index === 2) ? 'Не рассчитано' : money(value))))),
      node('div', { class: 'breakdown-total' }, node('span', {}, 'Итого за всех'), node('strong', {}, money(plan.price.total))),
      node('p', { class: 'muted small' }, `${nights(plan.dates.nights)} · ${plan.guests.adults} взр.${plan.guests.children_ages.length ? ` + ${plan.guests.children_ages.length} дет.` : ''} · рубли`));
  }

  function tripDetails(plan, showTitle = true) {
    const transport = plan.transport;
    const days = new Map();
    (plan.timeline || []).forEach(item => {
      const day = item.time.slice(0, 10);
      if (!days.has(day)) days.set(day, []);
      days.get(day).push(item);
    });
    const secondaryReasons = (plan.reasons || []).filter(reason => !/м до пляжа|рейтинг|завтрак включ/i.test(reason));
    const compromises = (plan.compromises || []).filter(value => !/невозвратный тариф/i.test(value));
    const warnings = (plan.warnings || []).filter(value => value !== plan.data_label && !/демонстрационн[а-я]* (отел|цены|данные)|все объекты/i.test(value));
    return node('div', { class: 'trip-detail-content' },
      node('figure', { class: 'plan-hero' }, node('img', { src: stayImage(plan), alt: '', width: 1200, height: 800 }), node('figcaption', { class: 'image-note' }, 'Иллюстрация демоотеля')),
      node('section', { class: 'detail-summary' }, showTitle ? node('h2', {}, plan.hotel.name) : null,
        node('p', { class: 'detail-location' }, `${plan.hotel.area} · ${plan.hotel.stars}★ · оценка ${String(plan.hotel.rating).replace('.', ',')} · ${plan.hotel.beach_m} м до моря`),
        node('p', { class: 'hotel-description' }, plan.hotel.description.replace(/^Вымышленный отель в районе [^.]+\.\s*/, '')),
        node('dl', { class: 'detail-facts' },
          node('div', {}, node('dt', {}, 'Когда'), node('dd', {}, `${date(plan.dates.check_in)} — ${date(plan.dates.check_out)} · ${nights(plan.dates.nights)}`)),
          node('div', {}, node('dt', {}, 'Проживание'), node('dd', {}, `${plan.room.name} · ${plan.room.rooms} ${plural(plan.room.rooms, 'номер', 'номера', 'номеров')}`)),
          node('div', {}, node('dt', {}, 'Гости'), node('dd', {}, `${plan.guests.adults} взрослых${plan.guests.children_ages.length ? ` · дети ${plan.guests.children_ages.join(', ')} лет` : ''}`)),
          node('div', {}, node('dt', {}, 'Питание'), node('dd', {}, mealLabel(plan))),
          node('div', {}, node('dt', {}, 'Дорога'), node('dd', {}, transport.title)),
          node('div', {}, node('dt', {}, 'Трансфер'), node('dd', {}, plan.transfer.title))),
        node('div', { class: 'rate-policy' }, node('strong', {}, 'Отмена'), node('p', { class: 'cancellation-policy' }, readablePolicy(plan.policy))),
        secondaryReasons.length ? node('details', { class: 'detail-reasons route-details' }, node('summary', {}, 'Почему подходит вашим пожеланиям'), node('ul', {}, secondaryReasons.map(reason => node('li', {}, reason)))) : null,
        compromises.length ? node('div', { class: 'detail-compromises' }, node('h3', {}, 'Главное учесть'), node('ul', {}, compromises.map(value => node('li', {}, value)))) : null),
      node('section', { class: 'timeline-section' }, node('h3', {}, 'Маршрут поездки'),
        [...days].map(([day, items]) => node('section', { class: 'route-group' }, node('h4', {}, date(day)),
          node('ol', { class: 'timeline' }, items.map(item => node('li', {}, node('time', { class: 'timeline-time', datetime: item.time }, item.time.slice(11, 16)), node('strong', {}, item.title)))))),
        node('details', { class: 'route-details' }, node('summary', {}, 'Подробности дороги и трансферов'), node('ul', {}, (plan.timeline || []).map(item => node('li', {}, node('strong', {}, `${dateTime(item.time)} · ${item.title}`), node('p', {}, item.detail))))),
        node('div', { class: 'policy-note' }, node('h3', {}, 'Важно о поездке'), warnings.map(warning => node('p', {}, warning)))));
  }

  function checkoutForm(plan) {
    const needsAnswer = state.session.request_status === 'needs_clarification' || state.session.clarifications?.length > 0;
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
        node('h3', {}, 'Оформление поездки'), node('p', { class: 'small muted' }, 'Демозаявка без оплаты.'),
        node('label', { for: name.id }, 'Ваше имя'), name, node('label', { for: email.id }, 'Электронная почта'), email,
        node('p', { class: 'form-note' }, 'Используйте тестовые данные. Письмо не отправляется.'),
        node('label', { class: 'checkbox-label', for: agreement.id }, agreement, node('span', {}, 'Подтверждаю демооформление: без реальной брони и списания денег.')),
        needsAnswer ? node('p', { class: 'form-note', role: 'status' }, 'Сначала ответьте на уточнение выше. Текущий вариант сохранён для сравнения; состав и стоимость могут измениться.') : null,
        node('button', { type: 'submit', class: 'button button-full checkout-submit', disabled: needsAnswer }, needsAnswer ? 'Сначала уточним условия' : 'Оформить демозаявку ↗')));
  }

  function selected() {
    const plan = state.session.selected_plan;
    if (!plan) return results();
    return node('div', { class: 'selected-content' }, button('← К вариантам поездки', () => { state.showResults = true; render(); document.querySelector('.section-heading')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 'back-button'),
      node('div', { class: 'mobile-checkout-link' }, node('p', {}, money(plan.price.total), node('span', {}, plan.transport.mode === 'self' ? 'За всех · без самостоятельной дороги' : 'За всю поездку · за всех')), node('a', { href: '#checkout', class: 'button' }, 'К оформлению ↓')),
      node('div', { class: 'selected-layout' }, tripDetails(plan, false), checkoutForm(plan)), composer(true), node('p', { class: 'parser-note' }, parserNote()), history());
  }

  function downloadOrder() {
    const order = state.session.order;
    if (!order) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(order, null, 2)], { type: 'application/json;charset=utf-8' }));
    const link = node('a', { href: url, download: `rivane-${String(order.reference).replace(/[^a-zA-Z0-9А-Яа-я_-]/g, '')}.json` });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function booked() {
    const order = state.session.order;
    if (!order) return selected();
    const plan = order.plan;
    return node('section', { class: 'booked-section' },
      node('div', { class: 'confirmation-main' }, node('div', {}, node('div', { class: 'success-mark', 'aria-hidden': 'true' }, '✓'), node('h2', {}, 'Ваша демозаявка готова'), node('p', { class: 'order-reference' }, '№ ', order.reference),
        node('p', { class: 'booked-description' }, 'План и условия сохранены. Реальная бронь не создана, деньги не списаны, письмо не отправляется. Подтверждение можно скачать или найти в «Моих поездках».'),
        node('div', { class: 'order-actions' }, button('Скачать заявку ↓', downloadOrder), button('Спланировать ещё поездку ↗', resetTrip, 'button button-secondary'))),
        node('figure', { class: 'confirmation-photo' }, node('img', { src: stayImage(plan), alt: '', width: 1200, height: 800 }), node('figcaption', { class: 'image-note' }, 'Иллюстрация демоотеля'))),
      node('div', { class: 'order-overview' }, node('div', {}, node('span', {}, 'Поездка'), node('strong', {}, plan.hotel.name), node('p', {}, `${date(plan.dates.check_in)} — ${date(plan.dates.check_out)}`)),
        node('div', {}, node('span', {}, 'На имя'), node('strong', {}, order.traveler_name), node('p', {}, order.email)),
        node('div', {}, node('span', {}, 'За всех'), node('strong', {}, money(order.total)), node('p', {}, 'Ничего не списано'))),
      node('details', { class: 'order-details' }, node('summary', {}, 'Весь маршрут и стоимость'), node('div', { class: 'selected-layout' }, tripDetails(plan), priceBreakdown(plan))));
  }

  function history() {
    const messages = state.session.messages || [];
    if (!messages.length) return null;
    return node('details', { class: 'history' }, node('summary', {}, 'История пожеланий', node('span', { 'aria-hidden': 'true' }, ' +')),
      node('ol', {}, messages.map(message => node('li', { class: message.role === 'user' ? 'history-user' : 'history-assistant' }, node('strong', {}, message.role === 'user' ? 'Вы' : 'O!RIVANE'), node('p', {}, message.content)))));
  }

  function render() {
    main.replaceChildren();
    main.setAttribute('aria-busy', String(state.pending));
    document.body.classList.toggle('has-session', Boolean(state.session));
    newTrip.hidden = !state.session;
    newTrip.disabled = state.pending;
    document.querySelector('#how-link').hidden = false;
    closeNavigation();
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
  document.querySelector('#home-link').addEventListener('click', event => { event.preventDefault(); resetTrip(); });
  document.querySelectorAll('[data-section]').forEach(link => link.addEventListener('click', event => { event.preventDefault(); navigateSection(link.dataset.section); }));
  document.querySelector('#trips-link').addEventListener('click', showTrips);
  document.querySelector('#search-trip').addEventListener('click', () => { if (!state.pending) { if (state.session) resetTrip(); document.querySelector('#trip-message')?.focus(); } });
  document.querySelector('#mobile-menu').addEventListener('click', event => { if (state.pending) return; const open = document.body.classList.toggle('menu-open'); event.currentTarget.setAttribute('aria-expanded', String(open)); event.currentTarget.setAttribute('aria-label', open ? 'Закрыть навигацию' : 'Открыть навигацию'); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeNavigation(); });
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
    if (results[1].status === 'fulfilled') { state.session = results[1].value; if (state.session) rememberTrip(state.session); }
    else {
      state.error = results[1].reason.status === 404 ? 'Предыдущая поездка больше недоступна. Расскажите о ней ещё раз — соберём новый план.' : 'Не удалось восстановить поездку. Обновите страницу, чтобы попробовать снова.';
      if (results[1].reason.status === 404) saveSession();
    }
    state.restoring = false;
    render();
  }
  boot();
})();
