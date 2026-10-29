// The tree browser and draft editor (spec: webapp), ported from
// design/mockups/webapp-mockup.html. Composing happens here without calling
// the server; Validate sends the list to POST /changesets/validate, and Save
// stores it. All logic lives in this module: attributes only call its methods
// and read its properties (Alpine CSP build).

import { api, pageData, problem, retrying } from './api.js';
import * as X from './expanders.js';
import { jobPercent, pauseBar, poll, pollJob, retryBars, startJob } from './jobs.js';
import { applyLocal, childIndex, describe, fromExport, idOf, isPh, keyOf, nodePath, pill, touched, wormsUrl } from './model.js';
import { atLeast, needs, roleIn } from './roles.js';

// Not reactive on purpose: large, and replaced wholesale.
let BASE = new Map(); // the tree at the viewed revision, or a draft's base revision
let CUR = { state: new Map(), kids: new Map(), labels: new Map(), local: null };
let PREV = new Map(); // labels, as of the revision before the viewed one, of the nodes it changed
// Bumped by each choice of what to show (picking a revision, starting or
// opening a draft), but not by the reload after a sync: see loadFor.
let CHOICE = 0;

const TABS = [
  { key: 'edited', label: 'As edited' },
  { key: 'reduced', label: 'As reduced' },
  { key: 'bynode', label: 'By node' },
  { key: 'summary', label: 'Summary' },
  { key: 'worms', label: 'WoRMS warnings' },
  { key: 'errors', label: 'Errors' },
];

