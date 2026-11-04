// ABOUTME: Validates the bundled HTML served to ChatGPT as an MCP app resource.
// ABOUTME: Checks that template insertion preserves executable module JavaScript.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { buildOptions } from '../build-options.mjs';

test('built MCP app HTML contains a syntactically valid module', async t => {
  const html = await readFile(new URL('../../app/static/chatgpt/curate.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html);
  t.after(() => dom.window.close());
  const scripts = dom.window.document.querySelectorAll('script[type=module]');
  assert.equal(scripts.length, 1);
  const result = spawnSync(process.execPath, ['--input-type=module', '--check'], {
    input: scripts[0].textContent, encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr.match(/SyntaxError: .*/)?.[0] ?? result.stderr);
  const bundled = await build(buildOptions);
  const expected = bundled.outputFiles[0].text.replaceAll('</script', '<\\/script');
  const digest = value => createHash('sha256').update(value).digest('hex');
  assert.equal(digest(scripts[0].textContent), digest(expected));
});
