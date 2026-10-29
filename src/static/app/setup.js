// The setup wizard for a new instance (spec: instance-setup): create the first
// organization, add its users, import its first trees. Everything goes
// through the API, as anywhere else in the web app; which step it opens at
// follows from the page data, so leaving and coming back works.

import { api, pageData, problem } from './api.js';
import * as X from './expanders.js';
import { fetchStep } from './jobs.js';

const STEPS = [
  { key: 'org', label: 'Organization' },
  { key: 'users', label: 'Users' },
  { key: 'trees', label: 'Trees' },
];

const emptyTree = () => ({ id: '', title: '', description: '', text: '' });

export default () => ({
  ...fetchStep(),  // the WoRMS fetch step and its progress bars
  steps: STEPS, step: 'org', orgs: [], roles: [], org: null,
  // Organization step
  orgForm: { id: '', name: '' }, orgError: '',
  // Users step
  members: [], userForm: { username: '', role: 'owner', password: '', password2: '' },
  needsPassword: false, userError: '', userNote: '', adding: false, discard: null,
  // Trees step
  treeForm: emptyTree(), treeErrors: [], importing: false, imported: [], pending: null,

  init() {
    const page = pageData();
    this.orgs = page.orgs;
    this.roles = page.roles;
    setInterval(() => { if (this.job) this.now = Date.now(); }, 250);
    if (this.orgs.length === 1) this.useOrg(this.orgs[0].id);
  },

  // ---- steps ----------------------------------------------------------------------
  stepClass(key) {
    const at = STEPS.findIndex(s => s.key === this.step);
    const i = STEPS.findIndex(s => s.key === key);
    return i === at ? 'text-bg-primary' : i < at ? 'text-bg-success' : 'text-bg-light border';
  },
  get orgName() { return this.orgs.find(o => o.id === this.org)?.name ?? ''; },
  get skipOrgHint() { return this.org ? '' : 'Create or pick an organization first: users and trees belong to one'; },
  skip() {
    if (this.step === 'org') { if (!this.skipOrgHint) this.goUsers(); }
    else if (this.step === 'users') this.leaveUsers();
    else this.leaveTrees('org');
  },
  /** Where leaving a step goes: the Trees step, the organization's page, or
   * (Done) the first imported tree. */
  goTo(next) {
    if (next === 'trees') this.step = 'trees';
    else if (next === 'org') window.location.href = `/orgs/${this.org}/`;
    else window.location.href = `/trees/${this.imported[0].id}/`;
  },
  async goUsers() {
    this.step = 'users';
    const r = await api('GET', `/orgs/${this.org}/members`);
    this.members = r.ok ? r.data.members : [];
    if (this.members.some(m => m.role === 'owner')) this.userForm.role = 'drafter';
  },

  // ---- Organization step -------------------------------------------------------------
  useOrg(id) { this.org = id; this.goUsers(); },
  async createOrg() {
    const r = await api('POST', '/orgs', { id: this.orgForm.id.trim(), name: this.orgForm.name });
    if (!r.ok) { this.orgError = problem(r); return; }
    this.orgError = '';
    this.orgs.push(r.data);
    this.useOrg(r.data.id);
  },

  // ---- Users step --------------------------------------------------------------------
  /** On to Trees, by Continue or Skip. A username typed but not added would be
   * lost without a trace, so ask first. */
  leaveUsers() {
    const name = this.userForm.username.trim();
    if (!name) return this.goTo('trees');
    this.discard = {
      title: 'Discard this user?', name, ok: 'Discard and continue', next: 'trees',
      text: "hasn't been added to the organization. Continue without adding them?",
    };
  },
  /** Leave by Skip or Done: ask first if the form holds a tree not imported,
   * or a saved draft that didn't publish (it stays a draft). */
  leaveTrees(next) {
    const t = this.treeForm;
    if (this.pending) {
      this.discard = {
        title: 'Leave this tree unpublished?', name: this.pending.tree.id, ok: 'Leave it as a draft', next,
        text: `is saved as draft #${this.pending.id} but not published. It stays a draft, which an owner can publish in the editor.`,
      };
    } else if ([t.id, t.title, t.description, t.text].some(v => v.trim())) {
      this.discard = {
        title: 'Discard this tree?', name: t.id.trim() || 'This tree', ok: 'Discard and leave', next,
        text: "hasn't been imported. Leave without importing it?",
      };
    } else {
      this.goTo(next);
    }
  },
  confirmDiscard() {
    const next = this.discard.next;
    this.discard = null;
    if (next === 'trees') {
      this.userForm = { ...this.userForm, username: '', password: '', password2: '' };
      this.usernameChanged();
    }
    this.goTo(next);
  },
  cancelDiscard() { this.discard = null; },
  usernameChanged() { this.needsPassword = false; this.userNote = ''; this.userError = ''; },
  get addHint() {
    const f = this.userForm;
    if (!f.username.trim()) return 'Enter a username';
    if (this.needsPassword && !f.password) return 'Enter an initial password';
    if (this.needsPassword && f.password !== f.password2) return "The passwords don't match";
    return '';
  },
  /** Add a member; a username with no account asks for an initial password
   * first, and the next Add creates the account. */
  async addUser() {
    const f = this.userForm;
    const username = f.username.trim();
    this.adding = true;
    try {
      if (this.needsPassword) {
        const u = await api('POST', '/users', { username, password: f.password });
        if (!u.ok && u.data?.error !== 'user_exists') { this.userError = problem(u); return; }
      }
      const r = await api('POST', `/orgs/${this.org}/members`, { username, role: f.role });
      if (r.status === 404 && !this.needsPassword) {
        this.needsPassword = true;
        this.userError = '';
        this.userNote = `${username} has no account yet: give an initial password to create it. They can change it on their account page.`;
        return;
      }
      if (!r.ok) {
        this.userError = r.data?.error === 'already_member' ? `${r.data.detail} Change their role on the organization page.` : problem(r);
        return;
      }
      this.userForm = { username: '', role: f.role, password: '', password2: '' };
      this.usernameChanged();
      await this.goUsers();
    } finally {
      this.adding = false;
    }
  },

  // ---- Trees step --------------------------------------------------------------------
  readFile(ev) {
    const file = ev.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const t = this.treeForm;
      t.text = reader.result;
      const stem = file.name.replace(/\.json$/i, '').replace(/[^A-Za-z0-9_-]/g, '_');
      if (!t.id) t.id = stem;
      if (!t.title) t.title = stem;
      this.formChanged();
    };
    reader.readAsText(file);
  },
  /** A failed publish keeps its draft for "Publish again", until the form changes. */
  formChanged() { this.pending = null; },
  get importHint() {
    const t = this.treeForm;
    if (this.importing) return 'Importing…';
    if (this.pending) return '';
    if (!t.id.trim() || !t.title.trim()) return 'Enter a tree id and a title';
    if (!t.text.trim()) return 'Paste or load an import file';
    return '';
  },
  get importLabel() { return this.pending ? 'Publish again' : 'Import'; },
  async importTree() {
    this.treeErrors = [];
    this.importing = true;
    try {
      if (this.pending) { await this.publish(); return; }
      const t = this.treeForm;
      let changes;
      try {
        changes = X.expandImport(JSON.parse(t.text), { group: 'import#1' });
      } catch (e) {
        this.treeErrors = [e instanceof X.ImportFormatError ? e.message : `Not valid JSON: ${e.message}`];
        return;
      }
      if (!changes.length) { this.treeErrors = ['The file has no nodes.']; return; }
      const body = { new_tree: { id: t.id.trim(), title: t.title.trim(), description: t.description, org: this.org }, changes };
      let v = await this.validate(body);
      if (v?.worms_missing.length) {
        await this.fetchMissing(this.org, v.worms_missing);  // proceeding leaves their checks unavailable
        v = await this.validate(body);
      }
      if (!v) return;
      const labels = new Map(changes.map(c => [c.node, c.label]));
      const problems = [...v.conflicts, ...v.errors].map(e =>
        (e.node ? `${labels.get(e.node) ?? e.node}: ` : '') + e.detail);
      if (problems.length) { this.treeErrors = problems; return; }
      const r = await api('POST', '/changesets', { ...body, notes: 'Imported in setup' });
      if (!r.ok) { this.treeErrors = [problem(r)]; return; }
      this.pending = { id: r.data.id, etag: r.etag, tree: body.new_tree };
      await this.publish();
    } catch (e) {
      this.treeErrors = [e.message];
    } finally {
      this.importing = false;
    }
  },
  async validate(body) {
    const r = await api('POST', '/changesets/validate', body);
    if (!r.ok) { this.treeErrors = [problem(r)]; return null; }
    return r.data;
  },
  /** Publish the saved draft; on failure it stays, for "Publish again" or the editor. */
  async publish() {
    const p = this.pending;
    if (!p.etag) {
      const cs = await api('GET', `/changesets/${p.id}`);
      if (!cs.ok) { this.treeErrors = [problem(cs)]; return; }
      p.etag = cs.etag;
    }
    const r = await api('POST', `/changesets/${p.id}/publish`, undefined, { 'If-Match': p.etag });
    if (!r.ok) {
      p.etag = null;  // read it again before the next try
      this.treeErrors = [`${problem(r)} The draft is saved as #${p.id}; publish it again here or open it in the editor.`];
      return;
    }
    this.imported.push({ id: p.tree.id, title: p.tree.title, rev: r.data.rev });
    this.pending = null;
    this.treeForm = emptyTree();
  },
  get draftLink() { return this.pending ? `/changesets/${this.pending.id}/edit/` : ''; },
  done() { this.leaveTrees('done'); },
});
