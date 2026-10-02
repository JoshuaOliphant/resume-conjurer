# ABOUTME: Coordinates application-local final Markdown and its composition provenance.
# ABOUTME: Stages picked text before explicit rebuilds and retains editable revision history.

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.adapters.scripts_path import ensure_scripts_on_path
from app.document_store import ConflictError, DocumentStore
from app.domain import validate_slug

ensure_scripts_on_path()

from stitch import stitch_app_dir  # noqa: E402

FINAL_NAMES = frozenset({"cover_letter.md", "resume.md"})
INPUT_NAMES = ("variants.md", "master-resume.md", "grimoire.md", "evidence.md", "jd.txt")


@dataclass(frozen=True)
class FinalState:
    cover_text: str
    resume_text: str
    cover_revision: str
    resume_revision: str
    stale: bool
    edited: bool
    metadata_warning: str

    @property
    def complete(self) -> bool:
        return bool(self.cover_revision and self.resume_revision)


class FinalDocuments:
    def __init__(self, root: Path, slug: str) -> None:
        validate_slug(slug)
        self.root = root
        self.app_dir = root / "applications" / slug
        self.store = DocumentStore(self.app_dir, FINAL_NAMES)
        self._lock = Lock()

    def _input_paths(self) -> tuple[Path, ...]:
        return (
            self.app_dir / "variants.md",
            self.root / "master-resume.md",
            self.root / "grimoire.md",
            self.app_dir / "evidence.md",
            self.app_dir / "jd.txt",
        )

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for name, path in zip(INPUT_NAMES, self._input_paths(), strict=True):
            try:
                content = path.read_bytes()
            except FileNotFoundError:
                if name != "evidence.md":
                    raise
                content = b""
            digest.update(name.encode())
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return digest.hexdigest()

    def _metadata(self) -> tuple[dict | None, str]:
        try:
            raw = (self.app_dir / ".final-composition.json").read_text()
        except FileNotFoundError:
            return None, "Composition record is missing. Rebuild from picks to restore the composition record."
        except (OSError, UnicodeError):
            return None, "Composition record could not be read. Final text is intact; rebuild from picks to restore the composition record."
        try:
            metadata = json.loads(raw)
        except ValueError:
            return None, "Composition record is invalid. Final text is intact; rebuild from picks to restore the composition record."
        if (
            not isinstance(metadata, dict)
            or not isinstance(metadata.get("fingerprint"), str)
            or not isinstance(metadata.get("composed_revisions"), dict)
            or any(not isinstance(metadata["composed_revisions"].get(name), str) for name in FINAL_NAMES)
        ):
            return None, "Composition record is invalid. Final text is intact; rebuild from picks to restore the composition record."
        return metadata, ""

    def state(self) -> FinalState:
        cover, cover_revision = self.store.read_with_revision("cover_letter.md")
        resume, resume_revision = self.store.read_with_revision("resume.md")
        if not (cover_revision or resume_revision):
            return FinalState(cover, resume, cover_revision, resume_revision, False, False, "")
        metadata, metadata_warning = self._metadata()
        try:
            fingerprint = self.fingerprint()
        except FileNotFoundError:
            fingerprint = ""
        stale = metadata is None or metadata.get("fingerprint") != fingerprint
        composed = metadata.get("composed_revisions", {}) if metadata else {}
        edited = bool(metadata) and (
            composed.get("cover_letter.md") != cover_revision
            or composed.get("resume.md") != resume_revision
        )
        return FinalState(cover, resume, cover_revision, resume_revision, stale, edited, metadata_warning)

    def save(self, name: str, text: str, expected_revision: str) -> str:
        with self._lock:
            return self.store.save(name, text, expected_revision)

    def record_exports(self, exported: dict[str, str]) -> None:
        state = self.state()
        artifacts = {}
        for name, status in exported.items():
            if name in {"cover_letter.pdf", "cover_letter.docx", "resume.pdf", "resume.docx"} and status == "written":
                path = self.app_dir / name
                if path.is_file():
                    artifacts[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {"cover_revision": state.cover_revision, "resume_revision": state.resume_revision, "artifacts": artifacts}
        descriptor, temporary_name = tempfile.mkstemp(prefix=".final-exports.", dir=self.app_dir)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                json.dump(manifest, temporary)
            os.replace(temporary_name, self.app_dir / ".final-exports.json")
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    def can_download(self, name: str) -> bool:
        if name in FINAL_NAMES:
            return bool(self.store.revision(name))
        if name not in {"cover_letter.pdf", "cover_letter.docx", "resume.pdf", "resume.docx"}:
            return False
        try:
            manifest = json.loads((self.app_dir / ".final-exports.json").read_text())
            state = self.state()
            expected = manifest["artifacts"].get(name)
            return (
                state.complete
                and manifest["cover_revision"] == state.cover_revision
                and manifest["resume_revision"] == state.resume_revision
                and isinstance(expected, str)
                and hashlib.sha256((self.app_dir / name).read_bytes()).hexdigest() == expected
            )
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, AttributeError):
            return False

    def _restore(self, name: str, text: str, revision: str, owned_revision: str) -> None:
        if self.store.revision(name) != owned_revision:
            raise ConflictError("Final document changed during composition recovery")
        if revision:
            self.store.save(name, text, owned_revision)
        else:
            (self.app_dir / name).unlink(missing_ok=True)

    def compose(self, cover_revision: str, resume_revision: str) -> FinalState:
        with self._lock:
            before = self.state()
            if (before.cover_revision, before.resume_revision) != (cover_revision, resume_revision):
                raise ConflictError("Final document revision is stale")
            fingerprint = self.fingerprint()
            with tempfile.TemporaryDirectory(prefix=".final-compose-", dir=self.app_dir) as directory:
                staged = Path(directory)
                (staged / "variants.md").write_bytes((self.app_dir / "variants.md").read_bytes())
                cover_path, resume_path = stitch_app_dir(staged, self.root / "master-resume.md")
                cover_text = cover_path.read_text()
                resume_text = resume_path.read_text()
            if self.fingerprint() != fingerprint:
                raise ConflictError("Composition sources changed during rebuild")

            next_cover = self.store.save("cover_letter.md", cover_text, cover_revision)
            next_resume = resume_revision
            try:
                next_resume = self.store.save("resume.md", resume_text, resume_revision)
                metadata = {
                    "fingerprint": fingerprint,
                    "composed_revisions": {"cover_letter.md": next_cover, "resume.md": next_resume},
                }
                descriptor, temporary_name = tempfile.mkstemp(prefix=".final-composition.", dir=self.app_dir)
                try:
                    with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                        json.dump(metadata, temporary)
                    os.replace(temporary_name, self.app_dir / ".final-composition.json")
                finally:
                    Path(temporary_name).unlink(missing_ok=True)
            except (OSError, ValueError, RuntimeError):
                self._restore("resume.md", before.resume_text, before.resume_revision, next_resume)
                self._restore("cover_letter.md", before.cover_text, before.cover_revision, next_cover)
                raise
            return self.state()
