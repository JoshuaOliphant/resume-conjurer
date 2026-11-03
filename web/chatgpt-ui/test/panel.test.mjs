import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '@playwright/test';
import { readFile } from 'node:fs/promises';

let browser;
const source = await readFile(new URL('../panel.js', import.meta.url), 'utf8');
const shell = await readFile(new URL('../shell.html', import.meta.url), 'utf8');
const fixture = { application_id: 'synthetic-demo', unit_id: 'resume.example.engineer.bullet_1',
  revision: 'a'.repeat(64), selected_variant: null, variants: [1, 2, 3, 4].map(id => ({
    id, text: `Variant ${id} <img src=x onerror="window.pwned=true">`, citation: '<script>bad()</script>',
    evidence: '<svg onload="window.pwned=true">', support: 'unchecked',
  })) };
before(async () => { browser = await chromium.launch({
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
  headless: true,
}); });
after(async () => { await browser?.close(); });
async function pageWithPanel() {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.setContent(shell.replace('<script type="module">/* BUNDLED_APP */</script>', ''));
  await page.addScriptTag({ type: 'module', content: source.replace('export function', 'window.mountPanel = function') });
  await page.evaluate(data => {
    window.saved = data; window.calls = []; window.fail = false; window.delay = 0;
    window.hold = false; window.pending = [];
    window.transport = async args => {
      window.calls.push(args);
      if (window.hold) await new Promise((resolve, reject) => window.pending.push({ resolve, reject }));
      if (window.delay) await new Promise(resolve => setTimeout(resolve, window.delay));
      if (window.fail) throw new Error('lost connection');
      if (args.name === 'set_variant_pick') {
        if (args.arguments.expected_revision !== window.saved.revision)
          return { structuredContent: { ...window.saved, status: 'conflict', message: 'Selection changed. Review and choose again.' } };
        window.saved = { ...window.saved, selected_variant: args.arguments.variant_id,
          revision: String(args.arguments.variant_id).repeat(64), status: 'saved' };
      }
      return { structuredContent: structuredClone(window.saved) };
    };
    window.panel = window.mountPanel(document.getElementById('app'), window.transport);
    return window.panel.refresh();
  }, fixture);
  return page;
}

test('four choices, inert hostile text, evidence and narrow layout', async () => {
  const page = await pageWithPanel();
  assert.equal(await page.locator('section').count(), 4);
  assert.equal(await page.locator('section img, section svg, section script').count(), 0);
  assert.equal(await page.evaluate(() => window.pwned), undefined);
  await page.locator('summary').first().click();
  assert.match(await page.locator('details').first().textContent(), /<svg/);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= 390), true);
  assert.equal(await page.locator('[aria-pressed=true]').count(), 0);
  await page.close();
});

test('keyboard pick persists across mount and historical host results', async () => {
  const page = await pageWithPanel();
  await page.locator('[data-variant="2"]').focus();
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelector('[data-variant="2"]').getAttribute('aria-pressed') === 'true');
  assert.equal(await page.evaluate(() => window.calls.filter(x => x.name === 'set_variant_pick').length), 1);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.variant), '2');
  await page.evaluate(() => {
    window.panel = window.mountPanel(document.getElementById('app'), window.transport);
    return window.panel.refresh();
  });
  assert.match(await page.locator('[role=status]').textContent(), /Variant 2 is saved/);
  await page.evaluate(() => window.panel.receive({ structuredContent: { selected_variant: null } }));
  await page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('Variant 2 is saved'));
  await page.close();
});

test('stale choice rejected, rapid clicks do not double-save, reload recovers uncertain write', async () => {
  const page = await pageWithPanel();
  await page.evaluate(() => { window.saved.revision = 'b'.repeat(64); window.saved.selected_variant = 4; });
  await page.locator('[data-variant="1"]').click();
  await page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('Selection changed'));
  assert.equal(await page.locator('[data-variant="4"]').getAttribute('aria-pressed'), 'true');
  await page.evaluate(() => { window.delay = 100; document.querySelector('[data-variant="3"]').click(); document.querySelector('[data-variant="3"]').click(); });
  await page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('Variant 3 is saved'));
  assert.equal(await page.evaluate(() => window.calls.filter(x => x.name === 'set_variant_pick').length), 2);
  await page.evaluate(() => { window.fail = true; });
  await page.locator('[data-variant="2"]').click();
  await page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('could not be confirmed'));
  assert.equal(await page.locator('section button:disabled').count(), 4);
  await page.evaluate(() => { window.fail = false; window.saved.selected_variant = 2; window.saved.revision = '2'.repeat(64); });
  await page.getByRole('button', { name: 'Reload saved selection', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('Variant 2 is saved'));
  await page.close();
});

