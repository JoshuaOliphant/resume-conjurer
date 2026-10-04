# ABOUTME: Stores editable source documents with content revisions on the local filesystem.
# ABOUTME: Preserves immutable snapshots and original uploads alongside atomic current files.

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from threading import Lock

DOCUMENT_NAMES = frozenset({"master-resume.md", "grimoire.md"})
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


def _verify_immutable(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise ValueError("Existing immutable content is a symlink")
    if path.exists() and path.read_bytes() != content:
        raise ValueError("Existing immutable content differs")


def _write_immutable(path: Path, content: bytes) -> None:
    try:
        destination = path.open("xb")
    except FileExistsError:
        _verify_immutable(path, content)
        return
    complete = False
    try:
        with destination:
            destination.write(content)
        complete = True
    finally:
        if not complete:
            path.unlink(missing_ok=True)


class ConflictError(ValueError):
    """The document changed since the caller read it."""


class DocumentStore:
    def __init__(self, root: Path, names: frozenset[str] = DOCUMENT_NAMES) -> None:
        self.root = root
        self.names = names
        self._lock = Lock()

    def _document_path(self, name: str) -> Path:
        if name not in self.names:
            raise ValueError(f"Invalid document name: {name}")
        return self.root / name

    def read(self, name: str) -> str:
        """Return the exact UTF-8 source text, or an empty string if absent."""
        return self.read_with_revision(name)[0]

    def revision(self, name: str) -> str:
        """Return the source content hash, or an empty string if absent."""
        return self.read_with_revision(name)[1]

    def read_with_revision(self, name: str) -> tuple[str, str]:
        """Return matching text and hash from one read, or two empty strings if absent."""
        path = self._document_path(name)
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return "", ""
        return content.decode("utf-8"), hashlib.sha256(content).hexdigest()

    def history(self, name: str) -> list[str]:
        self._document_path(name)
        directory = self.root / ".document-history" / name
        return sorted(path.stem for path in directory.glob("*.md"))

    def _snapshot(self, name: str, revision: str, content: bytes) -> None:
        directory = self.root / ".document-history" / name
        directory.mkdir(parents=True, exist_ok=True)
        _write_immutable(directory / f"{revision}.md", content)

    def save(self, name: str, text: str, expected_revision: str) -> str:
        with self._lock:
            return self._save(name, text, expected_revision)

    def _save(self, name: str, text: str, expected_revision: str) -> str:
        path = self._document_path(name)
        current_revision = self.revision(name)
        if current_revision != expected_revision:
            raise ConflictError("Document revision is stale")
        if not text.strip():
            raise ValueError("Document must not be empty")
        content = text.encode("utf-8")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise ValueError("Document exceeds 2 MiB")
        new_revision = hashlib.sha256(content).hexdigest()
        if new_revision == current_revision:
            return new_revision

        self.root.mkdir(parents=True, exist_ok=True)
        next_snapshot = self.root / ".document-history" / name / f"{new_revision}.md"
        _verify_immutable(next_snapshot, content)
        snapshot_existed = next_snapshot.exists()
        if current_revision:
            self._snapshot(name, current_revision, path.read_bytes())

        temporary_name: str | None = None
        committed = False
        try:
            self._snapshot(name, new_revision, content)
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{name}.", dir=self.root)
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(content)
            os.replace(temporary_name, path)
            committed = True
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
            if not committed and not snapshot_existed:
                next_snapshot.unlink(missing_ok=True)
        return new_revision

    def store_original(self, filename: str, content: bytes) -> str:
        if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
            raise ValueError("Invalid original filename")
        revision = hashlib.sha256(content).hexdigest()
        directory = self.root / ".document-originals" / revision
        directory.mkdir(parents=True, exist_ok=True)
        _write_immutable(directory / filename, content)
        return revision

    def purge_original(self, original_hash: str) -> bool:
        """Remove an uploaded original file and its directory.

        Returns True if the original was found and removed, False if it did not
        exist. Use this when a user explicitly removes a source to honor data
        deletion requests.
        """
        if not original_hash or "/" in original_hash or "\\" in original_hash:
            return False
        directory = self.root / ".document-originals" / original_hash
        if not directory.is_dir():
            return False
        import shutil
        shutil.rmtree(directory)
        return True