export default () => ({
  user: {}, trees: [], orgs: [], treeId: null, org: null, newTree: null,
  revisions: [], viewRev: null, latestRev: null,
  mode: 'static', draft: null, changes: [], dirty: false,
  revChanges: null, loading: true,
  exp: {}, filter: '', pick: null, hover: [], flash: null,
  collapsed: {}, menu: null, modal: null, f: {}, conf: null, toasts: [],
  rows: [], options: [],
  loadSeq: 0, wantedRev: null, watching: false,
  validation: null, validatedKey: null, validating: false, validations: 0,
  tab: 'edited', seen: {}, tabs: TABS,
  job: null, jobFailed: null, jobResolve: null, pauseSeen: {}, now: Date.now(),
  syncOpen: false, syncs: null, syncJob: null, syncFailed: null, syncKind: null,
  warningsOpen: false, warningsList: [], editOpen: false, drafts: { open: [], discarded: [] },
  aliasFailures: [], aliasError: null,

  async init() {
    const page = pageData();
    Object.assign(this, { user: page.user, trees: page.trees, orgs: page.orgs, treeId: page.tree, org: page.org,
                          newTree: page.new_tree, latestRev: page.latest_rev });
    setInterval(() => { if (this.job || this.syncJob) this.now = Date.now(); }, 250);
    window.addEventListener('beforeunload', e => { if (this.dirty) { e.preventDefault(); e.returnValue = ''; } });
    try {
      if (page.draft) await this.openDraft(page.draft);
      else if (this.treeId) { await this.loadRevisions(); await this.loadRev(this.latestRev); }
    } finally {
      this.loading = false;
    }
  },

  // ---- roles and state ------------------------------------------------------------
  get role() { return roleIn(this.user, this.org); },
  can(minimum) { return atLeast(this.role, minimum); },
  hint(minimum) { return needs(this.user, this.org, minimum); },
  get loggedIn() { return !!this.user?.username; },
  get frozen() { return this.mode === 'static' || this.draft?.state !== 'draft'; },
  get editable() { return !this.frozen && this.can(this.newTree ? 'owner' : 'drafter'); },
  get editHint() {
    if (this.mode === 'static') return 'Edit mode only';
    if (this.frozen) return 'This changeset is read-only';
    return this.hint(this.newTree ? 'owner' : 'drafter');
  },
  get status() {
    if (this.mode === 'static') return { text: 'Published (frozen)', cls: 'text-bg-success' };
    if (this.draft.state === 'discarded') return { text: 'Discarded (frozen)', cls: 'text-bg-dark' };
    if (this.draft.state === 'published') return { text: 'Published (frozen)', cls: 'text-bg-success' };
    if (this.dirty) return { text: 'Draft (unsaved)', cls: 'text-bg-warning' };
    if (this.draft.id) return { text: 'Draft (saved)', cls: 'text-bg-info' };
    return { text: 'None', cls: 'text-bg-secondary' };
  },
  get title() { return this.newTree ? `${this.newTree.id} (new tree)` : this.treeId; },
  get revLabel() { return this.mode === 'static' ? 'Revision:' : 'Base revision:'; },
  get draftLabel() { return this.draft?.id ? '#' + this.draft.id : 'new'; },
  get baseText() { return this.draft?.base_rev ?? 'none (new tree)'; },

  // ---- loading ---------------------------------------------------------------------
  async loadRevisions() {
    const r = await api('GET', `/trees/${this.treeId}/revisions?limit=1000`);
    this.revisions = r.data.revisions.map(x => ({
      rev: x.rev, text: `${x.rev} · ${x.published_at.slice(0, 10)} · ${x.author}` + (x.rev === r.data.revisions[0].rev ? ' (latest)' : ''),
    }));
    this.latestRev = r.data.revisions[0]?.rev ?? null;
  },
  async loadState(rev) {
    if (!this.treeId || rev == null) return new Map();
    const r = await api('GET', `/trees/${this.treeId}/export?rev=${rev}`);
    if (!r.ok) throw new Error(problem(r));
    return fromExport(r.data.nodes);
  },
  /**
   * Show revision `rev`. Every write of the displayed tree (here, and opening,
   * saving or rebasing a draft) bumps `loadSeq`, so a load that is overtaken
   * while it waits is dropped. Returns true once applied, false if
   * overtaken, and null if it failed (see loadFailed).
   */
  async loadRev(rev) {
    rev = Number(rev);
    this.wantedRev = rev;
    const seq = ++this.loadSeq;
    let state, revChanges, prev;
    try {
      const [s, changes] = await Promise.all([
        this.loadState(rev), api('GET', `/trees/${this.treeId}/revisions/${rev}/changes`),
      ]);
      if (seq !== this.loadSeq) return false;
      state = s;
      revChanges = changes.ok ? changes.data : null;
      prev = await this.previousLabels(revChanges, rev, state);
    } catch (e) {
      return this.loadFailed(seq, e);
    }
    if (seq !== this.loadSeq) return false;
    BASE = state;
    PREV = prev;
    this.viewRev = rev;
    this.revChanges = revChanges;
    if (!this.exp[this.treeKey]) this.expandTop();
    this.collapsed = {};
    this.refresh();
    return true;
  },
  /**
   * Labels, as of the revision before, of the nodes a revision's changes name
   * that its own `state` can't: renamed nodes' old names, and nodes no longer
   * there. Nodes the revision adds didn't exist before, so aren't asked for.
   */
  async previousLabels(revChanges, rev, state) {
    const changes = revChanges?.changes || [];
    if (rev <= 1 || !changes.length) return new Map();
    const added = new Set(changes.filter(c => c.op === 'add').map(c => c.node));
    const ids = new Set();
    for (const c of changes) {
      if (c.op === 'edit' && 'label' in c) ids.add(c.node);
      for (const id of touched(c)) if (!state.has(id)) ids.add(id);
    }
    const wanted = [...ids].filter(id => typeof id === 'number' && !added.has(id));
    const batches = [];
    for (let i = 0; i < wanted.length; i += 200) batches.push(wanted.slice(i, i + 200));  // short URLs
    const answers = await Promise.all(batches.map(b =>
      api('GET', `/trees/${this.treeId}/nodes?ids=${b.join(',')}&rev=${rev - 1}`)));
    const labels = new Map();
    for (const r of answers) for (const n of r.data?.nodes || []) if (n.label) labels.set(n.id, { label: n.label });
    return labels;
  },
  /** Load a draft's base revision as the displayed tree. Returns as loadRev does. */
  async loadBase(rev) {
    const seq = ++this.loadSeq;
    let state;
    try {
      state = await this.loadState(rev);
    } catch (e) {
      return this.loadFailed(seq, e);
    }
    if (seq !== this.loadSeq) return false;
    BASE = state;
    this.viewRev = rev;
    this.wantedRev = rev;
    return true;
  },
  /** A load failed: the shown tree stays, and so does the picker. Says why,
   * unless the load was overtaken anyway. */
  loadFailed(seq, e) {
    if (seq !== this.loadSeq) return false;
    this.wantedRev = this.viewRev;
    this.toast(`Couldn't load the tree: ${e.message}`, 'text-bg-danger');
    return null;
  },
  /**
   * Run `load` (a loadRev or loadBase) for the user's choice `choice`. The
   * reload after a sync can overtake it; then it runs again. A later choice
   * wins, and so does a failure: then it returns false.
   */
  async loadFor(choice, load) {
    for (let i = 0; i < 5; i++) {
      const applied = await load();
      if (applied !== false || choice !== CHOICE) return applied === true;
    }
    return false;
  },
  async selectTree(id) { window.location.href = `/trees/${id}/`; },
  async selectRev(rev) { CHOICE++; await this.loadRev(rev); },
  isWantedRev(rev) { return rev === this.wantedRev; },

  // ---- the tree -------------------------------------------------------------------------
  refresh() {
    let state = BASE, local = null;
    if (this.mode === 'edit') {
      local = applyLocal(BASE, this.changes);
      state = local.state;
    }
    const kids = childIndex(state, true);
    CUR = { state, kids, labels: X.labelIndex(state), local };
    const q = this.filter.trim().toLowerCase();
    let match = null;
    if (q) {
      match = new Set();
      for (const n of state.values()) {
        const aliases = (n.aliases || []).map(a => (a.alias ?? a).toLowerCase());
        if (n.label.toLowerCase().includes(q) || aliases.some(a => a.includes(q)))
          for (let m = n; m && !match.has(m.id); m = state.get(m.parent)) match.add(m.id);
      }
    }
    const exp = (this.exp[this.treeKey] ||= {});
    const pickBad = this.pick ? this.descendantsOf(this.pick.id) : null;
    const rows = [];
    const walk = (pid, depth) => {
      for (const id of kids.get(pid) || []) {
        if (match && !match.has(id)) continue;
        const n = state.get(id);
        const all = kids.get(id) || [];
        const open = match ? true : !!exp[keyOf(id)];
        const mark = !local ? '' : local.added.has(id) ? 'new' : n.dep ? 'dep' : local.bump.has(id) ? 'bump' : '';
        const cls = [mark && 'mark-' + mark, this.flash === id && 'flash',
                     q && n.label.toLowerCase().includes(q) && 'hit',
                     pickBad && (pickBad.has(id) || n.dep ? 'unpickable' : 'pickable')].filter(Boolean).join(' ');
        rows.push({ id, key: keyOf(id), depth, label: n.label, nk: all.filter(k => !state.get(k).dep).length,
                    hasKids: all.length > 0, open, mark, version: n.version, pill: pill(n), cls,
                    indent: `padding-left:${depth * 18 + 4}px`, bump: `v${n.version} → v${n.version + 1}` });
        if (open) walk(id, depth + 1);
      }
    };
    walk(null, 0);
    this.rows = rows;
    this.options = [...state.values()].filter(n => !n.dep)
      .sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }))
      .map(n => ({ id: n.id, key: keyOf(n.id), label: n.label, path: nodePath(state, n.id),
                   text: n.label + (n.parent != null ? `  (in ${state.get(n.parent)?.label})` : '') }));
  },
  get treeKey() { return this.treeId || this.newTree?.id || ''; },
  expandTop() {
    const exp = (this.exp[this.treeKey] ||= {});
    for (const n of BASE.values()) if (n.parent == null) exp[keyOf(n.id)] = true;
  },
  toggle(id) { const e = this.exp[this.treeKey]; e[keyOf(id)] = !e[keyOf(id)]; this.refresh(); },
  expandAll() { const e = this.exp[this.treeKey]; for (const id of CUR.kids.keys()) if (id != null) e[keyOf(id)] = true; this.refresh(); },
  collapseAll() { this.exp[this.treeKey] = {}; this.refresh(); },
  rowClick(r) { if (this.pick) return this.pickTarget(r.id); if (r.hasKids) this.toggle(r.id); },
  lbl(id) {
    if (id == null) return 'top level';
    return CUR.state.get(id)?.label ?? BASE.get(id)?.label ?? PREV.get(id)?.label ?? String(id);
  },
  live(id) { const n = CUR.state.get(id); return !!n && !n.dep; },
  liveKids(id) { return (CUR.kids.get(id) || []).filter(k => !CUR.state.get(k).dep); },
  descendantsOf(id) {
    const out = new Set([id]);
    const walk = p => (CUR.kids.get(p) || []).forEach(k => { out.add(k); walk(k); });
    walk(id);
    return out;
  },
  // Hover only changes the row classes, not the tree model.
  setHover(ids) { this.hover = (ids || []).filter(x => x != null); },
  clearHover() { this.hover = []; },
  rowClass(r) { return this.hover.includes(r.id) ? r.cls + ' hl' : r.cls; },
  /** Expand the node's ancestors, scroll to it and flash it. */
  reveal(id) {
    if (id == null || !CUR.state.has(id)) { if (id != null) this.toast(`${this.lbl(id)} isn't in this view`); return; }
    const e = (this.exp[this.treeKey] ||= {});
    for (let n = CUR.state.get(CUR.state.get(id).parent); n; n = CUR.state.get(n.parent)) e[keyOf(n.id)] = true;
    this.flash = id;
    this.refresh();
    this.$nextTick(() => document.getElementById('n-' + keyOf(id))?.scrollIntoView({ block: 'center' }));
    setTimeout(() => { if (this.flash === id) { this.flash = null; this.refresh(); } }, 1500);
  },
  onEscape() {
    if (this.conf) this.conf = null;
    else if (this.modal) this.closeModal();
    else if (this.menu) this.menu = null;
    else if (this.pick) { this.pick = null; this.refresh(); }
  },
  wormsUrl(id) { return wormsUrl(id); },

  // ---- static mode: the revision's changes ----------------------------------------------
  get revItems() {
    if (!this.revChanges) return [];
    return this.groupItems(this.revChanges.changes.map((c, i) => ({ c, i, text: describe(c, BASE, PREV) })));
  },
  get revHead() {
    return this.revChanges ? `revision ${this.revChanges.rev}` : '';
  },
  groupItems(rows) {
    const items = [];
    let cur = null;
    for (const row of rows) {
      const g = row.c.group;
      if (g) {
        if (!cur || cur.group !== g) {
          cur = { kind: 'group', group: g, key: 'g' + row.i, rows: [] };
          items.push(cur);
          // imports start collapsed, as do other large groups
          if (!(g in this.collapsed)) this.collapsed[g] = g.startsWith('import#') || rows.filter(r => r.c.group === g).length > 12;
        }
        cur.rows.push(row);
      } else {
        cur = null;
        items.push({ kind: 'one', key: 'c' + row.i, row });
      }
    }
    return items;
  },
  toggleGroup(g) { this.collapsed[g] = !this.collapsed[g]; },
  isCollapsed(g) { return !!this.collapsed[g]; },

  // ---- warnings panel ----------------------------------------------------------------------
  async toggleWarnings() {
    this.warningsOpen = !this.warningsOpen;
    if (this.warningsOpen) await this.loadWarnings();
  },
  async loadWarnings() {
    if (!this.treeId) return;
    const r = await api('GET', `/worms/warnings?tree=${this.treeId}&limit=1000`);
    this.warningsList = r.ok ? r.data.nodes : [];
  },
  warningText(n) { return n.worms_warnings.map(w => w.warning).join(', '); },

  // ---- edit menu and drafts ---------------------------------------------------------------
  async toggleEditMenu() {
    this.editOpen = !this.editOpen;
    if (!this.editOpen) return;
    const [open, discarded] = await Promise.all([
      api('GET', `/changesets?state=draft&tree=${this.treeId}`),
      api('GET', `/changesets?state=discarded&tree=${this.treeId}`),
    ]);
    this.drafts = { open: open.ok ? open.data.changesets : [], discarded: discarded.ok ? discarded.data.changesets : [] };
  },
  draftText(d) { return `base ${d.base_rev ?? 'none'} · ${d.author} · ${d.num_changes} changes`; },
  async startNewDraft() {
    this.editOpen = false;
    const choice = ++CHOICE;
    // Start only if the latest revision is what's shown: a draft builds on it.
    if (this.viewRev === this.latestRev) { this.loadSeq++; this.wantedRev = this.latestRev; }  // drop pending picks
    else if (!(await this.loadFor(choice, () => this.loadRev(this.latestRev)))) return;
    this.draft = { id: null, base_rev: this.latestRev, state: 'draft', notes: '', etag: null, author: this.user.username };
    this.enterEdit([]);
  },
  async openDraftFromMenu(id) { this.editOpen = false; await this.openDraft(id); },
  async openDraft(id) {
    const choice = ++CHOICE;
    const r = await api('GET', `/changesets/${id}`);
    if (!r.ok) { this.toast(problem(r), 'text-bg-danger'); return; }
    const cs = r.data;
    if (cs.tree) {
      this.treeId = cs.tree;
      if (!this.revisions.length) await this.loadRevisions();
      if (!(await this.loadFor(choice, () => this.loadBase(cs.base_rev)))) return;
    } else {
      this.loadSeq++;
      BASE = new Map();
      this.newTree = cs.new_tree;
      this.org = cs.new_tree.org;
    }
    this.draft = { id: cs.id, base_rev: cs.base_rev, state: cs.state, notes: cs.notes, etag: r.etag, author: cs.author };
    this.enterEdit(cs.changes.map(({ seq, ...c }) => c));
    if (cs.validation) this.setValidation(cs.validation);
    for (const c of this.changes) if (c.op === 'add' && c.parent == null) (this.exp[this.treeKey] ||= {})[keyOf(c.node)] = true;
    if (!BASE.size && this.changes.length) this.expandTop();
    this.refresh();
  },
  enterEdit(changes) {
    this.mode = 'edit';
    this.changes = changes;
    this.dirty = false;
    this.validation = null;
    this.validatedKey = null;
    this.seen = {};
    this.tab = 'edited';
    this.collapsed = {};
    if (!this.exp[this.treeKey]) this.expandTop();
    this.refresh();
  },
  exitEdit() {
    const go = async () => {
      this.mode = 'static'; this.draft = null; this.changes = []; this.dirty = false; this.pick = null;
      this.validation = null;
      if (this.newTree) { window.location.href = '/'; return; }
      await this.loadRevisions();
      await this.loadRev(this.latestRev);
    };
    if (this.dirty) this.confirm('Leave without saving?', 'The unsaved changes in this draft will be lost.', 'Leave', 'btn-danger', go);
    else go();
  },

  // ---- composing ------------------------------------------------------------------------------
  get changesKey() { return JSON.stringify([this.draft?.base_rev ?? null, this.changes]); },
  addChanges(list) {
    this.changes.push(...list);
    this.markDirty();
  },
  markDirty() { this.dirty = true; this.refresh(); },
  removeChange(i) { this.changes.splice(i, 1); this.markDirty(); },
  removeGroup(g) { this.changes = this.changes.filter(c => c.group !== g); this.markDirty(); },
  openMenu(r, ev) {
    const rect = ev.currentTarget.getBoundingClientRect();
    const n = CUR.state.get(r.id);
    const hint = this.editable ? (n.dep ? 'Deprecated in this draft' : '') : this.editHint;
    const direct = this.hint('drafter') || (isPh(r.id) ? 'Not published yet' : '');
    const describeHint = this.hint('drafter') || (isPh(r.id) && this.frozen ? this.editHint : '');
    const items = [
      { key: 'details', text: 'Details…', action: 'details' },
      { key: 'page', text: 'Node page', action: 'page', hint: isPh(r.id) ? 'Not published yet' : '' },
      { key: 'description', text: 'Edit description…', action: 'description', hint: describeHint },
      { key: 'aliases', text: 'Edit aliases…', action: 'aliases', hint: direct },
      { key: 'd1', divider: true },
      { key: 'edit', text: 'Edit…', action: 'edit', hint },
      { key: 'child', text: 'New child…', action: 'child', hint },
      { key: 'move', text: 'Move to…', action: 'move', hint },
      { key: 'split', text: 'Split…', action: 'split', hint },
      { key: 'merge', text: 'Merge…', action: 'merge', hint },
      { key: 'd2', divider: true },
      { key: 'dep', text: 'Deprecate…', action: 'deprecate', hint },
    ];
    const h = 360, w = 250;
    const y = rect.bottom + h > window.innerHeight ? Math.max(8, rect.top - h) : rect.bottom;
    this.menu = { id: r.id, label: r.label, items, style: `left:${Math.min(rect.left, window.innerWidth - w - 8)}px; top:${y}px` };
  },
  menuPick(m) {
    if (m.hint) return;
    const id = this.menu.id;
    this.menu = null;
    const actions = {
      details: () => this.openDetails(id), page: () => { window.location.href = `/nodes/${id}/`; },
      description: () => this.openDescription(id), aliases: () => this.openAliases(id),
      edit: () => this.openEdit(id), child: () => this.openAdd(id), move: () => this.startMove(id),
      split: () => this.openSplit(id), merge: () => this.openMerge(id), deprecate: () => this.openDeprecate(id),
    };
    actions[m.action]();
  },
  labelError(label, self, others = [], reserved = undefined) { return X.labelProblem(label, CUR.labels, self, others, reserved); },
  aphiaError(a) { return a === '' || a == null || /^\d+$/.test(String(a)) ? '' : 'AphiaID must be a number'; },
  aphiaVal(a) { return a === '' || a == null ? null : Number(a); },

  openAdd(parent) {
    const fixed = parent !== undefined && parent !== null;
    this.f = { mode: 'add', id: null, parent: fixed ? parent : null, parentFixed: fixed, parentKey: '',
               label: '', description: '', aphia: '', aliases: '' };
    this.modal = 'node';
  },
  openEdit(id) {
    const n = CUR.state.get(id);
    this.f = { mode: 'edit', id, orig: { ...n }, label: n.label, aphia: n.aphia_id ?? '' };
    this.modal = 'node';
  },
  get nodeTitle() {
    if (this.f.mode === 'edit') return 'Edit ' + this.f.orig.label;
    return this.f.parentFixed ? 'New child of ' + this.lbl(this.f.parent) : 'New node';
  },
  get nodeFormError() {
    if (this.modal !== 'node') return '';
    return this.labelError(this.f.label, this.f.id) || this.aphiaError(this.f.aphia);
  },
  submitNode() {
    const f = this.f;
    if (f.mode === 'add') {
      const node = X.placeholders(this.changes)();
      const parent = f.parentFixed ? f.parent : idOf(f.parentKey);
      const change = { op: 'add', node, label: f.label, parent, aphia_id: this.aphiaVal(f.aphia),
                       description: f.description, aliases: f.aliases.split(',').map(a => a.trim()).filter(Boolean) };
      this.addChanges([change]);
      if (parent != null) (this.exp[this.treeKey] ||= {})[keyOf(parent)] = true;
      this.closeModal();
      this.reveal(node);
      return;
    }
    const c = { op: 'edit', node: f.id };
    if (f.label !== f.orig.label) c.label = f.label;
    if (this.aphiaVal(f.aphia) !== (f.orig.aphia_id ?? null)) c.aphia_id = this.aphiaVal(f.aphia);
    if (Object.keys(c).length > 2) this.addChanges([c]);
    else this.toast('Nothing changed');
    this.closeModal();
  },
  startMove(id) { this.pick = { id, label: this.lbl(id) }; this.refresh(); },
  cancelPick() { this.pick = null; this.refresh(); },
  pickTarget(target) {
    const id = this.pick.id, n = CUR.state.get(id);
    if (target != null && (this.descendantsOf(id).has(target) || !this.live(target))) return;
    this.pick = null;
    if ((n.parent ?? null) === target) { this.toast('Already there'); this.refresh(); return; }
    this.addChanges([{ op: 'move', node: id, from_parent: n.parent, to_parent: target }]);
    if (target != null) this.reveal(id);
  },
  openDeprecate(id) { this.f = { id, kids: this.liveKids(id).length, sel: [], q: '' }; this.modal = 'deprecate'; },
  submitDeprecate() {
    this.addChanges([{ op: 'deprecate', node: this.f.id, successors: [...this.f.sel] }]);
    this.closeModal();
  },
  toggleSel(id) { const i = this.f.sel.indexOf(id); if (i < 0) this.f.sel.push(id); else this.f.sel.splice(i, 1); },
  isSel(id) { return this.f.sel.includes(id); },
  pickerOptions(q, exclude = []) {
    const s = (q || '').toLowerCase();
    return this.options.filter(o => !exclude.includes(o.id) && (!s || o.label.toLowerCase().includes(s))).slice(0, 60);
  },

  // ---- details, aliases and descriptions (outside changesets) --------------------------------
  openDetails(id) {
    const n = CUR.state.get(id), local = CUR.local;
    let version = n.version ? `v${n.version}` : 'v1 on publish';
    if (local?.bump.has(id)) version += ` → v${n.version + 1} on publish`;
    this.f = {
      label: n.label, aphia: n.aphia_id, warns: n.warnings || [],
      rows: [
        ['Id', String(id)], ['Path', nodePath(CUR.state, id) || '(top level)'], ['Version', version],
        ['Created in revision', n.created ?? 'this draft'], ['Description', n.description || '—'],
        ['Aliases', (n.aliases || []).map(a => a.alias ?? a).join(', ') || '—'],
        ['Children', String(this.liveKids(id).length)],
      ],
    };
    this.modal = 'details';
  },
  openDescription(id) { this.f = { id, text: CUR.state.get(id).description || '', inDraft: isPh(id) }; this.modal = 'description'; },
  async saveDescription() {
    const f = this.f;
    if (f.inDraft) {
      const add = this.changes.find(c => c.op === 'add' && c.node === f.id);
      add.description = f.text;
      this.closeModal();
      this.markDirty();
      return;
    }
    const r = await api('PUT', `/nodes/${f.id}/description`, { description: f.text });
    if (!r.ok) { this.toast(problem(r), 'text-bg-danger'); return; }
    for (const s of [BASE, CUR.state]) if (s.has(f.id)) s.get(f.id).description = f.text;
    this.toast(`Description of ${this.lbl(f.id)} saved`);
    this.closeModal();
  },
  openAliases(id) { this.f = { id, list: [...(CUR.state.get(id).aliases || [])], add: '', error: '' }; this.modal = 'aliases'; },
  async addAlias() {
    const text = this.f.add.trim();
    if (!text) return;
    const r = await api('POST', `/nodes/${this.f.id}/aliases`, { alias: text });
    if (!r.ok) { this.f.error = problem(r); return; }
    this.f.list.push(r.data);
    this.f.add = '';
    this.f.error = '';
    this.storeAliases();
  },
  async removeAlias(a) {
    const r = await api('DELETE', `/nodes/${this.f.id}/aliases/${a.id}`);
    if (!r.ok) { this.f.error = problem(r); return; }
    this.f.list = this.f.list.filter(x => x.id !== a.id);
    this.storeAliases();
  },
  storeAliases() { for (const s of [BASE, CUR.state]) if (s.has(this.f.id)) s.get(this.f.id).aliases = [...this.f.list]; },

  // ---- merge and split wizards ------------------------------------------------------------------
  openMerge(id) {
    this.f = { wizard: 'merge', steps: ['nodes', 'mode', 'new node', 'review'], a: id, step: 1, sel: [], q: '',
               repl: true, survivorKey: keyOf(id), parts: [{ label: '', aphia: '', description: '' }],
               parentKey: null, preview: null };
    this.modal = 'wizard';
  },
  openSplit(id) {
    const kids = this.liveKids(id);
    this.f = { wizard: 'split', steps: ['mode', 'new nodes', 'children', 'review'], a: id, step: 1, repl: true, kids,
               assign: Object.fromEntries(kids.map(k => [keyOf(k), ''])),
               parts: [{ label: '', aphia: '', description: '' }, { label: '', aphia: '', description: '' }], preview: null };
    this.modal = 'wizard';
  },
  get wizTitle() {
    return `${this.f.wizard === 'merge' ? 'Merge ' : 'Split '}${this.lbl(this.f.a)} · step ${this.f.step} of 4: ${this.f.steps[this.f.step - 1]}`;
  },
  wizIs(wizard, step) { return this.f.wizard === wizard && this.f.step === step; },
  get wizModeStep() { return (this.f.wizard === 'merge' && this.f.step === 2) || (this.f.wizard === 'split' && this.f.step === 1); },
  setRepl(on) {
    this.f.repl = on;
    if (this.f.wizard === 'split') {
      const min = on ? 2 : 1;
      while (this.f.parts.length < min) this.f.parts.push({ label: '', aphia: '', description: '' });
      if (!on && this.f.parts.length === 2 && !this.f.parts[1].label) this.f.parts.pop();
    }
  },
  addPart() { this.f.parts.push({ label: '', aphia: '', description: '' }); },
  removePart(i) { this.f.parts.splice(i, 1); },
  canRemovePart() { return this.f.parts.length > (this.f.repl ? 2 : 1); },
  survivor() { return idOf(this.f.survivorKey); },
  mergeIds() { return [this.f.a, ...this.f.sel]; },
  mergeCandidates() {
    const a = this.f.a, s = (this.f.q || '').toLowerCase();
    const bad = this.descendantsOf(a);
    for (let n = CUR.state.get(CUR.state.get(a).parent); n; n = CUR.state.get(n.parent)) bad.add(n.id);
    const parent = CUR.state.get(a).parent;
    return this.options
      .filter(o => !bad.has(o.id) && (!s || o.label.toLowerCase().includes(s)))
      .sort((x, y) => (CUR.state.get(y.id).parent === parent) - (CUR.state.get(x.id).parent === parent))
      .slice(0, 80);
  },
  mergeParentOptions() {
    const bad = new Set();
    for (const id of this.mergeIds()) this.descendantsOf(id).forEach(x => bad.add(x));
    return this.options.filter(o => !bad.has(o.id));
  },
  commonParent(ids) {
    const chain = id => { const out = []; for (let p = CUR.state.get(id).parent; p != null; p = CUR.state.get(p).parent) out.push(p); return out; };
    const [first, ...rest] = ids.map(chain);
    return first.find(p => rest.every(c => c.includes(p))) ?? null;
  },
  /** Nodes the wizard deprecates; their labels stay taken (see X.labelProblem). */
  wizardDeprecates() {
    const f = this.f;
    if (f.wizard === 'merge') return f.repl ? this.mergeIds() : this.mergeIds().filter(id => id !== this.survivor());
    return f.repl ? [f.a] : [];
  },
  /** The parts' label and AphiaID errors. */
  partErrors() {
    const labels = this.f.parts.map(p => p.label);
    const reserved = new Set(this.wizardDeprecates());
    return this.f.parts.map((p, i) =>
      this.labelError(p.label, null, labels.filter((_, j) => j !== i), reserved) || this.aphiaError(p.aphia));
  },
  partError(i) { return this.f.parts[i].label ? this.partErrors()[i] : ''; },
  get wizError() {
    const f = this.f;
    if (f.wizard === 'merge') {
      if (f.step === 1 && !f.sel.length) return 'Choose at least one node to merge with';
      if (f.step === 3 && f.repl) return this.partErrors()[0];
    }
    if (f.wizard === 'split') {
      if (f.step === 2) return this.partErrors().find(Boolean) || '';
      if (f.step === 3 && f.repl && X.unassigned(CUR.state, f.a, f.assign).length) return 'Assign every child';
    }
    return '';
  },
  wizBack() { if (this.f.step > 1) this.f.step--; else this.closeModal(); },
  wizNext() {
    const f = this.f;
    if (f.wizard === 'merge' && f.step === 1 && f.parentKey === null) f.parentKey = keyOf(this.commonParent(this.mergeIds()));
    f.step++;
    if (f.step === 4) {
      const changes = f.wizard === 'merge' ? this.mergeChanges() : this.splitChanges();
      const after = applyLocal(CUR.state, changes).state;
      const offset = this.changes.length;
      f.preview = { group: changes[0]?.group, changes,
                    rows: changes.map((c, i) => ({ i: offset + i, op: c.op, text: describe(c, after, CUR.state) })) };
    }
  },
  wizAdd() { const changes = this.f.preview.changes; this.closeModal(); this.addChanges(changes); },
  part(p) { return { label: p.label, aphia_id: this.aphiaVal(p.aphia), description: p.description }; },
  mergeChanges() {
    const f = this.f;
    return X.mergeChanges({
      state: CUR.state, nodes: this.mergeIds(), replace: f.repl, survivor: this.survivor(), newNode: this.part(f.parts[0]),
      parent: idOf(f.parentKey), group: X.nextGroup('merge', this.changes), ph: X.placeholders(this.changes),
    });
  },
  splitChanges() {
    const f = this.f;
    return X.splitChanges({
      state: CUR.state, a: f.a, replace: f.repl, parts: f.parts.map(p => this.part(p)), assign: f.assign,
      group: X.nextGroup('split', this.changes), ph: X.placeholders(this.changes),
    });
  },
  get mergeNote() {
    return `After publishing, the deprecated nodes' labels and aliases are copied into the aliases of ${this.f.repl ? 'the new node' : this.lbl(this.survivor())}.`;
  },

  // ---- import, Add from WoRMS, clone --------------------------------------------------------
  openImport() { this.f = { text: '', under: '', error: '' }; this.modal = 'import'; },
  readImportFile(ev) {
    const file = ev.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => { this.f.text = reader.result; };
    reader.readAsText(file);
  },
  submitImport() {
    let data;
    try { data = JSON.parse(this.f.text); } catch (e) { this.f.error = 'Not valid JSON: ' + e.message; return; }
    const group = X.nextGroup('import', this.changes);
    const start = Number(X.placeholders(this.changes)().slice(4)) - 1;
    let changes;
    try { changes = X.expandImport(data, { parent: idOf(this.f.under), group, start }); }
    catch (e) { this.f.error = e.message; return; }
    this.collapsed[group] = true;
    this.closeModal();
    this.addChanges(changes);
    this.toast(`${changes.length} nodes added as ${group}`);
  },
  openWorms() { this.f = { q: '', results: [], picked: null, parentKey: '', label: '', error: '', searching: false }; this.modal = 'worms'; },
  async searchWorms() {
    this.f.searching = true;
    this.f.error = '';
    const r = await api('GET', `/worms/search?name=${encodeURIComponent(this.f.q)}&limit=20`);
    this.f.searching = false;
    if (!r.ok) { this.f.error = problem(r); return; }
    this.f.results = r.data.results;
    if (!this.f.results.length) this.f.error = 'No WoRMS records match.';
  },
  async pickWorms(rec) {
    this.f.picked = rec;
    this.f.label = X.wormsLabel(rec.scientificname);
    const r = await api('GET', `/worms/${rec.AphiaID}/lineage`);
    const parent = r.ok ? X.suggestParent(r.data.lineage, CUR.state) : null;
    this.f.parentKey = keyOf(parent);
    this.f.suggested = parent;
  },
  get wormsError() { return this.f.picked ? this.labelError(this.f.label, null) : 'Pick a record'; },
  submitWorms() {
    const node = X.placeholders(this.changes)();
    const parent = idOf(this.f.parentKey);
    this.addChanges([{ op: 'add', node, label: this.f.label, parent, aphia_id: this.f.picked.AphiaID, description: '', aliases: [] }]);
    if (parent != null) (this.exp[this.treeKey] ||= {})[keyOf(parent)] = true;
    this.closeModal();
    this.reveal(node);
  },
  get ownedOrgs() {
    if (!this.loggedIn) return [];
    return this.orgs.filter(o => roleIn(this.user, o.id) === 'owner');
  },
  get cloneHint() { return this.loggedIn ? (this.ownedOrgs.length ? '' : 'Needs the owner role in an organization') : 'Log in to edit'; },
  openClone() { this.f = { org: this.ownedOrgs[0]?.id ?? '', id: '', title: '', description: '', error: '' }; this.modal = 'clone'; },
  get cloneError() {
    if (!X.LABEL_RE.test(this.f.id || '') || /[.]/.test(this.f.id)) return 'Use letters, digits, _ and -';
    if (this.trees.some(g => g.trees.some(t => t.id === this.f.id))) return 'A tree with this id exists';
    if (!this.f.title.trim()) return 'A title is needed';
    return '';
  },
  async submitClone() {
    const changes = X.expandImport(X.cloneData(BASE), { group: 'import#1' });
    const r = await api('POST', '/changesets', {
      new_tree: { id: this.f.id, title: this.f.title, description: this.f.description, org: this.f.org },
      changes, notes: `Clone of ${this.treeId} revision ${this.viewRev}.`,
    });
    if (!r.ok) { this.f.error = problem(r); return; }
    window.location.href = `/changesets/${r.data.id}/edit/`;
  },

  // ---- validate ----------------------------------------------------------------------------------
  get stale() { return !!this.validation && this.validatedKey !== this.changesKey; },
  get validateBlock() {
    if (this.frozen) return this.editHint;
    if (!this.changes.length) return 'No changes yet';
    if (this.validating) return 'Validating…';
    if (this.validation && !this.stale) return 'Already validated';
    return '';
  },
  validateBody() {
    const base = { changes: this.changes };
    if (this.newTree) return { ...base, new_tree: { id: this.newTree.id, title: this.newTree.title || this.newTree.id, org: this.newTree.org } };
    return { ...base, tree: this.treeId, base_rev: this.draft.base_rev };
  },
  async callValidate() {
    const r = await api('POST', '/changesets/validate', this.validateBody());
    if (!r.ok) throw new Error(problem(r));
    return r.data;
  },
  async validate() {
    const key = this.changesKey;
    this.validating = true;
    try {
      let v = await this.callValidate();
      if (v.worms_missing.length && await this.fetchMissing(v.worms_missing)) v = await this.callValidate();
      if (this.changesKey === key) this.setValidation(v);
    } catch (e) {
      this.toast(e.message, 'text-bg-danger');
    } finally {
      this.validating = false;
      this.job = null;
    }
  },
  setValidation(v) {
    this.validation = v;
    this.validatedKey = this.changesKey;
    this.validations++;
    this.seen[this.tab] = this.tabHash(this.tab);
  },
  /** Run fetch jobs until the AphiaIDs are cached or the user proceeds without them. */
  async fetchMissing(ids) {
    for (;;) {
      const job = await startJob({ kind: 'fetch', org: this.org, aphia_ids: ids });
      this.job = job;
      const done = await pollJob(job.id, s => { this.job = s; });
      if (!done.failed.length) return true;
      this.jobFailed = done.failed;
      const choice = await new Promise(resolve => { this.jobResolve = resolve; });
      this.jobFailed = null;
      if (choice !== 'retry') return true;
      ids = done.failed.map(x => x.aphia_id);
    }
  },
  tryAgain() { this.jobResolve?.('retry'); },
  proceedAnyway() { this.jobResolve?.('proceed'); },
  jobBar(j) { return `width:${jobPercent(j)}%`; },
  jobText(j) { return `${j.kind} · ${j.done} of ${j.total} AphiaIDs` + (j.failed.length ? ` · ${j.failed.length} failed` : ''); },
  retries(j) { this.now; return retryBars(j, this.now); },
  pause(j) { this.now; return pauseBar(j, this.pauseSeen, this.now); },
  width(p) { return `width:${p}%`; },

  // ---- changes panel tabs ---------------------------------------------------------------------
  tabHash(key) {
    const v = this.validation;
    if (!v) return '';
    const pick = { reduced: v.reduced_changes, bynode: v.node_changes, summary: [v.ok, v.errors.length, v.warnings.length],
                   worms: [v.warnings, v.warning_changes, v.unchecked], errors: [v.errors, v.conflicts], edited: [v.errors, v.warnings] };
    return JSON.stringify(pick[key]);
  },
  selectTab(key) { this.tab = key; this.seen[key] = this.tabHash(key); },
  unread(key) {
    if (!this.validation || key === this.tab) return false;
    const h = this.tabHash(key);
    return h !== this.seen[key] && h !== '[]' && h !== '[[],[]]' && h !== '[[],[],[]]';
  },
  tabCount(key) {
    const v = this.validation;
    if (!v) return '';
    if (key === 'errors') return String(v.errors.length + v.conflicts.length);
    if (key === 'worms') return String(v.warnings.length);
    return '';
  },
  tabClass(key) { return { active: this.tab === key }; },
  /** Per composed position: the errors and warnings of the reduced changes built from it. */
  get bySource() {
    const out = {};
    const v = this.validation;
    if (!v) return out;
    const at = (seq, kind, text) => {
      const src = seq == null ? [] : (v.reduced_changes[seq - 1]?.sources || []);
      for (const p of src) ((out[p - 1] ||= { errors: [], warnings: [] })[kind]).push(text);
    };
    for (const e of v.errors) at(e.seq, 'errors', `${e.error}: ${e.detail}`);
    for (const w of v.warnings) at(w.seq, 'warnings', `${w.warning}: ${w.detail}`);
    return out;
  },
  get editedItems() {
    const checks = this.bySource;
    return this.groupItems(this.changes.map((c, i) => ({
      c, i, op: c.op, text: describe(c, CUR.state, BASE), touched: touched(c),
      errors: checks[i]?.errors || [], warnings: checks[i]?.warnings || [],
    })));
  },
  get reducedRows() {
    return (this.validation?.reduced_changes || []).map(c => ({
      key: c.seq, seq: c.seq, op: c.op, text: describe(c, CUR.state, BASE), touched: touched(c), sources: c.sources.join(', '),
    }));
  },
  get nodeRows() {
    return (this.validation?.node_changes || []).map(n => ({
      key: keyOf(n.node), node: n.node, label: this.lbl(n.node),
      version: `${n.from ? 'v' + n.from : 'new'} → ${n.to ? 'v' + n.to : 'deprecated'}`,
      lines: [
        ...Object.entries(n.fields).map(([f, [a, b]]) => `${f}: ${f === 'parent' ? this.lbl(a) : (a ?? '—')} → ${f === 'parent' ? this.lbl(b) : (b ?? '—')}`),
        ...(n.children_gained.length ? [`gains ${n.children_gained.map(c => this.lbl(c)).join(', ')}`] : []),
        ...(n.children_lost.length ? [`loses ${n.children_lost.map(c => this.lbl(c)).join(', ')}`] : []),
        ...(n.successors ? [`successors ${n.successors.map(c => this.lbl(c)).join(', ') || 'none'}`] : []),
      ],
      groups: n.groups,
    }));
  },
  get summaryLines() {
    const v = this.validation;
    if (!v) return [];
    const nc = v.node_changes;
    return [
      `${this.changes.length} changes as edited, ${v.reduced_changes.length} after reduction`,
      `${nc.filter(n => n.from == null).length} new nodes · ${nc.filter(n => n.from && n.to).length} version increases · ${nc.filter(n => n.to == null).length} deprecated`,
      `${v.errors.length} errors · ${v.warnings.length} WoRMS warnings` + (v.worms === 'unavailable' ? ` · checks unavailable for AphiaIDs ${v.worms_missing.join(', ')}` : ''),
      v.conflicts.length ? 'Behind the latest revision: rebase before publishing' : 'Up to date with the latest revision',
    ];
  },
  warnRows() {
    return (this.validation?.warnings || []).map((w, i) => ({ key: i, node: w.node, text: `${this.lbl(w.node)}: ${w.warning}: ${w.detail}` }));
  },
  warnChangeRows() {
    return (this.validation?.warning_changes || []).map(w => ({
      key: w.node, node: w.node,
      text: `${this.lbl(w.node)}: ${[...w.added.map(a => '+' + a), ...w.removed.map(r => '−' + r)].join(' ')}`,
    }));
  },
  errorRows() {
    const v = this.validation;
    if (!v) return [];
    return [
      ...v.conflicts.map((c, i) => ({ key: 'c' + i, node: null, text: `${c.error}: ${c.detail}`,
                                       sub: (c.nodes || []).map(n => `${this.lbl(n.node)}: ${n.detail}`) })),
      ...v.errors.map((e, i) => ({ key: 'e' + i, node: e.node, text: `change ${e.seq ?? '—'}: ${e.error}: ${e.detail}`, sub: [] })),
    ];
  },
  get conflicts() { return this.validation?.conflicts?.filter(c => c.error === 'stale_base') || []; },

  // ---- save, rebase, publish, discard ----------------------------------------------------------
  get saveBlock() {
    if (this.frozen) return this.editHint;
    const h = this.hint(this.newTree ? 'owner' : 'drafter');
    if (h) return h;
    if (!this.dirty) return 'No unsaved changes';
    if (!this.validation || this.stale) return 'Validate first';
    return '';
  },
  get publishBlock() {
    const h = this.hint(this.newTree ? 'owner' : 'approver');
    if (h) return h;
    if (!this.draft?.id || this.dirty) return 'Save the draft first';
    if (!this.validation || this.stale) return 'Validate first';
    if (this.validation.errors.length) return `Fix ${this.validation.errors.length} errors first`;
    if (this.validation.conflicts.length) return 'Rebase on the latest revision first';
    return '';
  },
  save() {
    if (this.validation.errors.length) {
      this.confirm('Save a draft with errors?',
        `This draft has ${this.validation.errors.length} structural errors. It can be saved, but it will not be publishable as it is.`,
        'Save anyway', 'btn-warning', () => this.doSave());
    } else this.doSave();
  },
  async doSave(extra = {}) {
    const body = { changes: this.changes, notes: this.draft.notes, ...extra };
    let r;
    if (this.draft.id) r = await api('PUT', `/changesets/${this.draft.id}`, body, { 'If-Match': this.draft.etag });
    else r = await api('POST', '/changesets', { tree: this.treeId, base_rev: this.draft.base_rev, ...body });
    if (r.status === 412) return this.changedElsewhere();
    if (!r.ok) { this.toast(problem(r), 'text-bg-danger'); return false; }
    await this.stored(r);
    this.toast(`Draft #${r.data.id} saved`);
    return true;
  },
  /** Show a saved draft. If loading its new base revision is overtaken, the
   * user has opened something else, so it's left alone. If the load fails,
   * the old base stays; the next save loads the new one again. */
  async stored(r) {
    const cs = r.data;
    const loaded = cs.base_rev === this.draft.base_rev || await this.loadBase(cs.base_rev);
    if (loaded === false) return;
    const base_rev = loaded ? cs.base_rev : this.draft.base_rev;
    this.draft = { ...this.draft, id: cs.id, base_rev, etag: r.etag, state: cs.state, notes: cs.notes };
    this.changes = cs.changes.map(({ seq, ...c }) => c);
    this.dirty = false;
    this.setValidation(cs.validation);
    this.refresh();
    if (window.location.pathname !== `/changesets/${cs.id}/edit/`) history.replaceState(null, '', `/changesets/${cs.id}/edit/`);
  },
  changedElsewhere() {
    this.confirm('The draft changed', 'Someone saved this draft since you opened it. Reload it? Your unsaved changes here will be lost.',
                 'Reload', 'btn-primary', () => { this.dirty = false; this.openDraft(this.draft.id); });
    return false;
  },
  async rebase() {
    await this.loadRevisions();
    if (!this.draft.id) {
      if (!(await this.loadBase(this.latestRev))) return;
      this.draft.base_rev = this.latestRev;
      this.markDirty();
      return;
    }
    if (await this.doSave({ base_rev: this.latestRev })) this.toast(`Rebased on revision ${this.latestRev}`);
  },
  openPublish() { this.f = { notes: this.draft.notes }; this.modal = 'publish'; },
  async doPublish() {
    const r = await api('POST', `/changesets/${this.draft.id}/publish`, { notes: this.f.notes }, { 'If-Match': this.draft.etag });
    if (r.status === 412) { this.closeModal(); return this.changedElsewhere(); }
    if (!r.ok) {
      this.closeModal();
      if (r.data?.validation) this.setValidation(r.data.validation);
      this.toast(problem(r), 'text-bg-danger');
      return;
    }
    this.closeModal();
    this.draft.state = 'published';  // frozen from here on, even if copying aliases fails
    this.dirty = false;
    this.toast(`Published revision ${r.data.rev}`);
    const merged = this.changes.some(c => c.group?.startsWith('merge#'));
    if (merged && !(await this.copyMergeAliases())) return;  // the dialog offers Retry and Skip
    await this.exitAfterPublish();
  },
  /** After a merge publishes: each deprecated node's label and aliases become
   * aliases of its successor, skipping ones it has. Not part of the publish.
   * The published changeset names the successors' ids; if it can't be read,
   * the dialog says so. */
  async copyMergeAliases() {
    const cs = await retrying(() => api('GET', `/changesets/${this.draft.id}`));
    this.aliasError = cs.ok ? null : problem(cs);
    if (!cs.ok) { this.aliasFailures = []; this.modal = 'aliasFailures'; return false; }
    const wanted = [];
    for (const c of cs.data.changes) {
      if (c.op !== 'deprecate' || !c.group?.startsWith('merge#') || c.successors.length !== 1) continue;
      const old = BASE.get(c.node);
      if (!old) continue;
      for (const alias of [old.label, ...(old.aliases || []).map(a => a.alias ?? a)]) wanted.push({ node: c.successors[0], alias });
    }
    return this.addAliases(wanted);
  },
  async addAliases(wanted) {
    const failed = [];
    const have = {};
    for (const w of wanted) {
      if (!have[w.node]) {
        const r = await api('GET', `/nodes/${w.node}/aliases`);
        have[w.node] = new Set((r.data?.aliases || []).map(a => a.alias));
      }
      if (have[w.node].has(w.alias)) continue;
      const r = await api('POST', `/nodes/${w.node}/aliases`, { alias: w.alias });
      if (r.ok || r.status === 409) have[w.node].add(w.alias);
      else failed.push({ ...w, error: problem(r) });
    }
    this.aliasFailures = failed;
    if (failed.length) this.modal = 'aliasFailures';
    return !failed.length;
  },
  async retryAliases() {
    const [list, reread] = [this.aliasFailures, this.aliasError];
    this.closeModal();
    if (await (reread ? this.copyMergeAliases() : this.addAliases(list))) await this.exitAfterPublish();
  },
  async exitAfterPublish() {
    if (this.newTree) { window.location.href = `/trees/${this.newTree.id}/`; return; }
    this.mode = 'static'; this.draft = null; this.changes = [];
    await this.loadRevisions();
    await this.loadRev(this.latestRev);
  },
  discardDraft() {
    this.confirm(`Discard draft #${this.draft.id}?`, 'It is kept for the record, read-only, and can no longer be published.', 'Discard', 'btn-danger', async () => {
      const r = await api('DELETE', `/changesets/${this.draft.id}`);
      if (!r.ok) { this.toast(problem(r), 'text-bg-danger'); return; }
      this.toast(`Draft #${this.draft.id} discarded`);
      this.dirty = false;
      this.exitEdit();
    });
  },

  // ---- WoRMS syncs ------------------------------------------------------------------------------
  async toggleSync() {
    this.syncOpen = !this.syncOpen;
    if (this.syncOpen) this.watchSyncs();
  },
  async watchSyncs() {
    if (this.watching) return;  // one loop, however often the menu opens
    this.watching = true;
    try {
      await poll(() => api('GET', `/worms/jobs?tree=${this.treeId}`), {
        active: () => this.syncOpen || this.syncs?.active,
        onUpdate: async data => {
          const wasActive = this.syncs?.active;
          this.syncs = data;
          if (wasActive && !data.active) await this.afterSync(data.last);
        },
      });
    } catch (e) {
      // Only worth saying if a running sync drops out of view.
      if (this.syncs?.active) this.toast(`Lost track of the running sync: ${e.message}`, 'text-bg-danger');
      this.syncs = null;
    } finally {
      this.watching = false;
    }
  },
  syncHint(kind) {
    if (kind === 'sync_all' && !this.user.superuser) return 'Site admins only';
    if (this.syncs?.active) return 'A sync is running';
    return this.hint('drafter');
  },
  async startSync(kind, aphiaIds = null) {
    if (this.syncHint(kind)) return;
    const body = kind === 'sync_all' ? { kind } : { kind, tree: this.treeId };
    if (aphiaIds) body.aphia_ids = aphiaIds;
    let job;
    try { job = await startJob(body); } catch (e) { this.toast(e.message, 'text-bg-danger'); return; }
    this.syncKind = kind;
    this.syncFailed = null;
    this.syncJob = job;
    let done;
    try {
      done = await pollJob(job.id, s => { this.syncJob = s; });
    } catch (e) {
      this.toast(`Lost track of the sync: ${e.message}`, 'text-bg-danger');
      return;
    } finally {
      this.syncJob = null;
    }
    await this.afterSync(done);
  },
  async afterSync(status) {
    if (status?.failed?.length && status.started_by === this.user.username) this.syncFailed = status;
    if (this.mode === 'static') await this.loadRev(this.wantedRev ?? this.viewRev);
    if (this.warningsOpen) await this.loadWarnings();
  },
  get syncRunning() { return this.syncJob || this.syncs?.active || null; },
  syncAgain() { const s = this.syncFailed; this.syncFailed = null; this.startSync(s.kind, s.failed.map(f => f.aphia_id)); },
  dismissSync() { this.syncFailed = null; },

  // ---- dialogs ------------------------------------------------------------------------------------
  closeModal() { this.modal = null; this.f = {}; },
  confirm(title, body, ok, cls, fn) { this.conf = { title, body, ok, cls, fn }; },
  confirmOk() { const fn = this.conf.fn; this.conf = null; fn(); },
  toast(text, cls = 'text-bg-dark') {
    const t = { id: Math.random(), text, cls };
    this.toasts.push(t);
    setTimeout(() => { this.toasts = this.toasts.filter(x => x !== t); }, 3500);
  },
});
