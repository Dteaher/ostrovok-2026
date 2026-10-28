// Optional narration never owns the trip or disables its controls.
export class ExplanationLoader {
  constructor({ getSession, request, apply }) {
    Object.assign(this, { getSession, request, apply });
    this.controller = null;
    this.key = null;
  }

  cancel() {
    this.controller?.abort();
    this.controller = null;
    this.key = null;
  }

  async load() {
    const session = this.getSession();
    if (session?.agent?.explanation_status !== 'pending') return;
    const key = `${session.id}:${session.revision}`;
    if (this.key === key) return;
    this.cancel();
    this.key = key;
    const controller = new AbortController();
    this.controller = controller;
    const remaining = Math.max(0, (session.response_timing?.limit_seconds || 10) - (session.response_timing?.elapsed_seconds || 0));
    const timer = setTimeout(() => controller.abort(), remaining * 1000);
    const stillCurrent = () => this.controller === controller && this.getSession()?.id === session.id && this.getSession()?.revision === session.revision;
    try {
      const result = await this.request(`/api/sessions/${encodeURIComponent(session.id)}/explanation`, {
        method: 'POST', body: JSON.stringify({ revision: session.revision }), signal: controller.signal
      });
      if (stillCurrent() && result.revision === session.revision && result.agent) this.apply(result.agent);
    } catch {
      if (stillCurrent()) this.apply({ ...session.agent, mode: 'local', explanation_status: 'unavailable',
        notice: 'Персональное AI-объяснение не загрузилось. Проверенные факты и варианты доступны — можно продолжать подбор.' });
    } finally {
      clearTimeout(timer);
    }
  }
}
