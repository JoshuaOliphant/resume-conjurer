# ChatGPT curation prototype: synthetic first slice

Status: implemented for local protocol and UI testing. **Not connected to or validated in an actual ChatGPT host.** This narrowly continues [phase one](chatgpt-phase-one.md), not completion of that whole plan.

## Scope

One fixed synthetic résumé bullet, four alternatives, evidence disclosures and a "claim check not run" label. An explicit choice is saved through the existing picks.apply_picks engine. The only persisted selection is a Pick checkbox in variants.md. Reopening reads that file, not historical host results or browser state. Revision tokens reject stale choices; atomic replacement protects writes; uncertain saves require a read before another choice.

Native buttons/details, visible focus, status announcements and a narrow-screen layout support accessibility. Résumé/evidence strings enter textContent, never HTML.

No generation, import, real career data, claim verification, exports, downloads, provider rewrite, identity or multi-user hosting. Existing web routes and plugin engine are unchanged.

## Protocol decision (checked 2026-11-03)

Pinned Python MCP SDK mcp==1.27.2 and browser bridge @modelcontextprotocol/ext-apps==2.0.4. Streamable HTTP and standards-first MCP Apps, not a legacy window.openai bridge.

- open_curation_demo: no arguments, read-only, structured output schema, _meta.ui.resourceUri and ChatGPT thread entrypoint.
- set_variant_pick: app-visible only, bounded unit/variant/revision input. Host visibility is **not authorization**.
- Resource MIME text/html;profile=mcp-app. CSP allows no external resources, connection or frame domains.
- Self-contained bundled UI uses App.connect and callServerTool, handlers registered before connection.
- Official thread-panel support includes desktop, Work web, iOS and Android. Classic web is not assumed. Actual client support remains untested.

Sources: [Quickstart](https://developers.openai.com/plugins/build/app-quickstart), [ChatGPT UI](https://developers.openai.com/plugins/build/chatgpt-ui), [MCP server](https://developers.openai.com/plugins/build/mcp-server), [OpenAI MCP extensions](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md), [MCP Apps SDK](https://github.com/modelcontextprotocol/ext-apps), [App API](https://apps.extensions.modelcontextprotocol.io/api/classes/app.App.html).

## Local setup

From web/chatgpt-ui:

```sh
npm ci --ignore-scripts
npm run build
npm run test:dom
npx playwright install chromium
npm test
```

CHROMIUM_PATH optionally selects an existing Chromium executable. Built HTML is committed; CI rebuilds and checks an exact match.

From web:

```sh
uv sync --locked
uv run --locked python -m app.chatgpt_demo --scratch-dir /tmp/conjurer-chatgpt-demo
```

Endpoint: http://127.0.0.1:8401/mcp. Explicit setup initializes only the fixed synthetic fixture. Existing contents must match it apart from Pick checkboxes. Never use a real career workspace. Use one process and one dedicated directory; the lock is process-local. This unauthenticated loopback-only server must not be exposed as a real-data service. These commands do not deploy, tunnel, grant permissions or set up login.

## Verification and next gate

Python tests cover canonical persistence, reopen reads, concurrent stale writes, malformed fixture rejection, atomic-write failure, schemas/metadata, resources and JSON-RPC through the actual ASGI transport. DOM tests check state/error behavior. Chromium tests check keyboard selection, focus, hostile-text rendering, narrow layout and reopen with a controlled transport, **not ChatGPT**.

The implementation workspace blocks Chromium process sockets even after supported escalation. Local browser checks could not run; inspect the CI Chromium job. DOM and CI browser checks cannot establish real-host acceptance.

Before calling original slice A/B validated:
1. Connect an approved development endpoint to a supported ChatGPT client.
2. Open the panel and verify four alternatives/evidence.
3. Pick, close/reopen, and verify the same saved choice.
4. Check app-only mutation visibility, reconnect/errors and accessibility.
5. Record client/version and observations. Downloads remain a later slice.

Hosted endpoint and any connection/permission approvals are a separate decision, not implicit permission to deploy this unauthenticated fixture.
