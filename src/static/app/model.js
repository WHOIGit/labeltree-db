// The tree in the browser: nodes from /trees/{tree}/export, and the local
// apply that composing uses for draft markings. Composing never checks
// structure; the server does that when the user validates.

export const isPh = id => typeof id === 'string' && id.startsWith('new:');
export const keyOf = id => (id == null ? '' : String(id));
export const idOf = key => (key === '' || key == null ? null : (isPh(key) ? key : Number(key)));

/** Map id -> node from export's nested detailed nodes. */
export function fromExport(nodes) {
  const state = new Map();
  const walk = (list, parent) => {
    for (const n of list) {
      state.set(n.id, {
        id: n.id, label: n.label, parent, aphia_id: n.aphia_id ?? null, version: n.version,
        description: n.description || '', aliases: n.aliases || [], worms_data: n.worms_data ?? null,
        warnings: n.worms_warnings || [], created: n.created_in_rev ?? null, dep: false,
      });
      walk(n.children || [], n.id);
    }
  };
  walk(nodes, null);
  return state;
}

/** Children per parent (null for top level), sorted by label. */
export function childIndex(state, includeDep = true) {
  const kids = new Map();
  for (const n of state.values()) {
    if (n.dep && !includeDep) continue;
    if (!kids.has(n.parent)) kids.set(n.parent, []);
    kids.get(n.parent).push(n.id);
  }
  for (const list of kids.values())
    list.sort((a, b) => state.get(a).label.localeCompare(state.get(b).label, undefined, { sensitivity: 'base' }));
  return kids;
}

/** Nodes a change names: its node, parents and successors. */
export function touched(c) {
  const out = [c.node, c.parent, c.from_parent, c.to_parent, ...(c.successors || [])];
  return out.filter(x => x != null);
}

/**
 * Apply changes leniently to a copy of `base`: a change that can't apply is
 * skipped. Deprecated nodes stay, marked `dep`. Returns the state, the added
 * and deprecated nodes, and the existing nodes whose version will increase
 * (content, parent or child set differs from the base, as the server counts).
 */
export function applyLocal(base, changes) {
  const s = new Map();
  for (const [k, n] of base) s.set(k, { ...n });
  const added = new Set(), deprecated = new Set();
  const live = id => s.has(id) && !s.get(id).dep;
  for (const c of changes) {
    if (c.op === 'add' && !s.has(c.node) && (c.parent == null || live(c.parent))) {
      s.set(c.node, { id: c.node, label: c.label, parent: c.parent ?? null, aphia_id: c.aphia_id ?? null,
                      version: null, description: c.description || '', aliases: (c.aliases || []).map(a => ({ alias: a })),
                      worms_data: null, warnings: [], created: null, dep: false });
      added.add(c.node);
    } else if (c.op === 'edit' && live(c.node)) {
      if ('label' in c) s.get(c.node).label = c.label;
      if ('aphia_id' in c && c.aphia_id !== s.get(c.node).aphia_id) {
        Object.assign(s.get(c.node), { aphia_id: c.aphia_id, worms_data: null, warnings: [] });  // checked on Validate
      }
    } else if (c.op === 'move' && live(c.node) && (c.to_parent == null || live(c.to_parent))) {
      let cycle = false;
      for (let p = c.to_parent; p != null; p = s.get(p)?.parent ?? null) if (p === c.node) { cycle = true; break; }
      if (!cycle) s.get(c.node).parent = c.to_parent ?? null;
    } else if (c.op === 'deprecate' && live(c.node)) {
      s.get(c.node).dep = true;
      deprecated.add(c.node);
    }
  }
  const kidsOf = (state, id) => new Set([...state.values()].filter(n => !n.dep && n.parent === id).map(n => n.id));
  const bump = new Set();
  for (const [id, old] of base) {
    const now = s.get(id);
    if (!now || now.dep) continue;
    const before = kidsOf(base, id), after = kidsOf(s, id);
    const kidsChanged = before.size !== after.size || [...before].some(k => !after.has(k));
    if (old.label !== now.label || old.aphia_id !== now.aphia_id || old.parent !== now.parent || kidsChanged) bump.add(id);
  }
  return { state: s, added, deprecated, bump };
}

/** One line describing a change, with labels from `state` (or `fallback`). */
export function describe(c, state, fallback = new Map()) {
  const name = id => {
    if (id == null) return 'top level';
    const l = state.get(id)?.label ?? fallback.get(id)?.label ?? String(id);
    return isPh(id) ? `${l} (${id})` : l;
  };
  switch (c.op) {
    case 'add':
      return `${name(c.node)} under ${name(c.parent)}` + (c.aphia_id ? `, AphiaID ${c.aphia_id}` : '');
    case 'edit': {
      const bits = [];
      if ('label' in c) bits.push(`label → ${c.label}`);
      if ('aphia_id' in c) bits.push(`AphiaID → ${c.aphia_id ?? 'none'}`);
      // named as it was before the edit
      const before = fallback.get(c.node)?.label;
      return `${before && !isPh(c.node) ? before : name(c.node)}: ${bits.join(', ')}`;
    }
    case 'move':
      return `${name(c.node)}: ${name(c.from_parent)} → ${name(c.to_parent)}`;
    case 'deprecate':
      return name(c.node) + (c.successors?.length ? ` → successors ${c.successors.map(name).join(', ')}` : '');
    default:
      return JSON.stringify(c);
  }
}

/**
 * The AphiaID pill of a node: null without an AphiaID; otherwise its colour,
 * badge and tooltip. Red with `?` for unknown_aphia (whatever else), orange
 * with `!` for any other warning, grey if never fetched, else green.
 */
export function pill(node) {
  if (node.aphia_id == null) return null;
  const warnings = node.warnings || [];
  const codes = warnings.map(w => w.warning);
  let kind = 'green', badge = '';
  if (codes.includes('unknown_aphia')) { kind = 'red'; badge = '?'; }
  else if (codes.length) { kind = 'orange'; badge = '!'; }
  else if (!node.worms_data) kind = 'grey';
  const title = [`AphiaID ${node.aphia_id}` + (kind === 'grey' ? ' (not fetched from WoRMS yet)' : ''),
                 ...warnings.map(w => `${w.warning}: ${w.detail}`)].join('\n');
  return { kind, badge, title, href: wormsUrl(node.aphia_id) };
}

export const wormsUrl = id => `https://www.marinespecies.org/aphia.php?p=taxdetails&id=${id}`;

/** Path of a node's ancestors' labels. */
export function nodePath(state, id) {
  const parts = [];
  for (let n = state.get(state.get(id)?.parent); n; n = state.get(n.parent)) parts.unshift(n.label);
  return parts.join(' / ');
}
