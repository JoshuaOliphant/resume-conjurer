# Final document editing

In a configured live workspace, choose one variant for every application unit, then use **Compose final documents** on `/review`. Composition is an explicit POST. Reloading review never rebuilds or overwrites `applications/<slug>/cover_letter.md` or `resume.md`. The plugin and web app use these same Markdown files; `variants.md` remains the only pick store.

Open either **Edit** link on review to change the saved Markdown. Saving checks the revision shown when the editor opened. A stale save returns a conflict page with the submitted text for recovery. Earlier versions are retained under the application's `.document-history/` directory. Rebuild from picks is also explicit, checks both current final revisions, and may replace manual edits; those earlier versions remain in history.

Review and export read the saved final text. PDF and DOCX exports derive from those files when the local exporter is available. A binary download is offered only for the final revisions from which it was rendered. Older binary files stay on disk after edits, but the download route will not serve them. Markdown downloads return the current saved bytes. An export failure leaves the final Markdown available.

The composition record stores a fingerprint of the exact variant, master resume, grimoire, evidence, and job description bytes used for the last rebuild. If those inputs later change, review warns that composition is stale and leaves the saved finals intact. Manual edits also remain intact. Claim support for edited or stale finals is shown as unchecked; a fingerprint match is provenance, not independent verification of the final claims. A missing, corrupt, or unreadable composition record likewise leaves the finals intact and calls for an explicit rebuild.

The workbench is currently local and single-user. Source saves, pick changes, generation starts, final saves, composition, and export share a process-local lock. Use one server process; external writers and multiple processes are outside this coordination. The fixed application slug is a current product limit.
