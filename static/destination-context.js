export class DestinationLoader {
  constructor({ request, current, update }) { Object.assign(this, { request, current, update }); this.key = null; this.controller = null; }
  async load() {
    const session = this.current();
    if (!session?.requirements?.destination) return;
    const key = `${session.id}:${session.revision}`;
    if (key === this.key) return;
    this.controller?.abort();
    this.key = key;
    const controller = new AbortController();
    this.controller = controller;
    const timer = setTimeout(() => controller.abort(), 11000);
    try {
      const result = await this.request(`/api/sessions/${encodeURIComponent(session.id)}/destination-context?revision=${session.revision}`, { signal: controller.signal });
      if (this.key === key && `${this.current()?.id}:${this.current()?.revision}` === key) this.update(result);
    } catch {
      if (this.key === key && `${this.current()?.id}:${this.current()?.revision}` === key) this.update({ status: 'unavailable' });
    } finally { clearTimeout(timer); }
  }
  cancel() { this.controller?.abort(); this.controller = null; this.key = null; }
}

export const validExternal = value => {
  try { const url = new URL(value); return url.protocol === 'https:' && ['www.openstreetmap.org', 'open-meteo.com', 'project-osrm.org'].includes(url.hostname) && !url.username && !url.password ? url.href : null; } catch { return null; }
};
