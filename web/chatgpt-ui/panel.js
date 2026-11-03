// Hand-authored DOM only: resume and evidence strings never enter an HTML sink.
export function mountPanel(root, callTool) {
  let snapshot = null;
  let busy = false;
  let request = 0;
  let disconnected = false;
  const title = document.createElement('h1');
  title.textContent = 'Choose the wording';
  const intro = document.createElement('p');
  intro.textContent = 'Synthetic example · One résumé bullet · No claim check has run.';
  const list = document.createElement('div');
  list.setAttribute('aria-label', 'Four wording alternatives');
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.textContent = 'Connecting to the curation demo…';
  const reload = document.createElement('button');
  reload.type = 'button';
  reload.textContent = 'Reload saved selection';
  reload.addEventListener('click', () => refresh());
  root.replaceChildren(title, intro, list, status, reload);

  function show(data, message, focused = document.activeElement?.dataset?.variant) {
    if (!data || data.application_id !== 'synthetic-demo' || !Array.isArray(data.variants)
        || data.variants.length !== 4 || typeof data.revision !== 'string') {
      throw new Error('The server did not return this demo. Reload to try again.');
    }
    const active = document.activeElement;
    // Disabling the old button can blur it. Restore that lost focus, but do not
    // interrupt a user who moved to a control outside the list while awaiting I/O.
    const restoreFocus = focused && (!active || active === document.body || list.contains(active));
    snapshot = data;
    list.replaceChildren();
    for (const variant of data.variants) {
      const section = document.createElement('section');
      const text = document.createElement('p');
      text.className = 'variant-text';
      text.textContent = variant.text;
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.variant = String(variant.id);
      const selected = data.selected_variant === variant.id;
      button.setAttribute('aria-pressed', String(selected));
      button.textContent = selected ? `Variant ${variant.id} · Saved selection` : `Choose variant ${variant.id}`;
      button.disabled = busy;
      button.addEventListener('click', () => choose(variant.id));
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = 'Evidence · Claim check not run';
      const citation = document.createElement('p');
      citation.className = 'citation';
      citation.textContent = variant.citation;
      const quote = document.createElement('p');
      quote.textContent = variant.evidence;
      details.append(summary, citation, quote);
      section.append(button, text, details);
      list.append(section);
    }
    if (restoreFocus) [...list.querySelectorAll('button')]
      .find(button => button.dataset.variant === focused)?.focus();
    status.textContent = message || (data.selected_variant == null
      ? 'Nothing selected. Choose a version to save it.'
      : `Variant ${data.selected_variant} is saved. You can choose another version.`);
  }

  function resultData(result) {
    if (result.isError) throw new Error('The server could not complete the request. Reload before trying again.');
    return result.structuredContent;
  }

  async function refresh() {
    if (busy || disconnected) return;
    const focused = document.activeElement?.dataset?.variant;
    const current = ++request;
    busy = true;
    reload.disabled = true;
    list.querySelectorAll('button').forEach(button => { button.disabled = true; });
    status.textContent = 'Loading saved selection…';
    try {
      const result = await callTool({ name: 'open_curation_demo', arguments: {} });
      if (current !== request) return;
      busy = false;
      show(resultData(result), undefined, focused);
    } catch (error) {
      if (current !== request || disconnected) return;
      snapshot = null;
      status.textContent = String(error.message || error);
    } finally {
      if (current === request) {
        busy = false;
        reload.disabled = false;
        list.querySelectorAll('button').forEach(button => { button.disabled = snapshot == null; });
      }
    }
  }

  async function choose(id) {
    if (busy || disconnected || !snapshot) return;
    const focused = document.activeElement?.dataset?.variant;
    const current = ++request;
    busy = true;
    reload.disabled = true;
    list.querySelectorAll('button').forEach(button => { button.disabled = true; });
    status.textContent = 'Saving your selection…';
    try {
      const result = await callTool({ name: 'set_variant_pick', arguments: {
        unit_id: snapshot.unit_id, variant_id: id, expected_revision: snapshot.revision,
      } });
      if (current !== request) return;
      busy = false;
      const data = resultData(result);
      show(data, data.status === 'conflict' ? data.message : undefined, focused);
    } catch {
      if (current !== request || disconnected) return;
      // A lost response can follow a committed write. Do not retry a mutation blindly.
      status.textContent = 'Save could not be confirmed. Reload saved selection before choosing again.';
      snapshot = null;
    } finally {
      if (current === request) {
        busy = false;
        reload.disabled = false;
        list.querySelectorAll('button').forEach(button => { button.disabled = snapshot == null; });
      }
    }
  }

  return { refresh, receive(result) {
    if (disconnected) return;
    // Host tool results may be historical. Always reconcile with the canonical server file.
    if (result?.isError) status.textContent = 'The host request failed. Reload saved selection to retry.';
    else void refresh();
  }, disconnected() {
    disconnected = true;
    ++request;
    busy = false;
    snapshot = null;
    list.querySelectorAll('button').forEach(button => { button.disabled = true; });
    reload.disabled = true;
    status.textContent = 'Disconnected. Reopen the panel to load your saved selection.';
  } };
}
