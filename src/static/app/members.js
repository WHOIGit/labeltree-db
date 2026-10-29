// The organization page's members (spec: webapp "Organization page").

import { api, pageData, problem } from './api.js';

export default () => ({
  org: null, members: [], roles: [], canManage: false, me: null,
  newUser: '', newRole: 'reader', error: '',

  init() {
    const page = pageData();
    Object.assign(this, { org: page.org, members: page.members, roles: page.roles, canManage: page.can_manage, me: page.me });
  },
  async reload() {
    const r = await api('GET', `/orgs/${this.org}/members`);
    if (r.ok) this.members = r.data.members;
  },
  explain(r) {
    if (r.data?.error === 'last_owner') return 'The organization needs an owner: make someone else an owner first.';
    return problem(r);
  },
  async setRole(username, role) {
    const r = await api('PUT', `/orgs/${this.org}/members/${encodeURIComponent(username)}`, { role });
    this.error = r.ok ? '' : this.explain(r);
    await this.reload();
  },
  async remove(username) {
    const r = await api('DELETE', `/orgs/${this.org}/members/${encodeURIComponent(username)}`);
    this.error = r.ok ? '' : this.explain(r);
    await this.reload();
  },
  async add() {
    await this.setRole(this.newUser.trim(), this.newRole);
    if (!this.error) this.newUser = '';
  },
});
