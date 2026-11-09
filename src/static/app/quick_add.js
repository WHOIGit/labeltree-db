// The Quick add page (spec: webapp, quick-add): a client of
// POST /trees/{tree}/quick_add like any other. Preview sends the form; Confirm
// sends the previewed request again with its key, so it publishes what was
// shown even if the form changed since.

import { api, pageData, problem } from './api.js';
import { wormsUrl } from './model.js';

// Why a confirm returned a new preview instead of publishing.
const REASONS = {
  body_changed: 'The request changed, so this is a new preview.',
  plan_changed: 'The tree changed since the preview, and so did the result. Check it and confirm again.',
  expired: 'The preview expired. Check it and confirm again.',
  invalid: "The preview couldn't be used. Check it and confirm again.",
};
const LABEL_ERRORS = ['label_in_use', 'invalid_label'];

export default () => ({
  page: {},
  q: '', results: [], searching: false, searchError: '',
  aphia: null, pickedName: '',
  label: '', lower: true, parentMode: 'auto', parent: null, parentQ: '', parentResults: [],
  notes: '',
  busy: false, preview: null, request: null, reason: '', error: '',
  labelError: '', parentError: '', published: null,

  init() { this.page = pageData(); },
  reset() {
    Object.assign(this, {
      q: '', results: [], searchError: '', aphia: null, pickedName: '', label: '', lower: true,
      parentMode: 'auto', parent: null, parentQ: '', parentResults: [], notes: '',
      preview: null, request: null, reason: '', error: '', labelError: '', parentError: '',
      published: null,
    });
  },

  get url() { return `/trees/${this.page.tree}/quick_add`; },
  get canSearch() { return !!this.q.trim() && !this.searching; },
  wormsUrl(id) { return wormsUrl(id); },
  get labelPlaceholder() { return this.aphia ? 'From the WoRMS name' : 'Required without a WoRMS record'; },

  // ---- the form ------------------------------------------------------------------
  async searchWorms() {
    this.searching = true;
    this.searchError = '';
    const r = await api('GET', `/worms/search?name=${encodeURIComponent(this.q.trim())}&limit=20`);
    this.searching = false;
    if (!r.ok) { this.searchError = problem(r); return; }
    this.results = r.data.results;
    if (!this.results.length) this.searchError = 'No WoRMS records match.';
  },
  pick(rec) { this.aphia = rec.AphiaID; this.pickedName = rec.scientificname; },
  clearAphia() { this.aphia = null; this.pickedName = ''; },
  async searchParent() {
    const q = encodeURIComponent(this.parentQ.trim());
    const r = await api('GET', `/trees/${this.page.tree}/search?q=${q}&limit=10`);
    this.parentResults = r.ok ? r.data.results : [];
  },
  chooseParent(n) { this.parent = { id: n.id, label: n.label }; },
  get parentText() { return this.parent ? `Under ${this.parent.label || 'node ' + this.parent.id}` : ''; },

  /** The request the form describes. */
  body() {
    const body = {};
    if (this.aphia) body.aphia_id = this.aphia;
    if (this.label.trim()) body.label = this.label.trim();
    body.lowercase_label = this.lower;
    if (this.parentMode === 'top') body.parent = null;
    if (this.parentMode === 'node' && this.parent) body.parent = this.parent.id;
    return body;
  },
  get previewBlock() {
    if (this.busy) return 'Working…';
    if (!this.aphia && !this.label.trim()) return 'Pick a WoRMS record or type a label';
    if (this.parentMode === 'node' && !this.parent) return 'Pick the parent node';
    return '';
  },
  get confirmBlock() {
    if (this.busy) return 'Working…';
    if (JSON.stringify(this.body()) !== JSON.stringify(this.request)) return 'The form changed: preview again';
    return '';
  },

  // ---- preview and confirm ---------------------------------------------------------
  async send(body) {
    this.busy = true;
    this.error = this.labelError = this.parentError = '';
    const notes = this.notes.trim();
    const r = await api('POST', this.url, notes ? { ...body, notes } : body);
    this.busy = false;
    if (r.status === 201) { this.published = r.data; return; }
    if (r.status === 200) {
      this.preview = r.data;
      const planned = r.data.plan.parent;
      if (this.parent && planned?.id === this.parent.id) this.parent.label = planned.label;
      this.reason = REASONS[r.data.confirm_status] || '';
      return;
    }
    this.preview = null;
    this.reason = '';
    const errors = r.data?.errors || [];
    for (const e of errors) {
      if (LABEL_ERRORS.includes(e.error)) this.labelError = e.detail;
      else if (e.error === 'parent_not_in_tree') this.parentError = e.detail;
    }
    const other = errors.filter(e => !LABEL_ERRORS.includes(e.error) && e.error !== 'parent_not_in_tree');
    if (!errors.length) this.error = problem(r);
    else if (other.length) this.error = other.map(e => e.detail).join(' ');
  },
  async previewIt() {
    this.request = this.body();
    await this.send(this.request);
  },
  async confirm() {
    await this.send({ ...this.request, confirm: this.preview.confirm });
  },
  /** An issue's suggested edit: change the form and preview again. */
  async applyOption(option) {
    for (const [field, value] of Object.entries(option.set)) {
      if (field === 'aphia_id') { this.aphia = value; this.pickedName = ''; }
      if (field === 'parent' && value === null) { this.parentMode = 'top'; this.parent = null; }
      if (field === 'parent' && value !== null) { this.parentMode = 'node'; this.parent = { id: value, label: '' }; }
    }
    await this.previewIt();
  },
});
