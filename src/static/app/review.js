// Actions on the changeset review page: publish with notes, rebase, discard.

import { api, pageData, problem } from './api.js';
import { atLeast, needs, roleIn } from './roles.js';

export default () => ({
  page: {}, publishing: false, notes: '', error: '',

  init() { this.page = pageData(); this.notes = this.page.notes; },
  get newTree() { return !this.page.tree; },
  can(minimum) { return this.page.state === 'draft' && atLeast(roleIn(this.page.user, this.page.org), this.newTree ? 'owner' : minimum); },
  hint(minimum) {
    if (this.page.state !== 'draft') return `This changeset is ${this.page.state}`;
    return needs(this.page.user, this.page.org, this.newTree ? 'owner' : minimum);
  },
  get publishBlock() {
    const h = this.hint('approver');
    if (h) return h;
    return this.page.ok ? '' : 'Fix the errors and conflicts first';
  },
  openPublish() { this.publishing = true; },
  async publish() {
    const r = await api('POST', `/changesets/${this.page.id}/publish`, { notes: this.notes }, { 'If-Match': this.page.etag });
    this.publishing = false;
    if (r.status === 412) { this.error = 'The draft changed since this page loaded. Reload to review it again.'; return; }
    if (!r.ok) { this.error = problem(r); return; }
    window.location.href = `/trees/${r.data.id}/`;
  },
  async rebase() {
    const r = await api('PUT', `/changesets/${this.page.id}`, { base_rev: this.page.latest_rev }, { 'If-Match': this.page.etag });
    if (!r.ok) { this.error = problem(r); return; }
    window.location.reload();
  },
  async discard() {
    const r = await api('DELETE', `/changesets/${this.page.id}`);
    if (!r.ok) { this.error = problem(r); return; }
    window.location.reload();
  },
});
