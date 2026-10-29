// Expander tests: `node --test src/static/app/tests` (also run by
// core/tests/test_import_fixtures.py).
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import * as X from '../expanders.js';
import { applyLocal } from '../model.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = join(here, '../../../core/tests/import_fixtures');

// A > x(4), y(5) ; B(2) ; C(3) > z(6)
function state() {
  const nodes = [[1, 'A', null], [2, 'B', null], [3, 'C', null], [4, 'x', 1], [5, 'y', 1], [6, 'z', 3]];
  return new Map(nodes.map(([id, label, parent]) => [id, { id, label, parent, aphia_id: null, dep: false, aliases: [], description: '' }]));
}

for (const file of readdirSync(fixtures).filter(f => f.endsWith('.json'))) {
  test(`import fixture ${file}`, () => {
    const c = JSON.parse(readFileSync(join(fixtures, file), 'utf8'));
    if (c.error) {
      assert.throws(() => X.expandImport(c.input, c.options), e => e.position === c.error);
    } else {
      assert.deepEqual(X.expandImport(c.input, c.options), c.expected);
    }
  });
}

test('import placeholders continue after existing ones', () => {
  const out = X.expandImport({ nodes: [{ label: 'a' }] }, { start: 3 });
  assert.equal(out[0].node, 'new:4');
});

test('merge with replacement', () => {
  const s = state();
  const out = X.mergeChanges({ state: s, nodes: [1, 3], replace: true, newNode: { label: 'AC' }, parent: null,
                               group: 'merge#1', ph: X.placeholders([]) });
  assert.deepEqual(out.map(c => [c.op, c.node, c.to_parent ?? c.successors ?? c.parent]), [
    ['add', 'new:1', null], ['move', 4, 'new:1'], ['move', 5, 'new:1'], ['move', 6, 'new:1'],
    ['deprecate', 1, ['new:1']], ['deprecate', 3, ['new:1']],
  ]);
  assert.ok(out.every(c => c.group === 'merge#1'));
});

test('merge without replacement', () => {
  const out = X.mergeChanges({ state: state(), nodes: [1, 3], replace: false, survivor: 3, group: 'merge#1', ph: X.placeholders([]) });
  assert.deepEqual(out.map(c => [c.op, c.node]), [['move', 4], ['move', 5], ['deprecate', 1]]);
  assert.deepEqual(out[2].successors, [3]);
});

test('split with replacement assigns every child', () => {
  const s = state();
  assert.deepEqual(X.unassigned(s, 1, { 4: '0' }), [5]);
  const out = X.splitChanges({ state: s, a: 1, replace: true, parts: [{ label: 'A1' }, { label: 'A2' }],
                               assign: { 4: '0', 5: '1' }, group: 'split#1', ph: X.placeholders([]) });
  assert.deepEqual(out.map(c => [c.op, c.node]), [['add', 'new:1'], ['add', 'new:2'], ['move', 4], ['move', 5], ['deprecate', 1]]);
  assert.deepEqual(out[4].successors, ['new:1', 'new:2']);
  const after = applyLocal(s, out);
  assert.ok(after.deprecated.has(1) && after.state.get(4).parent === 'new:1');
});

test('split without replacement leaves unassigned children', () => {
  const out = X.splitChanges({ state: state(), a: 1, replace: false, parts: [{ label: 'A2' }], assign: { 4: '0' },
                               group: 'split#1', ph: X.placeholders([{ node: 'new:7' }]) });
  assert.deepEqual(out.map(c => [c.op, c.node]), [['add', 'new:8'], ['move', 4]]);
});

test('labels from WoRMS names', () => {
  assert.equal(X.wormsLabel('Chaetoceros debilis'), 'Chaetoceros_debilis');
  assert.equal(X.wormsLabel('Chaetoceros (Hyalochaete) debilis'), 'Chaetoceros_Hyalochaete_debilis');
  assert.equal(X.wormsLabel('Chaetoceros cf. debilis'), 'Chaetoceros_cf._debilis');
  assert.equal(X.wormsLabel('×Anthus hybrid'), 'Anthus_hybrid');
});

test('suggested parent is the deepest anchored lineage node', () => {
  const s = state();
  s.get(1).aphia_id = 10;
  s.get(4).aphia_id = 11;
  assert.equal(X.suggestParent([{ AphiaID: 10 }, { AphiaID: 11 }, { AphiaID: 12 }], s), 4);
  assert.equal(X.suggestParent([{ AphiaID: 99 }], s), null);
});

test('label checks', () => {
  const s = state();
  assert.match(X.labelProblem('x', s), /Already used/);
  assert.equal(X.labelProblem('x', s, 4), '');
  assert.match(X.labelProblem('a b', s), /machine-safe/);
});

test('next group and placeholders', () => {
  const changes = [{ node: 'new:2', group: 'merge#1' }, { node: 4, group: 'merge#3' }];
  assert.equal(X.nextGroup('merge', changes), 'merge#4');
  assert.equal(X.nextGroup('split', changes), 'split#1');
  assert.equal(X.placeholders(changes)(), 'new:3');
});

test('clone data skips deprecated nodes and keeps aliases', () => {
  const s = state();
  s.get(4).aliases = [{ id: 1, alias: 'ex' }];
  s.get(6).dep = true;
  const data = X.cloneData(s);
  assert.deepEqual(data.nodes.map(n => n.label), ['A', 'B', 'C']);
  assert.deepEqual(data.nodes[0].children[0].aliases, ['ex']);
  assert.deepEqual(data.nodes[2].children, []);
});

test('labels a macro deprecates stay taken until publish', () => {
  const s = state();
  assert.match(X.labelProblem('A', s, null, [], new Set([1])), /stays taken until this draft is published/);
  assert.match(X.labelProblem('A', s), /Already used/);
});