test('disconnect ignores in-flight response and disables writes', async () => {
  const page = await pageWithPanel();
  await page.evaluate(() => { window.delay = 150; document.querySelector('[data-variant="1"]').click(); window.panel.disconnected(); });
  await page.waitForTimeout(200);
  assert.match(await page.locator('[role=status]').textContent(), /Disconnected/);
  assert.equal(await page.locator('button:disabled').count(), 5);
  await page.close();
});

for (const operation of ['save', 'reload']) {
  test(`disconnect ignores a rejected ${operation} and late host notifications`, async () => {
    const page = await pageWithPanel();
    const callsBeforeLateMessages = await page.evaluate(async action => {
      window.hold = true;
      if (action === 'save') document.querySelector('[data-variant="1"]').click();
      else void window.panel.refresh();
      window.panel.disconnected();
      window.panel.cancelled();
      window.pending.shift().reject(new Error('connection closed'));
      await new Promise(resolve => setTimeout(resolve, 0));
      return window.calls.length;
    }, operation);
    assert.match(await page.locator('[role=status]').textContent(), /^Disconnected/);
    await page.evaluate(async () => {
      window.panel.receive({ structuredContent: window.saved });
      window.panel.receive({ isError: true });
      await window.panel.refresh();
      document.querySelector('[data-variant="2"]').click();
    });
    assert.equal(await page.evaluate(() => window.calls.length), callsBeforeLateMessages);
    assert.match(await page.locator('[role=status]').textContent(), /^Disconnected/);
    assert.equal(await page.locator('button:disabled').count(), 5);
    await page.close();
  });
}

test('a failed refresh disables stale choices until a successful reload', async () => {
  const page = await pageWithPanel();
  await page.evaluate(() => { window.fail = true; });
  await page.getByRole('button', { name: 'Reload saved selection', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('lost connection'));
  assert.equal(await page.locator('section button:disabled').count(), 4);
  assert.equal(await page.getByRole('button', { name: 'Reload saved selection', exact: true }).isEnabled(), true);
  await page.evaluate(() => { window.fail = false; });
  await page.getByRole('button', { name: 'Reload saved selection', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('Nothing selected'));
  assert.equal(await page.locator('section button:enabled').count(), 4);
  await page.close();
});

for (const operation of ['save', 'reload']) {
  for (const outcome of ['resolve', 'reject']) {
    test(`cancelled ${operation} ignores late ${outcome} and recovers with Reload`, async () => {
      const page = await pageWithPanel();
      const callsBeforeReload = await page.evaluate(async ({ action, result }) => {
        window.hold = true;
        if (action === 'save') document.querySelector('[data-variant="1"]').click();
        else void window.panel.refresh();
        const pending = window.pending.shift();
        window.panel.cancelled();
        window.panel.receive({ structuredContent: window.saved });
        window.panel.receive({ isError: true });
        await window.panel.refresh({ automatic: true });
        document.querySelector('[data-variant="2"]').click();
        if (result === 'resolve') pending.resolve();
        else pending.reject(new Error('cancelled request finished late'));
        await new Promise(resolve => setTimeout(resolve, 0));
        return window.calls.length;
      }, { action: operation, result: outcome });
      assert.equal(callsBeforeReload, 2);
      assert.match(await page.locator('[role=status]').textContent(), /^Request cancelled/);
      assert.equal(await page.locator('section button:disabled').count(), 4);
      const reload = page.getByRole('button', { name: 'Reload saved selection', exact: true });
      assert.equal(await reload.isEnabled(), true);
      await page.evaluate(() => { window.hold = false; });
      await reload.click();
      await page.waitForFunction(() => document.querySelectorAll('section button:enabled').length === 4);
      const saved = operation === 'save' && outcome === 'resolve';
      assert.equal(await page.locator('[data-variant="1"]').getAttribute('aria-pressed'), String(saved));
      assert.equal(await page.evaluate(() => window.calls.length), callsBeforeReload + 1);
      assert.equal(await page.evaluate(() => window.calls.filter(call => call.name === 'set_variant_pick').length),
        operation === 'save' ? 1 : 0);
      await page.close();
    });
  }
}

test('cancelled write completing after Reload cannot overwrite the next stale pick', async () => {
  const page = await pageWithPanel();
  await page.evaluate(async () => {
    window.hold = true;
    document.querySelector('[data-variant="1"]').click();
    const pending = window.pending.shift();
    window.panel.cancelled();
    window.hold = false;
    await window.panel.refresh();
    pending.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  assert.match(await page.locator('[role=status]').textContent(), /Nothing selected/);
  assert.equal(await page.evaluate(() => window.saved.selected_variant), 1);
  await page.locator('[data-variant="2"]').click();
  await page.waitForFunction(() => document.querySelector('[role=status]').textContent.includes('Selection changed'));
  assert.equal(await page.evaluate(() => window.saved.selected_variant), 1);
  assert.equal(await page.locator('[data-variant="1"]').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.evaluate(() => window.calls.filter(call => call.name === 'set_variant_pick').length), 2);
  await page.close();
});
