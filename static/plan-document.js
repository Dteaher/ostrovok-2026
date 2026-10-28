import { priceAudience, priceEntries, readablePolicy, preferenceLabels } from './trip-ui.js';

const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
const money = value => `${new Intl.NumberFormat('ru-RU').format(Number(value) || 0)} ₽`;
const day = value => {
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isNaN(date.getTime()) ? String(value || '') : date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
};

export function planDocument(order, requirements = {}) {
  if (!order?.plan) throw new Error('Сначала сохраните план поездки.');
  const plan = order.plan;
  const text = value => escape(value);
  const rows = priceEntries(plan).map(([label, value]) => `<tr><td>${text(label)}</td><td>${value == null ? 'Не включено' : money(value)}</td></tr>`).join('');
  const timeline = (plan.timeline || []).map(item => `<li><time>${text(day(item.time.slice(0, 10)))} · ${text(item.time.slice(11, 16))}</time><div><strong>${text(item.title)}</strong><p>${text(item.detail)}</p></div></li>`).join('');
  const children = plan.guests.children_ages || [];
  const preferences = preferenceLabels(requirements);
  return `<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>O!RIVANE — план ${text(order.reference)}</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f1eb;color:#142b45;font:15px/1.6 Georgia,serif}main{max-width:850px;margin:36px auto;padding:48px 56px;background:white}header{display:flex;justify-content:space-between;gap:20px;border-bottom:2px solid #142b45;padding-bottom:20px}.brand{font:700 22px Arial,sans-serif;letter-spacing:2px}.label,time{font:12px/1.6 Arial,sans-serif;color:#526072}.eyebrow{font:12px Arial,sans-serif;text-transform:uppercase;letter-spacing:2px;margin:36px 0 8px}h1{font-size:38px;line-height:1.15;margin:10px 0 16px}h2{font-size:23px;line-height:1.3;margin:32px 0 14px}p{margin:6px 0 12px}.summary{padding:20px 0;border-top:1px solid #ddd;border-bottom:1px solid #ddd}.total{font-size:29px;font-weight:bold}table{width:100%;border-collapse:collapse}td{padding:10px 0;border-bottom:1px solid #e6e6e1}td:last-child{text-align:right;font-variant-numeric:tabular-nums}tr:last-child td{border-bottom:2px solid #142b45;font-weight:bold}ol{list-style:none;margin:0;padding:0}li{display:grid;grid-template-columns:175px 1fr;gap:16px;padding:12px 0;border-bottom:1px solid #e6e6e1;break-inside:avoid}li p{font-size:14px;margin:3px 0}.notice{margin-top:32px;border-top:1px solid #bbb;padding-top:18px;font:12px/1.7 Arial,sans-serif;color:#526072}.print-help{font:13px Arial,sans-serif;color:#526072;margin-bottom:28px}@media(max-width:600px){main{margin:0;padding:25px}h1{font-size:30px}li{grid-template-columns:1fr;gap:4px}header{flex-direction:column}}@media print{@page{size:A4;margin:15mm}body{background:white}main{margin:0;padding:0;max-width:none}.print-help{display:none}h2{break-after:avoid}header,.summary,table{break-inside:avoid}}
</style></head><body><main>
<p class="print-help">Чтобы сохранить PDF или распечатать план, выберите «Печать» в меню браузера (Ctrl+P / ⌘P).</p>
<header><span class="brand">O!RIVANE</span><span class="label">Сохранённый план № ${text(order.reference)}</span></header>
<p class="eyebrow">Ваше путешествие · ${text(plan.hotel.area)}</p><h1>${text(plan.hotel.name)}</h1>
<div class="summary"><p>${text(day(plan.dates.check_in))} — ${text(day(plan.dates.check_out))} · ночей: ${text(plan.dates.nights)}</p><p>${text(priceAudience(plan.guests))}${children.length ? ` · возраст детей: ${text(children.join(', '))}` : ''}</p>${order.traveler_name ? `<p>На имя: ${text(order.traveler_name)}</p>` : ''}</div>
<h2>Проживание</h2><p>${text(plan.room.name)} · номеров: ${text(plan.room.rooms)} · ${text(plan.hotel.stars)}★</p><p>${text(plan.meal)}</p><p>${text(readablePolicy(plan.policy))}</p>
${preferences.length ? `<h2>Ваши условия</h2><p>${preferences.map(text).join(' · ')}</p>` : ''}
<h2>Стоимость за всех гостей и весь срок</h2><table><tbody>${rows}<tr><td>Итого, расчётная стоимость</td><td>${money(order.total ?? plan.price.total)}</td></tr></tbody></table>
<h2>Дорога</h2><p>${text(plan.transport.title)}</p>${plan.transport.mode !== 'self' ? `<p>${text(plan.transfer?.title)}</p>` : '<p>Дорога и трансферы организуются самостоятельно.</p>'}
${timeline ? `<h2>Маршрут · время московское</h2><ol>${timeline}</ol>` : ''}
<h2>Условия и важные детали</h2>${[...new Set([...(plan.warnings || []), ...(plan.compromises || [])])].map(value => `<p>${text(value)}</p>`).join('')}
<footer class="notice">Это сохранённый план по демонстрационному каталогу. Отели, наличие, тарифы и расписания вымышлены. Бронирование и оплата не выполнены, письмо не отправлялось. План доступен через «Мои поездки» в том браузере, где вы его сохранили.</footer>
</main></body></html>`;
}

export function downloadPlan(order, requirements = {}) {
  const url = URL.createObjectURL(new Blob([planDocument(order, requirements)], { type: 'text/html;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `rivane-${String(order.reference || 'plan').replace(/[^a-zA-Z0-9А-Яа-я_-]/g, '')}.html`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
