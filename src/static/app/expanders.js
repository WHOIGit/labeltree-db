// Macros that expand into ordinary grouped changes (spec: webapp, changeset-api
// "Macros have no endpoints"). Pure functions of a tree state, so they run in
// the browser and under `node --test` alike. The server re-validates whatever
// they produce.

export const LABEL_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

const isPh = id => typeof id === 'string' && id.startsWith('new:');

/** A function returning the next unused placeholder after those in `changes`. */
export function placeholders(changes) {
  let k = 0;
  for (const c of changes) if (isPh(c.node)) k = Math.max(k, Number(c.node.slice(4)));
  return () => `new:${++k}`;
}

/** The next `prefix#n` group name not used in `changes`. */
export function nextGroup(prefix, changes) {
  let n = 0;
  for (const c of changes) {
    if (c.group?.startsWith(prefix + '#')) n = Math.max(n, Number(c.group.split('#')[1]) || 0);
  }
  return `${prefix}#${n + 1}`;
}

/** The live nodes of a tree state by label, for labelProblem. A draft with
 * errors can have two live nodes with one label, so each label maps to a list. */
export function labelIndex(state) {
  const index = new Map();
  for (const n of state.values()) {
    if (n.dep) continue;
    const list = index.get(n.label);
    if (list) list.push(n);
    else index.set(n.label, [n]);
  }
  return index;
}

/**
 * Why a label can't be used, or '' (machine-safe and unused by another live
 * node). `labels` is the tree's labelIndex. `reserved` are nodes the same
 * macro deprecates: their labels stay taken until the draft is published,
 * since changes apply in order and a node is deprecated only after its
 * children move to the new node.
 */
export function labelProblem(label, labels, self = null, others = [], reserved = new Set()) {
  if (!label) return 'Label is required';
  if (!LABEL_RE.test(label)) return 'Not machine-safe: letters, digits and _ . - only, starting with a letter or digit';
  for (const n of labels.get(label) || []) {
    if (n.id === self) continue;
    if (reserved.has(n.id)) return `${label} stays taken until this draft is published: choose another label`;
    return `Already used by ${n.label} (${n.id})`;
  }
  if (others.includes(label)) return 'Used twice here';
  return '';
}

/** A WoRMS scientific name as a label: spaces become `_`, other unsafe
 * characters are dropped, and so is leading punctuation. */
export function wormsLabel(name) {
  return (name || '').trim().replace(/\s+/g, '_').replace(/[^A-Za-z0-9_.-]/g, '').replace(/^[^A-Za-z0-9]+/, '');
}

/** The deepest live node anchored to an AphiaID of `lineage` (top level first), or null. */
export function suggestParent(lineage, state) {
  for (const entry of [...lineage].reverse()) {
    for (const n of state.values()) if (!n.dep && n.aphia_id === entry.AphiaID) return n.id;
  }
  return null;
}

function liveKids(state, id) {
  return [...state.values()].filter(n => !n.dep && n.parent === id).map(n => n.id)
    .sort((a, b) => state.get(a).label.localeCompare(state.get(b).label));
}

/**
 * Merge `nodes` (A first). With replacement: add `newNode` under `parent`,
 * move every child of the merged nodes to it, deprecate them all with it as
 * successor. Without: children move to `survivor`, the others are deprecated.
 */
export function mergeChanges({ state, nodes, replace = true, survivor, newNode, parent = null, group, ph }) {
  const out = [];
  let target;
  if (replace) {
    target = ph();
    out.push({ op: 'add', node: target, label: newNode.label, parent, aphia_id: newNode.aphia_id ?? null,
               description: newNode.description || '', aliases: [], group });
  } else {
    target = survivor;
  }
  for (const x of nodes) {
    if (x === target) continue;
    for (const k of liveKids(state, x)) out.push({ op: 'move', node: k, from_parent: x, to_parent: target, group });
  }
  for (const x of nodes) if (x !== target) out.push({ op: 'deprecate', node: x, successors: [target], group });
  return out;
}

