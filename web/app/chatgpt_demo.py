# ABOUTME: Synthetic, local-only MCP Apps curation spike using canonical variants.md picks.
# ABOUTME: No generation, real career data, authentication, or production hosting is exposed.
"""Run with an explicitly selected scratch directory; see docs/plans/chatgpt-prototype.md."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from app.adapters.scripts_path import ensure_scripts_on_path

ensure_scripts_on_path()
from picks import apply_picks  # noqa: E402
from stitch import parse_variants_md  # noqa: E402

UNIT_ID = "resume.example.engineer.bullet_1"
RESOURCE_URI = "ui://conjurer/curate-v1.html"
UI_PATH = Path(__file__).parent / "static" / "chatgpt" / "curate.html"
EVIDENCE = "Built a Python service that validates incoming order events and reports invalid records."
FIXTURE = f"""# Synthetic curation example

## Unit: {UNIT_ID}
<!-- conjurer:unit id={UNIT_ID} -->

### Variant 1: synthetic evidence.md L1
Built a Python service to validate incoming order events and report invalid records.
- [ ] Pick

### Variant 2: synthetic evidence.md L1
Validated incoming order events with a Python service, surfacing invalid records for review.
- [ ] Pick

### Variant 3: synthetic evidence.md L1
Implemented order-event validation and invalid-record reporting in a Python service.
- [ ] Pick

### Variant 4: synthetic evidence.md L1
Developed a Python service for checking order events and reporting records that failed validation.
- [ ] Pick
"""


class FixtureStore:
    """Single-process demo store. Picks live only in variants.md, not UI state or JSON."""

    def __init__(self, directory: Path):
        self.path = directory / "variants.md"
        self.lock = Lock()

    def initialize(self) -> None:
        """Explicit setup, never called by a read tool. Existing data is not overwritten."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(FIXTURE, encoding="utf-8")
        self.read()

    def _snapshot(self, text: str) -> dict[str, Any]:
        units = parse_variants_md(text)
        if len(units) != 1 or units[0].unit_id != UNIT_ID:
            raise ValueError("This demo requires its one synthetic unit; use a fresh scratch directory.")
        unit = units[0]
        if [v.n for v in unit.variants] != [1, 2, 3, 4]:
            raise ValueError("This demo requires exactly four synthetic variants.")
        selected = unit.picked
        if re.sub(r"- \[[ xX]\] Pick", "- [ ] Pick", text) != FIXTURE:
            raise ValueError("Only the unchanged synthetic fixture and its Pick checkboxes are allowed.")
        return {
            "application_id": "synthetic-demo",
            "unit_id": UNIT_ID,
            "revision": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "selected_variant": selected.n if selected else None,
            "variants": [
                {"id": v.n, "text": v.content, "citation": v.citation,
                 "evidence": EVIDENCE, "support": "unchecked"}
                for v in unit.variants
            ],
        }

    def read(self) -> dict[str, Any]:
        with self.lock:
            return self._snapshot(self.path.read_text(encoding="utf-8"))

    def pick(self, unit_id: str, variant_id: int, expected_revision: str) -> dict[str, Any]:
        with self.lock:
            original_mode = self.path.stat().st_mode & 0o777
            text = self.path.read_text(encoding="utf-8")
            current = self._snapshot(text)
            if unit_id != UNIT_ID or type(variant_id) is not int or variant_id not in range(1, 5):
                raise ValueError("Unknown unit or variant.")
            # An exact replay after a changed pick is a conflict but has no further
            # effect: MCP idempotence concerns effects, not identical responses.
            if current["revision"] != expected_revision:
                return {"status": "conflict", "message": "Selection changed. Review the current pick and choose again.", **current}
            updated = apply_picks(text, {unit_id: variant_id})
            if updated == text:
                return {"status": "saved", **current}
            # Same-pick retries against the current revision are harmless; atomic replacement
            # prevents interrupted writes from truncating the canonical document.
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                try:
                    handle.write(updated)
                    handle.flush()
                    os.chmod(temporary, original_mode)
                    os.fsync(handle.fileno())
                    os.replace(temporary, self.path)
                finally:
                    temporary.unlink(missing_ok=True)
            return {"status": "saved", **self._snapshot(updated)}


def create_server(store: FixtureStore) -> FastMCP:
    """Create a loopback-only, synthetic MCP server. No workspace path enters a tool schema."""
    server = FastMCP("Conjurer synthetic curation", host="127.0.0.1", port=8401,
                     stateless_http=True, json_response=True)

    @server.resource(RESOURCE_URI, mime_type="text/html;profile=mcp-app",
                     meta={"ui": {"csp": {"connectDomains": [], "resourceDomains": [], "frameDomains": []}}})
    def panel() -> str:
        return UI_PATH.read_text(encoding="utf-8")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                            idempotentHint=True, openWorldHint=False),
                 meta={"ui": {"resourceUri": RESOURCE_URI},
                       "openai/ui": {"entrypoints": [{"type": "thread"}]}})
    def open_curation_demo() -> dict[str, Any]:
        """Open one synthetic résumé bullet with four choices. Never choose for the user."""
        return store.read()

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                            idempotentHint=True, openWorldHint=False),
                 meta={"ui": {"resourceUri": RESOURCE_URI, "visibility": ["app"]}})
    def set_variant_pick(
        unit_id: Literal["resume.example.engineer.bullet_1"],
        variant_id: Annotated[int, Field(strict=True, ge=1, le=4)],
        expected_revision: Annotated[str, Field(pattern="^[a-f0-9]{64}$")],
    ) -> dict[str, Any]:
        """Persist only an explicit panel selection. Reject stale choices; never auto-select."""
        return store.pick(unit_id, variant_id, expected_revision)

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local synthetic ChatGPT curation prototype")
    parser.add_argument("--scratch-dir", type=Path, required=True,
                        help="Dedicated synthetic directory, never a real career workspace")
    args = parser.parse_args(argv)
    store = FixtureStore(args.scratch_dir)
    store.initialize()
    create_server(store).run(transport="streamable-http")


if __name__ == "__main__":
    main()
