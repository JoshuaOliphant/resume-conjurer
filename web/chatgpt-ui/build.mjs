import { build } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
const result = await build({ entryPoints: ['main.js'], bundle: true, write: false,
  format: 'esm', target: 'es2022', minify: true, legalComments: 'inline' });
const template = await readFile('shell.html', 'utf8');
await mkdir('../app/static/chatgpt', { recursive: true });
await writeFile('../app/static/chatgpt/curate.html', template.replace('/* BUNDLED_APP */',
  result.outputFiles[0].text.replaceAll('</script', '<\\/script')));
