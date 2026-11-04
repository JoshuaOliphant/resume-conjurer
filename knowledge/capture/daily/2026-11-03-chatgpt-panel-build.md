# ChatGPT panel build corruption — 2026-11-03

The first real-host trial connected the synthetic demo through OpenAI Secure MCP Tunnel, but the panel failed in classic ChatGPT and the Work browser. La Boeuf's desktop screenshot showed the panel disappearing too. Successful tool data and resource retrieval did not establish successful rendering; the model's accompanying success text was misleading.

The committed HTML had 18 doctypes and 18 copies of the app container. Extracting its inline module and running `node --check` failed with `SyntaxError: Invalid or unexpected token`. `build.mjs` passed the esbuild bundle as a replacement string to `String.replace`; dollar-backtick sequences in the bundled SDK inserted the HTML template prefix into JavaScript. A replacement callback preserves the bundled bytes literally.

The regression parses the shipped HTML, syntax-checks its actual module, and compares its digest with direct esbuild output. It failed before the fix and passes after it. The existing `test:dom` CI gate now includes that check. Source-only panel tests had missed the broken artifact.

Verification: 21 DOM/artifact tests pass; 12 Chromium tests pass using the installed Chrome executable; the web suite reports 722 passed, 4 live tests deselected, and 100% line and branch coverage. The live server's resource contains one doctype and a syntactically valid module.

Refreshing the installed plugin's tools and making a fresh tool call rendered all four alternatives in the ChatGPT Work browser. Evidence disclosure worked, and closing/reopening the app viewer retained the functioning panel. All choices remained unselected. Actual-host pick persistence and a desktop retest remain unverified. The earlier failing tool result continued showing its historical rendering error; retrying that old result was not sufficient to verify the corrected artifact.

La Boeuf restarted ChatGPT during verification. The managed tunnel stayed running, but the demo server launched from the agent terminal stopped, leaving the now-rendering panel with an internal error. Restarting the local server and pressing Reload saved selection restored all four unselected alternatives in the existing panel. Running the demo in an independent terminal avoids tying its lifetime to the ChatGPT process; no background service was installed.
