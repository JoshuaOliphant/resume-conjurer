// DOM state-machine tests only. These do not verify browser layout, keyboard input,
// iframe sandbox behavior, or the ChatGPT host bridge; panel.test.mjs covers Chromium.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { setImmediate } from 'node:timers/promises';
import { JSDOM } from 'jsdom';

const source = await readFile(new URL('../panel.js', import.meta.url), 'utf8');
const shell = await readFile(new URL('../shell.html', import.meta.url), 'utf8');
const fixture = () => ({
  application_id: 'synthetic-demo', unit_id: 'resume.example.engineer.bullet_1',
  revision: 'a'.repeat(64), selected_variant: null,
  variants: [1, 2, 3, 4].map(id => ({
    id, text: `Variant ${id} <img src=x onerror="window.pwned=true">`,
    citation: '<script>window.pwned=true</script>',
    evidence: '<svg onload="window.pwned=true">', support: 'unchecked',
  })),
});

async function harness(t) {
  const dom = new JSDOM(shell.replace('<script type="module">/* BUNDLED_APP */</script>', ''), {
    // Only the trusted component source is evaluated; fixture markup is never executed.
    runScripts: 'outside-only',
  });
  t.after(() => dom.window.close());
  dom.window.eval(source.replace('export function', 'window.mountPanel = function'));
  const document = dom.window.document;
  const state = { saved: fixture(), calls: [], fail: false, loseSavedResponse: false,
    hold: false, pending: [], invalidResponse: false, errorResponse: false };
  const callTool = async args => {
    state.calls.push(structuredClone(args));
    if (state.hold) await new Promise((resolve, reject) => state.pending.push({ resolve, reject }));
    if (state.fail) throw new Error('lost connection');
    if (state.errorResponse) return { isError: true };
    if (state.invalidResponse) return { structuredContent: { application_id: 'other' } };
    if (args.name === 'set_variant_pick') {
      if (args.arguments.expected_revision !== state.saved.revision) {
        return { structuredContent: { ...structuredClone(state.saved), status: 'conflict',
          message: 'Selection changed. Review and choose again.' } };
      }
      state.saved = { ...state.saved, selected_variant: args.arguments.variant_id,
        revision: String(args.arguments.variant_id).repeat(64), status: 'saved' };
      if (state.loseSavedResponse) throw new Error('response lost after commit');
    }
    return { structuredContent: structuredClone(state.saved) };
  };
  const mount = () => dom.window.mountPanel(document.getElementById('app'), callTool);
  const panel = mount();
  await panel.refresh();
  return { dom, document, state, panel, mount,
    status: () => document.querySelector('[role=status]').textContent,
    button: id => document.querySelector(`[data-variant="${id}"]`),
    enabledChoices: () => document.querySelectorAll('section button:enabled').length,
    mutations: () => state.calls.filter(call => call.name === 'set_variant_pick'),
  };
}

test('mount renders four unselected choices and keeps hostile strings as text', async t => {
  const h = await harness(t);
  assert.equal(h.document.querySelectorAll('section').length, 4);
  assert.equal(h.document.querySelectorAll('section img, section svg, section script').length, 0);
  assert.match(h.document.querySelector('.variant-text').textContent, /<img/);
  assert.match(h.document.querySelector('.citation').textContent, /<script>/);
  assert.match(h.document.querySelector('details').textContent, /<svg/);
  assert.equal(h.document.querySelectorAll('[aria-pressed=true]').length, 0);
  assert.equal(h.dom.window.pwned, undefined);
  assert.equal(h.mutations().length, 0);
});

test('explicit click saves once and remount restores canonical selection', async t => {
  const h = await harness(t);
  h.button(2).click();
  await setImmediate();
  assert.equal(h.mutations().length, 1);
  assert.deepEqual(h.mutations()[0].arguments, {
    unit_id: fixture().unit_id, variant_id: 2, expected_revision: 'a'.repeat(64),
  });
  assert.equal(h.button(2).getAttribute('aria-pressed'), 'true');
  assert.match(h.status(), /Variant 2 is saved/);
  h.panel.disconnected();
  const reopened = h.mount();
  await reopened.refresh();
  assert.equal(h.button(2).getAttribute('aria-pressed'), 'true');
  reopened.receive({ structuredContent: fixture() });
  await setImmediate();
  assert.equal(h.button(2).getAttribute('aria-pressed'), 'true');
  assert.equal(h.mutations().length, 1);
});

test('stale choice restores current selection without overwriting it', async t => {
  const h = await harness(t);
  h.state.saved = { ...h.state.saved, selected_variant: 4, revision: 'b'.repeat(64) };
  h.button(1).click();
  await setImmediate();
  assert.equal(h.state.saved.selected_variant, 4);
  assert.equal(h.button(4).getAttribute('aria-pressed'), 'true');
  assert.match(h.status(), /Selection changed/);
  assert.equal(h.enabledChoices(), 4);
});

test('busy state suppresses rapid repeated save clicks', async t => {
  const h = await harness(t);
  h.state.hold = true;
  h.button(3).click();
  h.button(3).click();
  h.button(4).click();
  assert.equal(h.mutations().length, 1);
  assert.equal(h.enabledChoices(), 0);
  h.state.pending.shift().resolve();
  await setImmediate();
  assert.equal(h.state.saved.selected_variant, 3);
  assert.equal(h.button(3).getAttribute('aria-pressed'), 'true');
});

test('lost save response blocks writes and reload recovers the committed pick', async t => {
  const h = await harness(t);
  h.state.loseSavedResponse = true;
  h.button(2).click();
  await setImmediate();
  assert.equal(h.state.saved.selected_variant, 2);
  assert.match(h.status(), /could not be confirmed/);
  assert.equal(h.enabledChoices(), 0);
  h.button(1).click();
  assert.equal(h.mutations().length, 1);
  h.state.loseSavedResponse = false;
  await h.panel.refresh();
  assert.equal(h.button(2).getAttribute('aria-pressed'), 'true');
  assert.equal(h.enabledChoices(), 4);
});

for (const mode of ['fail', 'invalidResponse', 'errorResponse']) {
  test(`failed refresh (${mode}) disables stale choices until recovery`, async t => {
    const h = await harness(t);
    h.state[mode] = true;
    await h.panel.refresh();
    assert.equal(h.enabledChoices(), 0);
    assert.equal(h.document.querySelector('main > button').disabled, false);
    assert.equal(h.mutations().length, 0);
    h.state[mode] = false;
    await h.panel.refresh();
    assert.equal(h.enabledChoices(), 4);
  });
}

for (const action of ['save', 'reload']) {
  for (const outcome of ['resolve', 'reject']) {
    test(`disconnected ignores late ${action} ${outcome} and further host events`, async t => {
      const h = await harness(t);
      h.state.hold = true;
      if (action === 'save') h.button(1).click();
      else void h.panel.refresh();
      assert.equal(h.state.pending.length, 1);
      h.panel.disconnected();
      const pending = h.state.pending.shift();
      if (outcome === 'resolve') pending.resolve();
      else pending.reject(new Error('connection closed'));
      await setImmediate();
      assert.match(h.status(), /^Disconnected/);
      const calls = h.state.calls.length;
      h.panel.receive({ structuredContent: h.state.saved });
      h.panel.receive({ isError: true });
      await h.panel.refresh();
      h.button(2).click();
      assert.equal(h.state.calls.length, calls);
      assert.equal(h.document.querySelectorAll('button:disabled').length, 5);
      assert.match(h.status(), /^Disconnected/);
    });
  }
}
