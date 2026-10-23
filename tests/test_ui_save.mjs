import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../ui/app.js', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('../ui/index.html', import.meta.url), 'utf8');
const clone = value => JSON.parse(JSON.stringify(value));

class Element {
  constructor(tag, document) {
    this.tagName = tag.toUpperCase(); this.document = document; this.children = [];
    this.listeners = new Map(); this.style = {}; this.dataset = {}; this.attributes = {};
    this.disabled = false; this.value = ''; this.textContent = ''; this.className = '';
    this.classList = {add: () => {}, remove: () => {}, toggle: () => {}};
  }
  set id(value) { this._id = value; this.document.ids.set(value, this); }
  get id() { return this._id; }
  addEventListener(type, handler) { this.listeners.set(type, handler); }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
  replaceChildren(...children) {
    const remove = node => {for (const child of node.children || []) remove(child); if (node.id && this.document.ids.get(node.id) === node) this.document.ids.delete(node.id);};
    this.children.forEach(remove); this.children = []; this.append(...children);
  }
  // Dispatch even to disabled elements to exercise queued/synthetic event guards.
  emit(type) { return this.listeners.get(type)?.({target: this, preventDefault() {}}); }
}

function state() {
  const binding = {type: 'keyboard', action: 'Enter', mode: 'tap', delay: 500, interval: 70, speed: 6, shortcut: '', target: ''};
  return {version: 1, current: 'daily', profiles: [
    {id: 'daily', name: '日常控制', bindings: Object.fromEntries(Array.from({length: 13}, (_, i) => [i, clone(binding)]))},
    {id: 'work', name: '工作', bindings: Object.fromEntries(Array.from({length: 13}, (_, i) => [i, clone(binding)]))}
  ]};
}

async function harness(status = {phase: 'stopped'}) {
  const document = {ids: new Map(), all: [], selectors: new Map()};
  document.createElement = tag => {const element = new Element(tag, document); document.all.push(element); return element;};
  document.createTextNode = text => ({textContent: text});
  document.getElementById = id => document.ids.get(id);
  document.body = document.createElement('body');
  for (const match of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = document.createElement(match[1]); element.id = match[2]; document.body.append(element);
  }
  for (const selector of ['.connection-lines', '.connected', '.battery-level', '.workspace']) {
    document.selectors.set(selector, document.createElement('div'));
  }
  document.querySelector = selector => document.selectors.get(selector);
  document.querySelectorAll = selector => {
    if (selector === '.remote-hotspot') return document.all.filter(e => e.className.includes('remote-hotspot') && e.parent?.children.includes(e));
    if (selector.includes('.workspace')) return document.all.filter(e => ['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName));
    throw Error(`Unsupported test selector: ${selector}`);
  };
  let saved = state(), pending;
  const calls = [];
  const native = {call: async (method, value) => {
    calls.push({method, value: clone(value ?? null)});
    if (method === 'load') return clone(saved);
    if (method === 'status') return status;
    if (method === 'save') return new Promise((resolve, reject) => {pending = {resolve, reject, value: clone(value)};});
    if (method === 'import') return {state: clone(saved)};
    if (method === 'export') return {ok: true};
    throw Error(method);
  }};
  const context = {
    window: {rc003Ready: Promise.resolve(), rc003Native: native}, document,
    Option: function (name, value, unused, selected) {const option = document.createElement('option'); option.textContent = name; option.value = value; option.selected = selected; return option;},
    URL, setTimeout: () => 1, clearTimeout() {}, setInterval() {}
  };
  await vm.runInNewContext(source, context);
  return {document, calls, element: id => document.getElementById(id),
    finishSave() {saved = clone(pending.value); pending.resolve({state: clone(saved)});},
    failSave() {pending.reject(Error('save rejected'));},
    saved: () => clone(saved)};
}

test('pending save locks every config control and rejects queued selection/edit/second-save events', async () => {
  const h = await harness();
  const action = h.element('specific-action'); action.value = 'Delete'; action.emit('change');
  const pending = h.element('key-form').emit('submit');
  assert.equal(h.calls.filter(c => c.method === 'save').length, 1);
  assert.equal(h.element('profile-select').disabled, true);
  assert.equal(h.element('reset-key').disabled, true);
  assert.equal(h.element('import-profile').disabled, true);
  assert.equal(h.element('specific-action').disabled, true);
  const key = h.element('key-cards').children.find(e => e.dataset.key === 5);
  assert.equal(key.disabled, true);
  key.emit('click');
  h.element('action-type').value = 'disabled'; h.element('action-type').emit('change');
  h.element('profile-select').value = 'work'; await h.element('profile-select').emit('change');
  await h.element('reset-key').emit('click');
  await h.element('copy-profile').emit('click');
  await h.element('import-profile').emit('click');
  await h.element('key-form').emit('submit');
  h.finishSave(); await pending;
  assert.equal(h.calls.filter(c => c.method === 'save').length, 1);
  assert.equal(h.calls.filter(c => c.method === 'import').length, 0);
  assert.equal(h.saved().current, 'daily');
  assert.equal(h.saved().profiles.length, 2);
  assert.equal(h.saved().profiles[0].bindings['6'].action, 'Delete');
  assert.equal(h.saved().profiles[0].bindings['5'].action, 'Enter');
  assert.equal(h.element('selected-name').textContent, '返回 / 删除');
  assert.equal(h.element('specific-action').children.find(option => option.selected)?.value, 'Delete');
  assert.equal(h.element('profile-select').disabled, false);
});

test('failed save unlocks controls and preserves the unsaved draft for retry', async () => {
  const h = await harness();
  h.element('specific-action').value = 'Delete'; h.element('specific-action').emit('change');
  const pending = h.element('key-form').emit('submit');
  h.failSave(); await pending;
  assert.equal(h.element('profile-select').disabled, false);
  assert.equal(h.element('dirty-indicator').textContent, '有未保存更改');
  const retry = h.element('key-form').emit('submit'); h.finishSave(); await retry;
  assert.equal(h.saved().profiles[0].bindings['6'].action, 'Delete');
});

test('stopped or paused service still displays cleanup failure', async () => {
  const h = await harness({phase: 'stopped', paused: true, cleanupIssue: '释放失败，需要重试'});
  assert.equal(h.element('runtime-status').textContent, '释放失败，需要重试');
});
