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
    if (r.data?.error === 'already_member') return `${r.data.detail} Change their role in the list.`;
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
  /** Add a user. The server refuses existing members (409 already_member), so a
   * stale list can't turn this into a role change. */
  async add() {
    const r = await api('POST', `/orgs/${this.org}/members`, { username: this.newUser.trim(), role: this.newRole });
    this.error = r.ok ? '' : this.explain(r);
    if (r.ok) this.newUser = '';
    await this.reload();
  },
});
