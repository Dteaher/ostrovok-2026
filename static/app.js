import { requirementsPatch, assignStayImages, readablePolicy, restoreStayImages, journeyView, nextJourneyHash, preserveMessageDraft, priceAudience, travelLabels, priceEntries, readableDates, preferenceLabels, offerComparison } from './trip-ui.js?v=20261028-chat';
import { ExplanationLoader } from './explanation.js?v=20261028-deadline';
import { downloadPlan } from './plan-document.js?v=20261028-plan';
import { DestinationLoader, validExternal } from './destination-context.js?v=20261028-data';

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
  const state = { session: null, config: null, pending: false, restoring: false, error: '', draft: '', clarificationDate: '', checkout: { name: '', email: '', accepted: false } };
  state.chatOpen = window.matchMedia('(min-width: 1100px)').matches;
  let destinationData = null;
  let destinationDataKey = null;
  const destinationLoader = new DestinationLoader({ request, current: () => state.session,
    update: data => {
      destinationData = data;
      destinationDataKey = `${state.session?.id}:${state.session?.revision}`;
      document.querySelector('.destination-context')?.replaceWith(destinationPanel());
    }
  });

  function draftKey() { return `rivane-draft-${state.session?.id || 'new'}`; }
  function saveDraft() {
    try { localStorage.setItem(draftKey(), state.draft); } catch { /* Editing works without storage. */ }
  }
  function restoreDraft() {
    try { state.draft = localStorage.getItem(draftKey()) || ''; } catch { state.draft = ''; }
  }
  const explanations = new ExplanationLoader({
    getSession: () => state.session,
    request,
    apply: agent => {
      if (state.pending || !state.session) return;
      state.session.agent = agent;
      const previous = document.querySelector('.concierge-notes');
      if (!previous) return;
      const open = previous.querySelector('details')?.open;
      const focused = previous.contains(document.activeElement) ? document.activeElement.textContent : null;
      const panel = conciergePanel();
      if (!panel) return;
      panel.querySelector('details').open = open;
      previous.replaceWith(panel);
      const mode = document.querySelector('.chat-mode');
      const connected = agent.mode === 'llm' || state.session.parser_mode === 'llm';
      if (mode) {
        mode.textContent = connected ? 'ИИ подключён · по данным поездки' : 'ИИ недоступен · основные команды работают';
        mode.classList.toggle('is-connected', connected);
      }
      if (agent.mode === 'llm') {
        state.messageRetry = false;
        document.querySelector('.chat-retry')?.remove();
      }
      if (focused) [...panel.querySelectorAll('summary, button')].find(element => element.textContent === focused)?.focus({ preventScroll: true });
      announce(agent.mode === 'llm' ? 'Персональное объяснение готово.' : 'Проверенные факты доступны. Можно продолжать подбор.');
    }
  });
  let imageSession = null;
  let imageCache = {};
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
      check: 'm4 12 5 5L20 6',
      calendar: 'M4 5h16v16H4Z M8 2v6 M16 2v6 M4 10h16 M8 14h2 M14 14h2 M8 18h2'
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
    const entry = { id: session.id, destination: session.requirements.destination || 'Новое путешествие', date: session.requirements.check_in, stage: session.stage, title: plan?.hotel.name || 'Ваш персональный подбор', total: session.order?.total || plan?.price.total || null, thumbnail: plan ? stayImage(plan) : null, images: { ...imageCache } };
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
    dialog.append(node('div', { class: 'dialog-heading' }, node('div', {}, smallLabel('Вернёмся к вашим планам'), node('h2', { id: 'trips-title' }, 'Мои поездки')), button(icon('close'), close, 'dialog-close', { 'aria-label': 'Закрыть мои поездки' })), node('p', { class: 'dialog-description' }, 'Подборки и сохранённые планы в этом браузере.'), notice, list);
    if (!trips.length) list.append(node('div', { class: 'trips-empty' }, icon('bag', 40), node('h3', {}, 'Ваша первая история ещё впереди'), node('p', {}, 'Расскажите об отдыхе — здесь останутся ваши подборы и планы.'), button('Начать путешествие', () => { close(); seedIdea(''); }, 'button')));
    trips.forEach(trip => {
      const thumbnail = typeof trip.thumbnail === 'string' && /^\/static\/media\/stays\/demo-(coastal|garden|room|courtyard)\.webp$/.test(trip.thumbnail) ? trip.thumbnail : '/static/media/stays/demo-garden.webp';
      const action = button(node('span', { class: 'saved-trip-inner' }, node('span', { class: 'saved-trip-thumbnail' }, node('img', { src: thumbnail, alt: '', width: 120, height: 90, loading: 'lazy' })), node('span', { class: 'saved-trip-copy' }, node('span', { class: 'saved-trip-status' }, trip.stage === 'booked' ? 'План сохранён' : 'Подборка'), node('strong', {}, trip.title), node('span', {}, `${trip.destination} · ${date(trip.date)}`)), node('span', { class: 'saved-trip-price' }, trip.total ? money(trip.total) : 'Продолжить', icon('arrow'))), async () => {
        list.querySelectorAll('button').forEach(control => { control.disabled = true; });
        notice.textContent = 'Возвращаем ваш план…';
        try {
          const restored = await request(`/api/sessions/${encodeURIComponent(trip.id)}`);
          if (!dialog.open || !dialog.isConnected) return;
          if (state.session?.id !== restored.id) { state.checkout = { name: '', email: '', accepted: false }; state.clarificationDate = ''; }
          explanations.cancel();
          state.session = restored;
          state.error = ''; restoreDraft();
          window.history.replaceState(null, '', restored.stage === 'booked' ? '#confirmation' : restored.stage === 'selected' ? '#trip' : '#options');
          saveSession(); close(); render(); window.scrollTo({ top: 0, behavior: 'smooth' });
          document.querySelector('[data-view-heading]')?.focus();
          void explanations.load();
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
    explanations.cancel();
    state.pending = true;
    state.error = '';
    let updated = null;
    const previousHash = location.hash;
    const previousDraftKey = draftKey();
    setPending(true);
    announce(pendingLabel());
    try {
      const session = await request(path, { method, body: JSON.stringify(body) });
      if (session.selected_plan?.id !== state.session?.selected_plan?.id) state.checkout.accepted = false;
      state.session = session;
      updated = session;
      const hash = nextJourneyHash(session, previousHash, path.endsWith('/select'));
      window.history[path.endsWith('/select') ? 'pushState' : 'replaceState'](null, '', hash);
      if (body.message) state.messageRetry = preserveMessageDraft(session);
      if (body.message && state.draft === body.message && !state.messageRetry) {
        state.draft = '';
        try { localStorage.removeItem(previousDraftKey); } catch { /* Storage is optional. */ }
      }
      saveDraft();
      saveSession();
      announce(session.stage === 'booked' ? 'План сохранён в «Моих поездках».' : 'План обновлён.');
    } catch (error) {
      if (error.status === 409 && state.session) {
        try {
          state.session = await request(`/api/sessions/${encodeURIComponent(state.session.id)}`);
          if (journeyView(state.session, location.hash) !== 'checkout' && location.hash === '#checkout') window.history.replaceState(null, '', '#trip');
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
        else if (body.message && state.chatOpen) {
          document.querySelector('#refine-message')?.focus({ preventScroll: true });
        } else {
          document.querySelector('[data-view-heading]')?.focus({ preventScroll: true });
          window.scrollTo({ top: 0, behavior: 'instant' });
        }
      }
    }
    void explanations.load();
    return updated;
  }

  function pendingLabel() {
    const text = (state.draft || '').toLowerCase();
    if (/сравни|отлич/.test(text)) return 'Сравниваем варианты…';
    if (/почему|объясни|подробнее/.test(text)) return 'Готовим объяснение…';
    if (main.querySelector('.checkout-submit')) return 'Сохраняем ваш план…';
    return state.session ? 'Перепроверяем условия и стоимость…' : 'Подбираем поездку…';
  }

  function setPending(pending) {
    main.setAttribute('aria-busy', String(pending));
    newTrip.disabled = pending;
    for (const control of main.querySelectorAll('button:not(.chat-toggle):not(.chat-close), textarea, input, select')) control.disabled = pending;
    const submit = main.querySelector('.composer-submit');
    if (submit) {
      submit.classList.toggle('is-loading', pending);
      submit.textContent = pending ? pendingLabel() : state.session?.plans?.length || state.session?.selected_plan ? 'Применить пожелание' : 'Показать поездки';
    }
    const checkout = main.querySelector('.checkout-submit');
    if (checkout && pending) checkout.textContent = 'Сохраняем в «Мои поездки»…';
    const dateSubmit = main.querySelector('.clarify-date-submit');
    if (dateSubmit && pending) dateSubmit.textContent = 'Подбираем…';
    if (pending && state.session && !main.querySelector('.concierge-working')) {
      main.append(node('div', { class: 'concierge-working', 'aria-hidden': 'true' }, icon('spark', 18), node('span', {}, pendingLabel())));
    }
  }

  function sendMessage(message) {
    const cleaned = message.trim();
    if (!cleaned || state.pending) return;
    state.draft = cleaned;
    saveDraft();
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
      ? 'Проверьте распознанные даты, гостей и пожелания перед выбором.'
      : 'Понимаем основные условия поездки. Проверьте даты, гостей и пожелания перед выбором.';
  }

  function composer(compact = false) {
    const clarifying = compact && state.session?.stage === 'clarify';
    const input = node('textarea', {
      id: compact ? 'refine-message' : 'trip-message', name: 'message', rows: 2,
      maxlength: '3000', required: true, 'aria-label': compact ? 'Что изменить в поездке' : 'Расскажите о своей поездке',
      placeholder: clarifying ? 'Например: «С 15 ноября на 5 ночей, до 120 000 ₽»' : compact ? 'Например: «На ночь короче, отель оставь»' : 'Сочи, с 15 ноября на неделю, вдвоём, до 160 тысяч. Завтрак желателен.',
      oninput: event => { state.draft = event.target.value; saveDraft(); },
      onkeydown: event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); sendMessage(input.value); } }
    });
    input.value = state.draft;
    return node('form', { class: `composer ${compact ? 'composer-compact' : 'hero-composer'}`, onsubmit: event => { event.preventDefault(); sendMessage(input.value); } },
      !compact ? node('span', { class: 'composer-emblem' }, icon('spark', 26)) : null,
      node('label', { for: input.id, class: 'composer-label' }, clarifying ? 'Уточните условия поездки' : compact ? 'Спросите или уточните поездку' : 'Какую поездку вы задумали?'),
      input,
      node('div', { class: 'composer-bottom' }, node('span', { class: 'composer-hint' }, compact ? 'Остальные пожелания сохраним' : 'Куда, когда, с кем и что для вас важно'),
        node('button', { type: 'submit', class: 'button composer-submit' }, compact ? node('span', {}, clarifying ? 'Продолжить подбор' : 'Отправить', icon('arrow', 18)) : node('span', {}, 'Спланировать путешествие', icon('arrow')))));
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
      ['02', 'Выберите поездку', 'Сравните отели вместе с перелётом или поездом и трансфером.'],
      ['03', 'План под вас', 'Измените пожелания одной фразой. Остальные условия сохранятся.'],
      ['04', 'Сохраните свой вариант', 'План останется в «Моих поездках» в этом браузере.']
    ];
    return node('div', { class: 'landing enter' },
      node('section', { class: 'lux-hero', 'aria-labelledby': 'hero-title' },
        node('img', { class: 'lux-hero-image', src: '/static/media/rivane/hero-sochi.webp', alt: 'Морской вокзал и яхты в порту Сочи.', width: 2400, height: 1600, fetchpriority: 'high' }),
        node('div', { class: 'lux-hero-shade' }),
        node('div', { class: 'lux-hero-inner wrap' },
          node('div', { class: 'lux-intro' }, smallLabel('Путешествия по Большому Сочи'),
            node('h1', { id: 'hero-title', tabindex: '-1', 'data-view-heading': true }, 'Ваш отдых в Сочи,', node('br'), 'который начинается', node('br'), node('em', {}, 'с одного желания')),
            node('p', { class: 'lux-description' }, 'Отель, перелёт или поезд и трансфер — в одном плане. ', node('span', {}, 'Опишите отдых своими словами: сравним варианты и покажем общую стоимость.'))),
          node('aside', { class: 'hero-manifesto', 'aria-label': 'Что входит в план поездки' }, smallLabel('В одном плане'),
            node('ul', { class: 'hero-plan-services' }, ['Отель', 'Перелёт или поезд', 'Трансфер'].map(label => node('li', {}, icon('check', 17), label))),
            node('span', { class: 'manifesto-rule' }),
            node('div', { class: 'hero-facts' }, node('div', {}, node('strong', {}, '20'), node('span', {}, 'демоотелей')), node('div', {}, node('strong', {}, '6'), node('span', {}, 'районов Сочи')))),
          node('div', { class: 'lux-search' }, composer(),
            node('div', { class: 'theme-chips', id: 'inspiration', 'aria-label': 'Идеи для путешествия' }, themes.map(([name, label, prompt]) => button(node('span', {}, icon(name), label), () => sendMessage(prompt), 'example-button theme-chip'))),
            node('p', { class: 'hero-demo-note' }, 'Сохраните план в этом браузере. Без бронирования и оплаты.'))),
        node('p', { class: 'hero-photo-credit' }, 'Сочи · Морской вокзал')),
      node('section', { class: 'destinations-section wrap', id: 'destinations', 'aria-labelledby': 'destinations-title' },
        node('div', { class: 'destination-heading' }, node('div', {}, smallLabel('Откройте Большой Сочи'), node('h2', { id: 'destinations-title' }, 'Идеи для вашего следующего путешествия')),
          button(node('span', {}, 'Помогите выбрать', icon('arrow')), () => seedIdea('Хочу в Большой Сочи, но пока не знаю, какой район выбрать. Важны море и спокойный отдых.'), 'outline-button')),
        node('div', { class: 'destination-grid' }, destinations.map(destination => button(node('span', { class: 'destination-card-content' },
          node('img', { src: `/static/media/rivane/${destination.image}.webp`, alt: '', width: 600, height: 500, loading: 'lazy' }),
          node('span', { class: 'destination-copy' }, node('span', { class: 'destination-name' }, destination.label), node('span', { class: 'destination-description' }, destination.description)),
          node('span', { class: 'destination-arrow' }, icon('arrow'))), () => seedIdea(`${destination.prompt} с ${futureDate()} на неделю вдвоём, до 160 тысяч, с завтраком`), 'destination-card', { 'aria-label': `Спланировать отдых: ${destination.name}` }))),
        node('p', { class: 'destination-note' }, 'Один регион — разные впечатления. Фотографии районов иллюстративные.')),
      node('section', { class: 'journey-section wrap', id: 'how', 'aria-labelledby': 'how-title' },
        node('div', { class: 'journey-heading' }, smallLabel('Всё сложится в путешествие'), node('h2', { id: 'how-title' }, 'От первого «хочу»', node('em', {}, ' до вашего плана.'))),
        node('ol', { class: 'journey-steps' }, steps.map(([number, title, description]) => node('li', {}, node('span', { class: 'step-number' }, number), node('h3', {}, title), node('p', {}, description)))),
        node('p', { class: 'journey-parser-note' }, parserNote())));
  }

  function editConditions() {
    if (state.pending || !state.session || state.session.stage === 'booked' || document.querySelector('.trip-editor')) return;
    const current = state.session.requirements;
    const opener = document.activeElement;
    let saving = false, applied = false;
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
    const scope = select('budget_scope', [['trip', 'Вся поездка'], ['hotel', 'Только отель']], current.budget_scope);
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
        applied = true;
        dialog.close();
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
    dialog.addEventListener('close', () => {
      dialog.remove();
      if (applied) {
        document.querySelector('[data-view-heading]')?.focus({ preventScroll: true });
        window.scrollTo({ top: 0, behavior: 'instant' });
      } else if (opener?.isConnected) opener.focus({ preventScroll: true });
      else document.querySelector('#edit-conditions')?.focus({ preventScroll: true });
    });
    document.body.append(dialog);
    dialog.showModal();
  }

  function conditions(requirements) {
    const r = requirements;
    const people = [`${r.adults} ${plural(r.adults, 'взрослый', 'взрослых', 'взрослых')}`];
    if (r.children_ages?.length) people.push(`${r.children_ages.length} ${plural(r.children_ages.length, 'ребёнок', 'ребёнка', 'детей')} (${r.children_ages.join(', ')} лет)`);
    const transport = { flight: 'Перелёт', train: 'Поезд', self: 'Своим ходом' }[r.transport] || 'Дорога';
    const clarifying = state.session.stage === 'clarify';
    const terms = [r.destination || 'Куда — уточним', clarifying && !r.check_in ? nights(r.nights) : `${date(r.check_in)} · ${nights(r.nights)}`, people.join(' + '), r.budget ? `До ${money(r.budget)}${r.budget_scope === 'hotel' ? ' на отель' : ' за всё'}` : clarifying ? null : 'Бюджет не задан', `${transport}${r.origin ? ' · ' + r.origin : ''}`].filter(Boolean);
    const wishes = preferenceLabels(r);
    return node('section', { class: 'conditions', 'aria-label': 'Сохранённые условия поездки' },
      node('div', { class: 'condition-main' }, node('ul', { class: 'condition-list' }, terms.map((term, index) => node('li', { class: 'condition-primary' }, index === 0 ? icon('sea', 19) : null, term))),
        button(node('span', {}, 'Изменить', icon('arrow', 16)), editConditions, 'text-button edit-conditions', { id: 'edit-conditions', 'aria-label': 'Изменить условия', hidden: state.session.stage === 'booked' })),
      wishes.length ? node('ul', { class: 'preference-strengths', 'aria-label': 'Важность условий' }, wishes.map(wish => node('li', {}, wish))) : null);
  }

  function sessionIntro() {
    const session = state.session;
    const view = journeyView(session, location.hash);
    const selectedView = view === 'trip';
    const selectedPlan = selectedView ? session.selected_plan : null;
    const phase = view === 'confirmation' ? 3 : view === 'checkout' ? 2 : selectedView ? 1 : 0;
    const title = session.stage === 'clarify' ? 'Уточним вашу поездку' : view === 'confirmation' ? 'Ваш план сохранён' : view === 'checkout' ? 'Сохраните поездку' : selectedPlan ? selectedPlan.hotel.name : session.hypothetical ? 'Сравнение условий' : session.change_receipt ? 'План пересчитан' : session.hotel_intent && !session.selected_plan ? 'Ваш обновлённый вариант' : 'Выберите поездку';
    const routineReply = /^(Нашёл|Вы выбрали|Пересобрал|Сохранил отель|Эти условия уже действуют|Восстановил сохранённые условия)/.test(session.assistant_message || '');
    const requiresAttention = session.clarifications?.length || session.hypothetical || !session.plans.length || !routineReply;
    const reply = node('p', {}, readableDates(session.assistant_message).replace(/AI не успел ответить за отведённое время\.[\s\S]*/, 'ИИ задерживается. Условия распознаны локально — проверьте их перед выбором.'));
    const steps = ['Выбор поездки', 'Ваш план', 'Сохранение', 'Готово'];
    return node('section', { class: `session-intro${selectedView ? ' session-intro-selected' : ''}` },
      node('ol', { class: 'journey-progress', 'aria-label': 'Этапы поездки' }, steps.map((label, index) => node('li', { class: index === phase ? 'is-current' : index < phase ? 'is-complete' : '', 'aria-current': index === phase ? 'step' : null }, node('span', { 'aria-hidden': 'true' }, index < phase ? '✓' : `0${index + 1}`), index < phase && view !== 'confirmation' && index < 2 ? button(label, () => navigateJourney(index === 0 ? '#options' : '#trip'), 'progress-back', { 'aria-label': index === 0 ? 'К вариантам поездки' : 'Назад к поездке' }) : label))),
      view === 'clarify' ? null : node('div', { class: 'session-title-row' }, node('div', {}, smallLabel(selectedView ? 'Ваш план поездки' : 'От желания к маршруту'),
        node('h1', { class: 'results-title', tabindex: '-1', 'data-view-heading': true }, title),
        selectedPlan ? node('p', { class: 'selected-location' }, `${selectedPlan.hotel.area} · ${selectedPlan.hotel.stars}★ · ${selectedPlan.hotel.beach_m} м до моря`) : view === 'results' && session.plans.length && !session.change_receipt ? node('p', { class: 'intro-caption' }, session.plans.length > 1 ? 'Проживание и выбранный транспорт — сравните общую стоимость.' : 'Условия сохранены. Проверьте обновлённое предложение.') : view === 'checkout' ? node('p', { class: 'intro-caption' }, 'План появится в «Моих поездках» в этом браузере.') : null),
        node('span', { class: 'demo-tag' }, 'Демокаталог')),
      view === 'confirmation' || view === 'checkout' ? null : conditions(session.requirements),
      view === 'results' && session.change_receipt && !session.hypothetical ? changeReceipt(session.change_receipt) : null,
      session.hypothetical ? hypotheticalSummary(session.hypothetical) : null,
      session.stage !== 'booked' && !session.hypothetical && !session.clarifications?.length && requiresAttention && !session.agent?.requested ? node('div', { class: 'assistant-message', role: 'status' }, node('span', { class: 'assistant-mark', 'aria-hidden': 'true' }, 'О!'), reply) : null,
      session.changes?.length ? node('details', { class: 'changes-note' }, node('summary', {}, icon('check', 15), 'Условия обновлены', node('span', { 'aria-hidden': 'true' }, '+')), node('p', {}, readableDates(session.changes.map(change => change.summary || change.label || change.field).join('; ')), '. Остальные условия сохранены.')) : null,
      session.hotel_intent && view === 'results' ? node('div', { class: session.change_receipt ? 'receipt-alternative' : 'hotel-intent-note' }, !session.change_receipt ? node('p', {}, 'Сохраняем ', node('strong', {}, session.hotel_intent.name)) : null,
        session.change_receipt && !session.hypothetical ? button('Отменить правку', () => sendMessage('Верни предыдущее изменение'), 'text-button') : null,
        button('Другие отели', () => sendMessage('Покажи другие отели'), 'text-button', { 'aria-label': 'Рассмотреть другие отели' })) : null,
      session.stage !== 'clarify' && session.clarifications?.length ? clarificationQuestions() : null,
      session.hypothetical?.total_matches > 0 ? node('div', { class: 'hypothetical-action' }, button('Применить это изменение', () => patchRequirements(session.hypothetical.patch), 'choice-chip'), node('span', {}, 'Только после нажатия изменим условия и пересчитаем предложение.')) : null);
  }

  function changeReceipt(receipt) {
    const difference = receipt.after_total - receipt.before_total;
    return node('section', { class: 'change-receipt', 'aria-label': 'Результат пересчёта' },
      node('div', {}, node('strong', {}, receipt.hotel_preserved ? 'Отель сохранён' : 'Предложение обновлено'), node('span', {}, receipt.hotel_name)),
      node('div', { class: 'receipt-duration' }, receipt.before_nights !== receipt.after_nights ? `${nights(receipt.before_nights)} → ${nights(receipt.after_nights)}` : nights(receipt.after_nights), receipt.before_check_in !== receipt.after_check_in ? node('small', {}, `${date(receipt.before_check_in)} → ${date(receipt.after_check_in)}`) : null),
      node('div', { class: 'receipt-price' }, node('span', {}, node('s', {}, money(receipt.before_total)), ' → ', node('strong', {}, money(receipt.after_total))),
        node('small', {}, difference === 0 ? 'Стоимость не изменилась' : `${difference < 0 ? 'Дешевле' : 'Дороже'} на ${money(Math.abs(difference))}`)));
  }

  function hypotheticalSummary(comparison) {
    return node('section', { class: 'hypothetical-summary', 'aria-label': 'Сравнение без изменения поездки', role: 'status' },
      node('strong', {}, 'Только сравниваем — поездка не изменена'),
      comparison.total_matches ? node('dl', {},
        node('div', {}, node('dt', {}, 'Минимум сейчас'), node('dd', {}, comparison.baseline_min_total == null ? 'Нет вариантов' : money(comparison.baseline_min_total))),
        node('div', {}, node('dt', {}, 'Минимум после изменения'), node('dd', {}, money(comparison.min_total)))) : node('p', {}, comparison.diagnostic?.message || 'Для этих условий вариантов нет.'),
      node('p', {}, `${comparison.hotel_id ? 'В том же отеле. ' : 'Отель может измениться. '}Сравниваем минимальные тарифы, а не доплату к выбранному предложению.`));
  }

  function journeyCommand() {
    const chosen = Boolean(state.session.hotel_intent);
    const examples = chosen ? [['На ночь короче', 'Оставь этот отель, но сократи поездку на день'], ['Сначала сравнить', 'А если сократить поездку на день?']] : [['Сравнить варианты', 'Сравни первый и второй варианты'], ['Почему эти отели', 'Почему эти варианты?']];
    return node('section', { class: 'journey-command', 'aria-labelledby': 'command-title' },
      node('div', { class: 'command-heading' }, node('h2', { id: 'command-title' }, 'Меняйте планы одной фразой'), node('span', {}, 'Неупомянутые условия сохраняются')),
      composer(true),
      node('div', { class: 'command-examples' }, examples.map(([label, message]) => button(label, () => sendMessage(message), 'text-button'))));
  }

  function sessionContext(includeReply = true) {
    const session = state.session;
    const assumptions = [...new Set([...(session.assumptions || []), ...(session.requirements.assumptions || [])])];
    return node('details', { class: 'session-context' }, node('summary', {}, icon('check', 16), 'Как подобрали поездку', node('span', { 'aria-hidden': 'true' }, '+')),
      includeReply ? node('p', {}, session.assistant_message) : null,
      assumptions.length ? node('ul', {}, assumptions.map(value => node('li', {}, readableDates(value)))) : null,
      (session.requirements.unsupported || []).length ? node('ul', {}, session.requirements.unsupported.map(value => node('li', {}, 'Пока не можем учесть: ' + value))) : null);
  }

  function clarificationQuestions(detailedDates = false) {
    const questions = (state.session.clarifications || []).slice(0, 1).map(question => {
      if (detailedDates && question.field === 'check_in') {
        const input = node('input', { id: 'clarify-check-in', name: 'check_in', type: 'date', required: true, min: futureDate(0), value: state.clarificationDate, oninput: event => { state.clarificationDate = event.target.value; } });
        const choices = (question.options || []).map(option => {
          const parsed = new Date(`${option.value}T12:00:00`);
          const parts = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' }).formatToParts(parsed);
          return button(node('span', { class: 'clarify-date-copy' }, node('small', {}, parsed.toLocaleDateString('ru-RU', { weekday: 'long' })), node('strong', {}, parts.find(part => part.type === 'day').value), node('span', {}, parts.find(part => part.type === 'month').value), icon('arrow', 16)), () => patchRequirements({ check_in: option.value }), 'choice-chip clarify-date-option', { 'aria-label': `Заехать ${parsed.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })}` });
        });
        return node('section', { class: 'clarify-item clarify-arrival', 'aria-labelledby': 'clarify-date-title' },
          node('h2', { id: 'clarify-date-title' }, 'Выберите дату заезда'),
          node('p', { class: 'clarify-question-note' }, question.question?.replace(/^Когда хотите заехать\?\s*/, '') || 'Выберите удобную дату начала отдыха.'),
          choices.length ? node('div', { class: 'clarify-date-options' }, choices) : null,
          node('form', { class: 'clarify-date-form', onsubmit: event => { event.preventDefault(); patchRequirements({ check_in: input.value }); } },
            node('div', { class: 'clarify-custom-date' }, node('label', { for: input.id }, 'Своя дата заезда'), input),
            node('button', { type: 'submit', class: 'button clarify-date-submit' }, node('span', {}, 'Показать поездки', icon('arrow', 19)))));
      }
      const choices = (question.options || []).map(option => button(question.field === 'check_in' ? date(option.value) : option.label, () => patchRequirements({ [question.field]: option.value }), 'choice-chip'));
      return node('div', { class: 'clarify-item' }, node('h2', {}, question.question), node('div', { class: 'chip-row' }, choices));
    });
    return node('div', { class: 'clarification-questions' }, questions);
  }

  function clarification() {
    const hasDate = state.session.clarifications?.[0]?.field === 'check_in';
    return node('section', { class: 'clarify-section' },
      node('div', { class: 'clarify-layout' },
        node('figure', { class: 'clarify-photo' }, node('img', { src: '/static/media/rivane/hero-sochi.webp', alt: 'Морской вокзал и гавань Сочи', width: 2400, height: 1600 }), node('figcaption', {},
          node('div', {}, node('p', { class: 'clarify-destination' }, 'Большой Сочи'),
            node('h1', { tabindex: '-1', 'data-view-heading': true }, hasDate ? 'Когда начнётся' : 'Продумано', node('em', {}, hasDate ? 'ваш отдых?' : 'под вас.'))),
          node('small', {}, 'Сочи · Морской вокзал'))),
        node('div', { class: 'clarify-panel' },
          node('p', { class: 'clarify-kicker' }, icon(hasDate ? 'calendar' : 'spark', 18), hasDate ? 'Начало путешествия' : 'Детали вашей поездки'),
          clarificationQuestions(true),
          node('p', { class: 'clarify-saved' }, icon('check', 16), 'Остальные условия уже сохранены'),
          button('Уточнить в чате', () => toggleChat(true), 'text-button'))));
  }

  function stayImage(plan) {
    if (imageSession !== state.session?.id) {
      imageSession = state.session?.id;
      imageCache = restoreStayImages(savedTrips().find(trip => trip.id === imageSession)?.images);
    }
    const hotels = (state.session?.plans || []).map(item => item.hotel);
    if (!hotels.some(hotel => hotel.id === plan.hotel.id)) hotels.push(plan.hotel);
    imageCache = { ...imageCache, ...assignStayImages(hotels, imageCache) };
    return imageCache[plan.hotel.id];
  }

  function mealLabel(plan) { return plan.meal === 'Завтрак включён' ? 'Завтрак включён' : 'Без питания'; }

  function cancellationLabel(plan) {
    if (!plan.refundable) return 'Невозвратный тариф';
    const cutoff = /до (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})/.exec(plan.policy || '');
    return cutoff ? `Бесплатно до ${date(cutoff[1])}, ${cutoff[2]} МСК` : 'Смотрите условия тарифа';
  }

  function tripScope(plan) { return travelLabels(plan.transport.mode).scope; }

  function timelineTitle(item, plan) {
    if (item.title === 'Выезд из Москвы') return `${travelLabels(plan.transport.mode).departure} из Москвы`;
    if (plan.transport.mode !== 'flight') return item.title;
    if (item.title === 'Обратная дорога') return 'Обратный вылет';
    return /^Прибытие в (Сочи|Москву)$/.test(item.title) ? item.title.replace('Прибытие', 'Прилёт') : item.title;
  }

  function hotelCard(plan, index) {
    const hotel = plan.hotel;
    const comparison = offerComparison(plan, state.session.plans);
    const originalBadge = state.session.plan_labels?.[plan.id];
    const badge = state.session.plans.length === 1 ? 'Подходит вашим условиям' : comparison.premium === 0 ? 'Доступнее из показанных' : originalBadge === 'Ближе к пожеланиям' && !comparison.preferenceGains.length ? 'Другой уровень комфорта' : originalBadge;
    const factLike = /м до пляжа|рейтинг|завтрак включ|бесплатная отмена/i;
    const uniqueReasons = (plan.reasons || []).filter(reason => !factLike.test(reason));
    const mainReason = uniqueReasons[0] || (plan.preference_matches || [])[0] || (badge === 'Самая низкая цена' ? 'Самая доступная поездка в этом подборе' : (hotel.features || []).includes('pool') ? 'Бассейн на территории' : badge === 'Высокий рейтинг' ? 'Один из лучших рейтингов в подборе' : 'Соответствует обязательным условиям');
    const cheapestShown = Math.min(...state.session.plans.map(item => item.price.total));
    const premium = plan.price.total - cheapestShown;
    const compromise = (plan.compromises || []).find(value => /нужно \d.*номер/i.test(value)) || (plan.preference_compromises || [])[0] || (plan.compromises || []).find(value => !/тариф|отмен|данные|демо|питание|завтрак/i.test(value)) || (premium > 0 ? `На ${money(premium)} дороже самого доступного из показанных` : (plan.warnings || []).some(value => /раннее заселение не включено/i.test(value)) ? 'Ранний заезд не включён' : 'Личные расходы не включены');
    const selectLabel = state.session.clarifications?.length ? 'Сначала уточним условия' : state.session.hotel_intent && !state.session.selected_plan ? 'Подтвердить новый план' : 'Посмотреть план';
    return node('article', { class: `hotel-card${index === 0 ? ' hotel-card-recommended' : ''}` },
      node('div', { class: `hotel-image hotel-image-${index}` }, node('img', { src: stayImage(plan), alt: '', loading: 'lazy', width: 1200, height: 800 }),
        node('span', { class: 'image-note' }, 'Иллюстрация'), badge ? node('span', { class: 'recommendation' }, badge) : null),
      node('div', { class: 'hotel-body' },
        node('div', { class: 'hotel-meta' }, node('span', {}, hotel.area || 'Сочи', hotel.stars ? ` · ${hotel.stars}★` : ''), node('span', { class: 'rating' }, hotel.rating ? String(hotel.rating).replace('.', ',') : '—', node('span', { class: 'sr-only' }, ' — оценка отеля'))),
        node('h3', {}, hotel.name),
        node('p', { class: 'total-price' }, money(plan.price.total), node('span', {}, `${priceAudience(plan.guests)} · ${nights(plan.dates.nights)}`), node('small', { class: 'price-includes' }, tripScope(plan))),
        node('dl', { class: 'stay-facts' }, [['До моря', `${hotel.beach_m} м`], ['Питание', mealLabel(plan)], ['Отмена', cancellationLabel(plan)]].map(([label, value]) => node('div', {}, node('dt', {}, label), node('dd', {}, value)))),
        node('div', { class: 'fit-list' }, node('p', {}, node('span', { 'aria-hidden': 'true' }, '✓'), mainReason.replace('Тихий район и спокойная территория по демо-каталогу', 'Спокойная территория').replace('Самая доступная поездка в этом подборе', 'Самый доступный вариант'))),
        comparison.premium > 0 ? node('details', { class: 'offer-tradeoff' }, node('summary', {}, `За что +${money(comparison.premium)}`), node('strong', {}, `К «${comparison.baselineName}»`),
          comparison.facts.length ? node('ul', {}, comparison.facts.slice(0, 3).map(fact => node('li', {}, fact))) : null,
          node('p', {}, comparison.preferenceGains.length ? `Дополнительно из пожеланий: ${comparison.preferenceGains.join('; ')}.` : 'Дополнительных выполненных пожеланий нет. Выбирайте, важны ли вам эти отличия.'),
          comparison.preferenceLosses.length ? node('p', {}, `Компромисс: ${comparison.preferenceLosses.join('; ')}.`) : null) : null,
        /нужно \d.*номер/i.test(compromise) ? node('p', { class: 'compromise' }, node('span', {}, 'Учтите: '), compromise) : null,
        node('div', { class: 'card-bottom' },
          button(node('span', {}, selectLabel, arrow()), () => mutate(`/api/sessions/${encodeURIComponent(state.session.id)}/select`, { plan_id: plan.id, revision: state.session.revision }), `button button-full${index ? ' button-secondary' : ''}`, { disabled: state.session.clarifications?.length > 0 }),
          node('details', { class: 'card-price-details' }, node('summary', {}, 'Состав цены и детали'), node('dl', {}, priceEntries(plan).map(([label, value]) => node('div', {}, node('dt', {}, label), node('dd', {}, value === null ? 'Не рассчитано' : money(value))))),
            node('p', {}, compromise)))));
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
      node('div', { class: 'section-heading' }, node('h2', {}, session.plans.length ? session.hotel_intent && !session.selected_plan ? 'Проверьте новую стоимость' : 'Подобрано для вас' : 'Условия пока не совпали'),
        session.plans.length ? node('p', {}, `${session.total_matches} ${plural(session.total_matches, 'отель подходит', 'отеля подходят', 'отелей подходят')} · показываем ${session.plans.length}`) : null),
      session.plans.length > 1 ? node('div', { class: 'result-priorities', 'aria-label': 'Порядок вариантов' }, node('span', {}, 'Сначала:'),
        [['balanced', 'Рекомендуемые', 'Покажи рекомендованные варианты'], ['price', 'Дешевле', 'Покажи сначала дешевле'], ['beach', 'Ближе к морю', 'Покажи сначала ближе к морю']].map(([key, label, message]) => button(label, () => sendMessage(message), 'text-button', { 'aria-pressed': String((session.ranking || 'balanced') === key) }))) : null,
      session.plans.length ? node('div', { class: `hotel-grid${session.plans.length === 1 ? ' hotel-grid-single' : ''}` }, session.plans.slice(0, 3).map(hotelCard)) : node('div', { class: 'empty-state' },
        node('span', { class: 'empty-symbol', 'aria-hidden': 'true' }, '↝'), node('h3', {}, session.hotel_intent ? 'Проверили сохранённый отель' : 'Точных совпадений пока нет'), node('p', {}, session.diagnostic?.message || 'В демонстрационном каталоге нет предложений для этих условий.'),
        session.hotel_alternative ? button(`${session.hotel_alternative.label} · ${session.hotel_alternative.total_matches}`, () => sendMessage('Покажи другие отели'), 'button button-secondary') : null),
      supportTools());
  }

  function supportTools() {
    const changes = alternatives();
    return node('section', { class: 'journey-tools', 'aria-label': 'Уточнения и подробности' },
      changes ? node('details', { class: 'alternatives-disclosure', open: !state.session.plans.length }, node('summary', {}, icon('bag', 20), node('span', {}, 'Другие условия и цены', node('small', {}, 'Посмотреть возможные компромиссы')), node('span', { class: 'disclosure-plus', 'aria-hidden': 'true' }, '+')), changes) : null,
      node('div', { class: 'technical-details' }, sessionContext(), node('p', { class: 'parser-note' }, parserNote())));
  }

  function conciergePanel() {
    const agent = state.session?.agent;
    if (!agent?.facts?.length) return null;
    return node('section', { class: 'concierge-notes', 'aria-label': 'Объяснение подбора' },
      agent.explanation_status === 'pending' ? node('p', { class: 'concierge-notice', role: 'status' }, 'Варианты уже готовы. Персональное AI-объяснение загружается…') : null,
      node('details', { open: Boolean(agent.requested) },
        node('summary', {}, icon('spark', 20), node('span', {}, agent.title, node('small', {}, 'На основе цен и условий текущих предложений')), node('span', { 'aria-hidden': 'true' }, '+')),
        agent.notice ? node('p', { class: 'concierge-notice', role: 'status' }, agent.notice) : null,
        node('ul', { class: 'concierge-facts' }, agent.facts.map(fact => node('li', {}, readableDates(fact.text)))),
        node('p', { class: 'concierge-provenance' }, 'Сравнение рассчитано по текущим предложениям демокаталога. Условия поездки не меняются.')),
      agent.question ? node('p', { class: 'concierge-question' }, agent.question) : null,
      node('div', { class: 'concierge-actions' }, (agent.actions || []).map(action => button(action.label, () => sendMessage(action.message), 'choice-chip'))));
  }

  function priceBreakdown(plan) {
    const selfTravel = plan.transport.mode === 'self';
    const entries = priceEntries(plan);
    return node('div', { class: 'price-breakdown' },
      node('h3', {}, selfTravel ? 'Стоимость включённых услуг' : 'Из чего складывается цена'),
      selfTravel ? node('p', { class: 'muted small price-exclusion-note' }, 'Стоимость самостоятельной дороги и трансфера не рассчитана и не включена в сумму.') : null,
      node('dl', {}, entries.map(([label, value]) => node('div', {}, node('dt', {}, label), node('dd', {}, value === null ? 'Не рассчитано' : money(value))))),
      node('div', { class: 'breakdown-total' }, node('span', {}, 'Итого'), node('strong', {}, money(plan.price.total))),
      node('p', { class: 'muted small' }, `${priceAudience(plan.guests)} · ${nights(plan.dates.nights)}`));
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
      node('figure', { class: 'plan-hero' }, node('img', { src: stayImage(plan), alt: '', width: 1200, height: 800 }), node('figcaption', { class: 'image-note' }, 'Иллюстрация')),
      node('section', { class: 'detail-summary' }, showTitle ? node('h2', {}, plan.hotel.name) : null,
        node('p', { class: 'detail-location' }, `${plan.hotel.area} · ${plan.hotel.stars}★ · оценка ${String(plan.hotel.rating).replace('.', ',')} · ${plan.hotel.beach_m} м до моря`),
        node('p', { class: 'hotel-description' }, plan.hotel.description.replace(/^Вымышленный отель в районе [^.]+\.\s*/, '')),
        node('dl', { class: 'detail-facts' },
          node('div', {}, node('dt', {}, 'Когда'), node('dd', {}, `${date(plan.dates.check_in)} — ${date(plan.dates.check_out)} · ${nights(plan.dates.nights)}`)),
          node('div', {}, node('dt', {}, 'Проживание'), node('dd', {}, `${plan.room.name} · ${plan.room.rooms} ${plural(plan.room.rooms, 'номер', 'номера', 'номеров')}`)),
          node('div', {}, node('dt', {}, 'Гости'), node('dd', {}, `${plan.guests.adults} взрослых${plan.guests.children_ages.length ? ` · дети ${plan.guests.children_ages.join(', ')} лет` : ''}`)),
          node('div', {}, node('dt', {}, 'Питание'), node('dd', {}, mealLabel(plan))),
          node('div', {}, node('dt', {}, travelLabels(transport.mode).service), node('dd', {}, transport.title)),
          node('div', {}, node('dt', {}, 'Трансфер'), node('dd', {}, plan.transfer.title))),
        node('div', { class: 'rate-policy' }, node('strong', {}, 'Отмена'), node('p', { class: 'cancellation-policy' }, readablePolicy(plan.policy))),
        secondaryReasons.length ? node('details', { class: 'detail-reasons route-details' }, node('summary', {}, 'Почему подходит вашим пожеланиям'), node('ul', {}, secondaryReasons.map(reason => node('li', {}, reason)))) : null,
        compromises.length ? node('div', { class: 'detail-compromises' }, node('h3', {}, 'Главное учесть'), node('ul', {}, compromises.map(value => node('li', {}, value)))) : null),
      node('section', { class: 'timeline-section' }, node('h3', {}, 'Маршрут поездки'),
        [...days].map(([day, items]) => node('section', { class: 'route-group' }, node('h4', {}, date(day)),
          node('ol', { class: 'timeline' }, items.map(item => node('li', {}, node('time', { class: 'timeline-time', datetime: item.time }, item.time.slice(11, 16)), node('strong', {}, timelineTitle(item, plan))))))),
        node('details', { class: 'route-details' }, node('summary', {}, 'Подробности дороги и трансферов'), node('ul', {}, (plan.timeline || []).map(item => node('li', {}, node('strong', {}, `${dateTime(item.time)} · ${timelineTitle(item, plan)}`), node('p', {}, item.detail))))),
        node('div', { class: 'policy-note' }, node('h3', {}, 'Важно о поездке'), warnings.map(warning => node('p', {}, readableDates(warning))))));
  }

  function checkoutForm(plan) {
    const needsAnswer = state.session.request_status === 'needs_clarification' || state.session.clarifications?.length > 0;
    const name = node('input', { id: 'traveler-name', name: 'name', autocomplete: 'name', minlength: 2, maxlength: 100, placeholder: 'Имя и фамилия', oninput: event => { state.checkout.name = event.target.value; } });
    const email = node('input', { id: 'traveler-email', name: 'email', type: 'email', autocomplete: 'email', maxlength: 254, placeholder: 'you@example.ru', oninput: event => { state.checkout.email = event.target.value; } });
    const agreement = node('input', { id: 'demo-agreement', type: 'checkbox', required: true, onchange: event => { state.checkout.accepted = event.target.checked; } });
    name.value = state.checkout.name;
    email.value = state.checkout.email;
    agreement.checked = state.checkout.accepted;
    return node('section', { id: 'checkout', class: 'checkout-panel', 'aria-label': 'Сохранение плана поездки' },
      node('form', { class: 'checkout-form', onsubmit: event => {
        event.preventDefault();
        if (name.value.trim() && name.value.trim().length < 2) { name.setCustomValidity('Введите имя длиной от 2 символов.'); name.reportValidity(); name.addEventListener('input', () => name.setCustomValidity(''), { once: true }); return; }
        mutate(`/api/sessions/${encodeURIComponent(state.session.id)}/checkout`, { revision: state.session.revision, accept_demo: agreement.checked, traveler_name: name.value.trim() || null, email: email.value.trim() || null });
      } },
        node('div', { class: 'form-section-heading' }, node('div', {}, node('h2', {}, 'План останется с вами'), node('p', { class: 'small muted' }, 'Сохраните маршрут и расчёт в «Моих поездках». Контакты не нужны.'))),
        node('details', { class: 'optional-contacts' }, node('summary', {}, 'Добавить имя и почту · необязательно'), node('label', { for: name.id }, 'Ваше имя'), name, node('label', { for: email.id }, 'Электронная почта'), email,
          node('p', { class: 'form-note' }, 'Контакты попадут только в сохранённый план. Письмо не отправляется.')),
        node('div', { class: 'checkout-total' }, node('span', {}, 'Итого за\u00a0поездку'), node('strong', {}, money(plan.price.total))),
        stayCautions(plan),
        node('label', { class: 'checkbox-label', for: agreement.id }, agreement, node('span', {}, 'Я понимаю: сохраняется план, бронирование не создаётся.')),
        needsAnswer ? node('p', { class: 'form-note', role: 'status' }, 'Сначала ответьте на уточнение выше. Текущий вариант сохранён для сравнения; состав и стоимость могут измениться.') : null,
        node('button', { type: 'submit', class: 'button button-full checkout-submit', disabled: needsAnswer }, needsAnswer ? 'Сначала уточним условия' : node('span', {}, 'Сохранить в «Мои поездки»', icon('arrow', 20)))));
  }

  function navigateJourney(hash) {
    if (state.pending) return;
    window.history.pushState(null, '', hash);
    render();
    document.querySelector('[data-view-heading]')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: 'instant' });
  }

  function selected() {
    const plan = state.session.selected_plan;
    if (!plan) return results();
    const blocked = state.session.request_status === 'needs_clarification' || state.session.clarifications?.length;
    const services = ['Проживание', plan.transport.mode === 'self' ? null : travelLabels(plan.transport.mode).service, plan.transport.mode === 'self' ? null : 'Трансфер'].filter(Boolean);
    return node('div', { class: 'selected-content' },
      node('section', { class: 'trip-showcase', 'aria-label': 'Обзор выбранной поездки' },
        node('figure', { class: 'showcase-photo' }, node('img', { src: stayImage(plan), alt: 'Иллюстрация выбранного демоотеля', width: 1200, height: 800, fetchpriority: 'high' }), node('span', { class: 'showcase-rating' }, String(plan.hotel.rating).replace('.', ','), node('span', {}, 'оценка отеля')), node('figcaption', { class: 'image-note' }, 'Иллюстрация')),
        node('div', { class: 'trip-decision' }, smallLabel('Ваш отдых в деталях'), node('h2', {}, plan.hotel.description.replace(/^Вымышленный отель в районе [^.]+\.\s*/, '') || 'Время для себя'),
          node('dl', { class: 'decision-facts' }, [['Номер', `${plan.room.name} · ${plan.room.rooms} ${plural(plan.room.rooms, 'номер', 'номера', 'номеров')}`], ['Питание', mealLabel(plan)]].map(([label, value]) => node('div', {}, node('dt', {}, label), node('dd', {}, value)))),
          node('div', { class: 'decision-price' }, node('span', {}, priceAudience(plan.guests)), node('strong', {}, money(plan.price.total)), node('small', {}, `За ${nights(plan.dates.nights)}`)),
          node('ul', { class: 'included-services' }, services.map(service => node('li', {}, icon('check', 15), service))),
          plan.transport.mode === 'self' ? node('p', { class: 'decision-exclusion' }, 'Самостоятельная дорога и трансфер не рассчитаны и не включены.') : null,
          stayCautions(plan),
          button(node('span', {}, blocked ? 'Сначала уточним условия' : 'Сохранить этот вариант', icon('arrow', 20)), () => navigateJourney('#checkout'), 'button decision-continue', { disabled: Boolean(blocked) }),
          node('p', { class: 'decision-note' }, 'Сохранение без регистрации и контактов'))),
      routePreview(plan),
      node('details', { class: 'stay-detail-disclosure' }, node('summary', {}, 'Номер, транспорт и условия', node('span', { 'aria-hidden': 'true' }, '+')), node('dl', { class: 'detail-facts' }, [['Номер', `${plan.room.name} · ${plan.room.rooms} ${plural(plan.room.rooms, 'номер', 'номера', 'номеров')}`], ['Питание', mealLabel(plan)], [travelLabels(plan.transport.mode).service, plan.transport.title], ['Трансфер', plan.transfer.title]].map(([label, value]) => node('div', {}, node('dt', {}, label), node('dd', {}, value)))),
        node('ul', { class: 'stay-warnings' }, (plan.warnings || []).filter(warning => warning !== plan.data_label).map(warning => node('li', {}, readableDates(warning))))),
      supportTools());
  }

  function stayCautions(plan) {
    const compromises = [...new Set(plan.compromises || [])].filter(value => !/невозвратный тариф/i.test(value));
    return node('section', { class: 'stay-cautions', 'aria-label': 'Важные условия' },
      node('div', { class: 'cancellation-summary' }, icon('check', 20), node('div', {}, node('h3', {}, plan.refundable ? 'Отмена по условиям тарифа' : 'Невозвратный тариф'), node('p', {}, readablePolicy(plan.policy)))),
      compromises.length ? node('div', { class: 'compromise-summary' }, node('span', { class: 'caution-symbol', 'aria-hidden': 'true' }, '!'), node('div', {}, node('h3', {}, 'Перед выбором учтите'), node('p', {}, compromises.join(' · ')))) : null);
  }

  function routePreview(plan) {
    const days = new Map();
    (plan.timeline || []).forEach(item => {
      const day = item.time.slice(0, 10);
      if (!days.has(day)) days.set(day, []);
      days.get(day).push(item);
    });
    return node('section', { class: 'route-preview timeline-section' },
      node('div', { class: 'route-heading' }, smallLabel('Всё продумано'), node('h2', {}, 'Как пройдёт поездка')),
      node('div', { class: 'route-days' }, [...days].map(([day, items]) => node('section', { class: 'route-group' }, node('div', { class: 'route-day-heading' }, node('h3', {}, date(day)), node('span', {}, day < plan.dates.check_in ? 'Дорога к отелю' : day >= plan.dates.check_out ? 'Возвращение' : 'Начало отдыха')), node('ol', { class: 'timeline' }, items.map(item => node('li', {}, node('time', { class: 'timeline-time', datetime: item.time }, item.time.slice(11, 16)), node('strong', {}, timelineTitle(item, plan)))))))),
      node('details', { class: 'route-details' }, node('summary', {}, 'Расписание и детали трансферов', node('span', { 'aria-hidden': 'true' }, '+')), node('ul', {}, (plan.timeline || []).map(item => node('li', {}, node('strong', {}, `${dateTime(item.time)} · ${timelineTitle(item, plan)}`), node('p', {}, item.detail))))),
      node('p', { class: 'route-notice' }, 'Демонстрационное расписание · время московское. Раннее заселение не включено.'));
  }

  function checkoutView() {
    const plan = state.session.selected_plan;
    return node('div', { class: 'checkout-content' },
      node('div', { class: 'checkout-layout' }, checkoutForm(plan),
        node('aside', { class: 'checkout-recap', 'aria-label': 'Выбранная поездка и стоимость' },
          node('div', { class: 'recap-stay' }, node('img', { src: stayImage(plan), alt: '', width: 180, height: 140 }), node('div', {}, smallLabel(`${plan.hotel.area} · ${plan.hotel.stars}★`), node('h2', {}, plan.hotel.name), node('p', {}, `${date(plan.dates.check_in)} — ${date(plan.dates.check_out)} · ${nights(plan.dates.nights)}`), node('p', {}, `${plan.guests.adults} ${plural(plan.guests.adults, 'взрослый', 'взрослых', 'взрослых')}${plan.guests.children_ages.length ? ` · детей: ${plan.guests.children_ages.length}` : ''}`))),
          priceBreakdown(plan), button('Вернуться к поездке', () => navigateJourney('#trip'), 'text-button recap-back'))));
  }

  function downloadOrder() {
    downloadPlan(state.session.order, state.session.requirements);
  }

  function booked() {
    const order = state.session.order;
    if (!order) return selected();
    const plan = order.plan;
    return node('section', { class: 'booked-section' },
      node('div', { class: 'confirmation-main' }, node('div', {}, node('div', { class: 'success-mark', 'aria-hidden': 'true' }, '✓'), node('h2', {}, plan.hotel.name), node('p', { class: 'order-reference' }, 'План № ', order.reference),
        node('p', { class: 'booked-description' }, 'План доступен в «Моих поездках» в этом браузере. Его можно скачать. Бронирование не создано, письмо не отправлялось.'),
        node('div', { class: 'order-actions' }, button('Скачать план', downloadOrder), button('Новая поездка', resetTrip, 'button button-secondary'))),
        node('figure', { class: 'confirmation-photo' }, node('img', { src: stayImage(plan), alt: '', width: 1200, height: 800 }), node('figcaption', { class: 'image-note' }, 'Иллюстрация'))),
      node('div', { class: 'order-overview' }, node('div', {}, node('span', {}, 'Поездка'), node('strong', {}, plan.hotel.name), node('p', {}, `${date(plan.dates.check_in)} — ${date(plan.dates.check_out)}`)),
        node('div', {}, node('span', {}, order.traveler_name ? 'На имя' : 'Где найти'), node('strong', {}, order.traveler_name || 'Мои поездки'), node('p', {}, order.email || 'В этом браузере')),
        node('div', {}, node('span', {}, priceAudience(plan.guests)), node('strong', {}, money(order.total)), node('p', {}, 'Расчётная стоимость'))),
      node('details', { class: 'order-details' }, node('summary', {}, 'Весь маршрут и стоимость'), node('div', { class: 'selected-layout' }, tripDetails(plan), priceBreakdown(plan))));
  }

  function toggleChat(open = !state.chatOpen) {
    state.chatOpen = open;
    render();
    (open ? document.querySelector('#refine-message') : document.querySelector('.chat-toggle'))?.focus({ preventScroll: true });
  }

  function conversation() {
    const agent = state.session.agent;
    const connected = agent?.mode === 'llm' || state.session.parser_mode === 'llm';
    const messages = state.session.messages || [];
    const thread = node('ol', { class: 'chat-thread', 'aria-label': 'История разговора', tabindex: '0' },
      messages.map(message => node('li', { class: message.role === 'user' ? 'chat-user' : 'chat-assistant' },
        node('strong', {}, message.role === 'user' ? 'Вы' : 'O!RIVANE'), node('p', {}, readableDates(message.content)))));
    const panel = node('aside', { id: 'travel-chat', class: 'travel-chat', hidden: !state.chatOpen, 'aria-labelledby': 'chat-title' },
      node('div', { class: 'chat-heading' }, node('div', {}, node('h2', { id: 'chat-title' }, icon('spark', 19), 'Ваш помощник'), node('p', { class: `chat-mode${connected ? ' is-connected' : ''}` }, connected ? 'ИИ подключён · по данным поездки' : 'ИИ недоступен · основные команды работают')),
        button('×', () => toggleChat(false), 'chat-close', { 'aria-label': 'Свернуть чат' })),
      node('p', { class: 'chat-context' }, 'Один разговор на всём пути. Условия и история сохраняются.'),
      thread,
      node('div', { class: 'chat-evidence' }, conciergePanel()),
      state.error ? node('p', { class: 'chat-error', role: 'status' }, state.error) : null,
      state.messageRetry ? node('p', { class: 'chat-error chat-retry', role: 'status' }, 'ИИ не ответил. Черновик сохранён — проверьте ответ и условия перед повтором.') : null,
      node('div', { class: 'chat-compose' }, composer(true),
        node('p', { class: 'chat-hint' }, 'Ctrl + Enter — отправить. «А если…» — сначала сравнить.')));
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.stopPropagation(); toggleChat(false); }
      if (event.key !== 'Tab' || window.matchMedia('(min-width: 1100px)').matches) return;
      const controls = [...panel.querySelectorAll('button, textarea, [tabindex="0"], summary')].filter(item => !item.disabled && item.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    });
    requestAnimationFrame(() => { thread.scrollTop = thread.scrollHeight; });
    return panel;
  }

  function render() {
    main.replaceChildren();
    main.setAttribute('aria-busy', String(state.pending));
    document.body.classList.toggle('has-session', Boolean(state.session));
    document.body.classList.toggle('chat-is-open', Boolean(state.session && state.chatOpen));
    const view = journeyView(state.session, location.hash);
    document.querySelector('#search-trip').hidden = view === 'confirmation';
    if (state.session) document.body.dataset.journeyView = view;
    else delete document.body.dataset.journeyView;
    newTrip.hidden = !state.session;
    newTrip.disabled = state.pending;
    document.querySelector('#how-link').hidden = false;
    closeNavigation();
    if (state.error) main.append(renderError());
    if (state.restoring) main.append(node('section', { class: 'restore-state', role: 'status' }, smallLabel('Возвращаемся к вашим планам'), node('h1', {}, 'Ваша поездка уже рядом.'), node('p', {}, 'Загружаем сохранённые пожелания и маршрут…')));
    else if (!state.session) main.append(landing());
    else {
      const content = node('div', { class: 'journey-main' }, sessionIntro());
      if (view === 'confirmation') content.append(booked());
      else if (view === 'clarify') content.append(clarification());
      else if (view === 'checkout') content.append(checkoutView());
      else if (view === 'trip') content.append(selected());
      else content.append(results());
      if (view !== 'clarify' && state.session.requirements.destination) content.append(destinationPanel());
      main.append(node('div', { class: 'journey-workspace' }, content, conversation()));
      if (state.chatOpen) main.append(button('', () => toggleChat(false), 'chat-backdrop', { 'aria-label': 'Закрыть чат', tabindex: '-1' }));
      main.append(button(node('span', {}, icon('spark', 19), 'Чат о поездке'), () => toggleChat(), 'chat-toggle', { 'aria-controls': 'travel-chat', 'aria-expanded': String(state.chatOpen), hidden: state.chatOpen && window.matchMedia('(min-width: 1100px)').matches }));
    }
    syncChatLayout();
    updateChatViewport();
    if (state.session?.requirements?.destination) void destinationLoader.load();
    else destinationLoader.cancel();
  }

  function destinationPanel() {
    const key = `${state.session?.id}:${state.session?.revision}`;
    const data = destinationDataKey === key ? destinationData : null;
    const link = (label, url) => validExternal(url) ? node('a', { href: validExternal(url), target: '_blank', rel: 'noopener noreferrer', class: 'context-link' }, label, ' ↗') : null;
    const panel = node('section', { class: 'destination-context', 'aria-label': 'Информация о месте поездки' },
      smallLabel('Открытые источники'), node('h2', {}, 'Ближе к месту поездки'),
      node('p', { class: 'context-intro' }, 'Погода, места и дорога — отдельно от демонстрационных предложений отелей.'));
    if (!data) { panel.append(node('p', { role: 'status', class: 'context-status' }, 'Загружаем сведения. Подбором уже можно пользоваться.')); return panel; }
    if (!data.location) { panel.append(node('p', { role: 'status' }, 'Открытые источники сейчас не ответили. Условия и результаты подбора доступны.'), button('Повторить загрузку', () => { destinationLoader.cancel(); void destinationLoader.load(); }, 'text-button')); return panel; }
    const place = data.location;
    const weather = data.weather || {};
    const calendarDate = value => new Date(value + 'T12:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
    const temp = value => Number.isFinite(value) ? `${Math.round(value)}°` : '—';
    const weatherBlock = node('div', { class: 'context-weather' }, node('h3', {}, 'Погода · ', place.name));
    if (weather.status === 'ok') {
      if (Number.isFinite(weather.current?.temperature_c)) weatherBlock.append(node('p', { class: 'context-temperature' }, temp(weather.current.temperature_c), node('span', {}, 'Сейчас · данные погодной модели')));
      weatherBlock.append(node('p', { class: 'context-caption' }, weather.coverage === 'outside_forecast' ? 'Прогноз на даты поездки ещё недоступен: горизонт источника — до 16 дней.' : weather.coverage === 'partial' ? 'Прогноз доступен на часть поездки. Более дальние дни пока не прогнозируются.' : weather.coverage === 'upcoming' ? 'Ближайшие дни. Укажите даты поездки, чтобы увидеть прогноз на свой срок.' : 'Прогноз на даты поездки. Он может меняться.'));
      if (weather.days?.length) weatherBlock.append(node('ul', { class: 'context-days', 'aria-label': 'Прогноз по дням' }, weather.days.slice(0, 16).map(day => node('li', {}, node('span', {}, calendarDate(day.date)), node('strong', {}, temp(day.high_c)), node('span', {}, 'ночью ', temp(day.low_c)), node('small', {}, Number.isFinite(day.rain_probability_pct) ? `Осадки ${day.rain_probability_pct}%` : 'Вероятность осадков неизвестна')))));
      if (weather.fetched_at) weatherBlock.append(node('p', { class: 'context-caption' }, 'Получено ', dateTime(weather.fetched_at)));
    } else weatherBlock.append(node('p', {}, 'Источник погоды временно недоступен.'));
    if (data.history?.status === 'ok') weatherBlock.append(node('p', { class: 'context-history' }, `История за ${data.history.month}: средняя дневная максимальная ${temp(data.history.mean_high_c)}, ночная минимальная ${temp(data.history.mean_low_c)}. Это прошлогодние наблюдения, не прогноз и не климатическая норма.`));
    weatherBlock.append(link('Источник погоды: Open-Meteo · CC BY 4.0', 'https://open-meteo.com/'));
    const mapBlock = node('div', { class: 'context-map' }, node('h3', {}, 'Место на карте'), node('p', {}, `${place.name}${place.country ? ', ' + place.country : ''}`), link('Открыть OpenStreetMap', data.map_url), node('p', { class: 'context-caption' }, 'Координаты населённого пункта, не отеля. Геокодирование: Open-Meteo / GeoNames.'));
    mapBlock.append(button('Показать интерактивную карту', event => {
      const url = validExternal(data.map_embed_url);
      if (!url) return;
      event.currentTarget.replaceWith(node('iframe', { src: url, title: `Карта: ${place.name}`, loading: 'lazy', class: 'context-map-frame', referrerpolicy: 'no-referrer' }));
    }, 'choice-chip'), node('p', { class: 'context-caption' }, 'По нажатию карта загрузится с OpenStreetMap; сервис получит ваш IP-адрес.'), link('© OpenStreetMap contributors · ODbL', 'https://www.openstreetmap.org/copyright'));
    const places = node('div', { class: 'context-places' }, node('h3', {}, 'Что посмотреть рядом'));
    if (data.places?.attractions?.length) places.append(node('ul', { class: 'context-places-list' }, data.places.attractions.map(item => node('li', {}, link(item.name, item.url), node('small', {}, item.kind)))));
    else places.append(node('p', {}, data.places?.status === 'ok' ? 'В открытой карте не нашлось отмеченных мест в радиусе 12 км.' : 'Источник достопримечательностей временно не ответил. Можно посмотреть места на карте.'));
    places.append(node('p', { class: 'context-caption' }, 'Сведения из открытой карты. Часы работы, доступность и стоимость посещения не проверены.'), link('Источник: OpenStreetMap', 'https://www.openstreetmap.org/copyright'));
    const transport = node('div', { class: 'context-road' }, node('h3', {}, 'Как добраться'));
    if (data.road?.status === 'ok') transport.append(node('p', { class: 'context-route' }, `${data.road.origin} → ${data.road.destination}`), node('p', {}, `На автомобиле: около ${data.road.distance_km} км · ${data.road.duration_hours} ч`), link('Посмотреть маршрут', data.road.url), node('p', { class: 'context-caption' }, 'Расчёт OSRM по дорогам OpenStreetMap. Без пробок, остановок и проверки ограничений. Не время перелёта или поезда.'));
    else transport.append(node('p', {}, 'Дорожный маршрут сейчас не рассчитан.'));
    if (data.places?.transport_points?.length) transport.append(node('ul', { class: 'context-places-list' }, data.places.transport_points.map(item => node('li', {}, link(item.name, item.url), node('small', {}, item.kind)))));
    transport.append(node('p', { class: 'context-caption' }, 'Живые цены, наличие билетов и расписания не подключены: требуется доступ перевозчика. Цены транспорта в подборе остаются демонстрационными.'));
    panel.append(node('div', { class: 'context-grid' }, weatherBlock, mapBlock, places, transport));
    return panel;
  }

  function syncChatLayout() {
    const desktop = window.matchMedia('(min-width: 1100px)').matches;
    const modalChat = Boolean(state.session && state.chatOpen && !desktop);
    const toggle = document.querySelector('.chat-toggle');
    if (toggle) toggle.hidden = state.chatOpen && desktop;
    document.querySelector('.journey-main')?.toggleAttribute('inert', modalChat);
    document.querySelector('.site-header').toggleAttribute('inert', modalChat);
    document.querySelector('.site-footer').toggleAttribute('inert', modalChat);
  }

  function updateChatViewport() {
    const viewport = window.visualViewport;
    if (!viewport) return;
    document.documentElement.style.setProperty('--chat-viewport-height', `${Math.round(viewport.height * .88)}px`);
    document.documentElement.style.setProperty('--chat-keyboard-inset', `${Math.max(0, Math.round(window.innerHeight - viewport.height - viewport.offsetTop))}px`);
  }
  window.visualViewport?.addEventListener('resize', updateChatViewport);
  window.visualViewport?.addEventListener('scroll', updateChatViewport);
  window.matchMedia('(min-width: 1100px)').addEventListener('change', syncChatLayout);

  function resetTrip() {
    if (state.pending) return;
    explanations.cancel();
    state.session = null;
    state.messageRetry = false;
    restoreDraft();
    state.error = '';
    state.clarificationDate = '';
    if (['#trip', '#checkout', '#options', '#confirmation'].includes(location.hash)) window.history.replaceState(null, '', location.pathname + location.search);
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
  document.querySelector('#search-trip').addEventListener('click', () => {
    if (state.pending) return;
    if (state.session) { toggleChat(true); return; }
    const input = document.querySelector('#refine-message, #trip-message');
    if (input) { input.focus(); input.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  });
  document.querySelector('#mobile-menu').addEventListener('click', event => { if (state.pending) return; const open = document.body.classList.toggle('menu-open'); event.currentTarget.setAttribute('aria-expanded', String(open)); event.currentTarget.setAttribute('aria-label', open ? 'Закрыть навигацию' : 'Открыть навигацию'); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeNavigation(); });
  window.addEventListener('hashchange', () => {
    if (!state.session || state.pending) return;
    render();
    document.querySelector('[data-view-heading]')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: 'instant' });
  });
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
    restoreDraft();
    render();
    void explanations.load();
  }
  boot();
})();