/**
 * Split `a`: add `parts` as its siblings, move each child assigned to a part
 * (`assign` maps child id -> part index), and, with replacement, deprecate `a`
 * with the parts as successors. Unassigned children stay with `a`.
 */
export function splitChanges({ state, a, replace = true, parts, assign, group, ph }) {
  const out = [];
  const parent = state.get(a).parent;
  const ids = parts.map(p => {
    const id = ph();
    out.push({ op: 'add', node: id, label: p.label, parent, aphia_id: p.aphia_id ?? null,
               description: p.description || '', aliases: [], group });
    return id;
  });
  for (const k of liveKids(state, a)) {
    const i = assign[String(k)];
    if (i !== undefined && i !== '' && i !== null) {
      out.push({ op: 'move', node: k, from_parent: a, to_parent: ids[Number(i)], group });
    }
  }
  if (replace) out.push({ op: 'deprecate', node: a, successors: ids, group });
  return out;
}

/** Children of a split with replacement that no part takes. */
export function unassigned(state, a, assign) {
  return liveKids(state, a).filter(k => assign[String(k)] === undefined || assign[String(k)] === '');
}

export class ImportFormatError extends Error {
  constructor(position, detail) {
    super(`${position}: ${detail}`);
    this.position = position;
    this.detail = detail;
  }
}

function checkNode(node, position) {
  if (node === null || typeof node !== 'object' || Array.isArray(node)) throw new ImportFormatError(position, 'a node must be an object');
  if (typeof node.label !== 'string') throw new ImportFormatError(position, 'node has no `label`');
  if (typeof (node.description || '') !== 'string') throw new ImportFormatError(position, '`description` must be a string');
  const aphia = node.aphia_id;
  if (aphia !== undefined && aphia !== null && !Number.isInteger(aphia)) throw new ImportFormatError(position, '`aphia_id` must be an integer');
  const aliases = node.aliases || [];
  if (!Array.isArray(aliases) || !aliases.every(a => typeof a === 'string')) throw new ImportFormatError(position, '`aliases` must be a list of strings');
  if (!Array.isArray(node.children || [])) throw new ImportFormatError(position, '`children` must be a list');
}

/**
 * Expand an import file into `add` changes, as core.importer.expand_import
 * does: one group, parents before children in file order. `parent` is an
 * existing node to import under; placeholders continue after `start`.
 */
export function expandImport(data, { parent = null, group = 'import#1', start = 0 } = {}) {
  if (data === null || typeof data !== 'object' || !Array.isArray(data.nodes)) {
    throw new ImportFormatError('file', 'expected an object with a `nodes` list');
  }
  const changes = [];
  const walk = (nodes, parentRef, path) => {
    nodes.forEach((node, i) => {
      const position = `${path}[${i}]`;
      checkNode(node, position);
      const ref = `new:${start + changes.length + 1}`;
      const change = { op: 'add', group, node: ref, label: node.label, parent: parentRef };
      if (node.description) change.description = node.description;
      if (node.aphia_id !== undefined && node.aphia_id !== null) change.aphia_id = node.aphia_id;
      if (node.aliases?.length) change.aliases = [...node.aliases];
      changes.push(change);
      walk(node.children || [], ref, `${position}.children`);
    });
  };
  walk(data.nodes, parent, 'nodes');
  return changes;
}

/** A tree state as an import file: the clone of a revision, as core.clone does. */
export function cloneData(state) {
  const nested = parentId => liveKids(state, parentId).map(id => {
    const n = state.get(id);
    return {
      label: n.label, aphia_id: n.aphia_id ?? null, description: n.description || '',
      aliases: (n.aliases || []).map(a => (typeof a === 'string' ? a : a.alias)),
      children: nested(id),
    };
  });
  return { nodes: nested(null) };
}
