// Landing presentation only. Form submission and trip state remain in app.js.
const mounted = new WeakSet();
let activeLanding = null;
let releaseLanding = () => {};
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
const examples = [
  'В Сочи на неделю вдвоём, с завтраком и рядом с морем',
  'Семьёй в Сочи: двое взрослых и ребёнок 7 лет, нужен бассейн',
  'На выходные к морю, тихий отель и дорога из Москвы'
];
const exampleStart = new Date();
exampleStart.setDate(exampleStart.getDate() + 14);
const exampleDate = exampleStart.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).replace(/\s*г\.$/, '');
const scenarios = [
  `В Сочи с ${exampleDate} на 7 ночей вдвоём, до 160 тысяч, тихий отель рядом с морем, с завтраком`,
  `В Сочи с ${exampleDate} на 7 ночей: двое взрослых и ребёнок 7 лет, до 180 тысяч, нужен бассейн`,
  `В Сочи с ${exampleDate} на 2 ночи вдвоём, до 120 тысяч, рядом с морем, дорога из Москвы`,
  `В Дагомыс с ${exampleDate} на 5 ночей вдвоём, до 130 тысяч, тихое место, с завтраком`
];

function mount(landing) {
  if (mounted.has(landing)) return;
  releaseLanding();
  activeLanding = landing;
  mounted.add(landing);
  landing.dataset.editorial = '2026';
  const title = landing.querySelector('#hero-title');
  if (title) {
    const emphasis = document.createElement('em');
    emphasis.textContent = 'с\u00a0одного желания.';
    title.replaceChildren('Сочи начинается', document.createElement('br'), emphasis);
  }
  const description = landing.querySelector('.lux-description');
  if (description) description.textContent = 'Отель, дорога и\u00a0трансфер — один план с\u00a0общей ценой. Расскажите, каким вы\u00a0видите свой отдых.';
  const destinationTitle = landing.querySelector('#destinations-title');
  if (destinationTitle) destinationTitle.textContent = 'У каждого — свой Сочи';
  const note = landing.querySelector('.journey-parser-note');
  if (note) note.hidden = true;
  const input = landing.querySelector('#trip-message');
  if (!input) return;
  const submitLabel = landing.querySelector('.composer-submit>span');
  if (submitLabel) {
    const arrow = submitLabel.querySelector('svg');
    submitLabel.replaceChildren('Подобрать поездку');
    if (arrow) submitLabel.append(arrow);
  }
  landing.querySelectorAll('.theme-chip').forEach((chip, index) => {
    chip.addEventListener('click', event => {
      if (!scenarios[index] || input.disabled) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      input.value = scenarios[index];
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus({ preventScroll: true });
      input.scrollIntoView({ block: 'center', behavior: reduced.matches ? 'auto' : 'smooth' });
      const status = document.querySelector('#live-status');
      if (status) status.textContent = 'Сценарий добавлен. Уточните пожелания и нажмите «Подобрать поездку».';
    }, { capture: true });
  });
  let example = 0;
  let timer = null;
  let observer = null;
  input.placeholder = examples[example];
  if (!reduced.matches) {
    timer = setInterval(() => {
      if (!input.isConnected) { clearInterval(timer); return; }
      if (reduced.matches || document.hidden || input.value || input.disabled || document.activeElement === input) return;
      example = (example + 1) % examples.length;
      input.placeholder = examples[example];
    }, 5000);
  }
  if ('IntersectionObserver' in window && !reduced.matches) {
    observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.dataset.reveal = 'visible';
        observer.unobserve(entry.target);
      }
    }, { threshold: .12 });
    landing.querySelectorAll('.journey-steps li').forEach(step => {
      step.dataset.reveal = 'pending';
      observer.observe(step);
    });
  }
  releaseLanding = () => {
    if (timer != null) clearInterval(timer);
    observer?.disconnect();
  };
}

document.querySelectorAll('.landing').forEach(mount);
new MutationObserver(records => {
  if (activeLanding && !activeLanding.isConnected) {
    releaseLanding();
    activeLanding = null;
  }
  for (const record of records) {
    for (const node of record.addedNodes) {
      if (!(node instanceof Element)) continue;
      if (node.matches('.landing')) mount(node);
      node.querySelectorAll('.landing').forEach(mount);
    }
  }
}).observe(document.querySelector('#main'), { childList: true, subtree: true });
