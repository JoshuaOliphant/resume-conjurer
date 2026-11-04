// ABOUTME: Defines the esbuild configuration for the bundled MCP app resource.
// ABOUTME: Shares the production build settings with the artifact regression test.
import { fileURLToPath } from 'node:url';

export const buildOptions = {
  absWorkingDir: fileURLToPath(new URL('.', import.meta.url)),
  entryPoints: ['main.js'], bundle: true, write: false,
  format: 'esm', target: 'es2022', minify: true, legalComments: 'inline',
};
