// ABOUTME: Progressive enhancement for the curation screen — keyboard picking and nav.
// ABOUTME: The form works without this (click a variant, submit). JS only adds speed.

(function () {
  "use strict";

  // One listener for the page lifetime. It reads the current curate form on each
  // keypress, so it keeps working across hx-boost swaps without re-binding (which
  // would stack duplicate handlers and fire Enter multiple times).
  document.addEventListener("keydown", function (e) {
    const form = document.querySelector("form[data-curate]");
    if (!form) return;

    const radios = Array.from(form.querySelectorAll('input[name="variant_id"]'));
    if (!radios.length) return;

    // Don't hijack typing in text fields.
    const t = e.target;
    if (t && (t.tagName === "TEXTAREA" || (t.tagName === "INPUT" && t.type !== "radio"))) return;

    // 1–9 pick the matching variant.
    if (/^[1-9]$/.test(e.key)) {
      const idx = parseInt(e.key, 10) - 1;
      const r = radios[idx];
      if (r) {
        e.preventDefault();
        r.checked = true;
        r.dispatchEvent(new Event("change", { bubbles: true }));
        r.focus({ preventScroll: false });
      }
      return;
    }

    // Enter continues once something is chosen.
    if (e.key === "Enter" && radios.some((r) => r.checked)) {
      const btn = form.querySelector("[data-continue]");
      if (btn && document.activeElement !== btn) {
        e.preventDefault();
        form.requestSubmit ? form.requestSubmit(btn) : form.submit();
      }
    }
  });
})();
