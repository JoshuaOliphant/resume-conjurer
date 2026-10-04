# ABOUTME: Exercises document revisions and original uploads against a real temporary filesystem.
# ABOUTME: Checks conflicts, validation, and preserved history without touching workspace fixtures.

from __future__ import annotations

import hashlib
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from app.document_store import ConflictError, DocumentStore


@pytest.fixture
def store(tmp_path: Path) -> DocumentStore:
    return DocumentStore(tmp_path / "documents")


def test_missing_document_and_history(store: DocumentStore) -> None:
    assert store.read("master-resume.md") == ""
    assert store.revision("master-resume.md") == ""
    assert store.read_with_revision("master-resume.md") == ("", "")
    assert store.history("master-resume.md") == []


def test_save_preserves_exact_text_and_revisions_across_instances(store: DocumentStore) -> None:
    first = "# Resume\r\n\r\nFirst line\n"
    first_revision = store.save("master-resume.md", first, "")
    assert first_revision == hashlib.sha256(first.encode("utf-8")).hexdigest()
    assert store.read("master-resume.md") == first

    second = "# Résumé\nSecond line\n"
    second_revision = store.save("master-resume.md", second, first_revision)
    reloaded = DocumentStore(store.root)
    assert reloaded.read("master-resume.md") == second
    assert reloaded.revision("master-resume.md") == second_revision
    assert set(reloaded.history("master-resume.md")) == {first_revision, second_revision}
    history_root = store.root / ".document-history" / "master-resume.md"
    assert (history_root / f"{first_revision}.md").read_bytes() == first.encode("utf-8")
    assert (history_root / f"{second_revision}.md").read_bytes() == second.encode("utf-8")
    assert reloaded.save("master-resume.md", first, second_revision) == first_revision
    assert reloaded.read("master-resume.md") == first
    assert set(reloaded.history("master-resume.md")) == {first_revision, second_revision}


def test_stale_revision_rejects_write_without_changing_document(store: DocumentStore) -> None:
    revision = store.save("grimoire.md", "current", "")
    with pytest.raises(ConflictError, match="revision"):
        store.save("grimoire.md", "replacement", "")
    assert store.read("grimoire.md") == "current"
    assert store.history("grimoire.md") == [revision]


def test_concurrent_saves_on_one_store_reject_the_stale_writer(
    store: DocumentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_writing = Event()
    release_first = Event()
    second_started = Event()
    snapshot = store._snapshot

    def pause_first_snapshot(name: str, revision: str, content: bytes) -> None:
        if content == b"first":
            first_writing.set()
            assert release_first.wait(timeout=2)
        snapshot(name, revision, content)

    monkeypatch.setattr(store, "_snapshot", pause_first_snapshot)

    def second_save() -> str:
        second_started.set()
        return store.save("grimoire.md", "second", "")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(store.save, "grimoire.md", "first", "")
        assert first_writing.wait(timeout=2)
        second = executor.submit(second_save)
        assert second_started.wait(timeout=2)
        release_first.set()
        first_revision = first.result(timeout=2)
        with pytest.raises(ConflictError, match="revision"):
            second.result(timeout=2)

    assert store.read("grimoire.md") == "first"
    assert store.history("grimoire.md") == [first_revision]


def test_same_text_is_noop_and_history_is_not_overwritten(store: DocumentStore) -> None:
    revision = store.save("grimoire.md", "same", "")
    snapshot = store.root / ".document-history" / "grimoire.md" / f"{revision}.md"
    snapshot.write_text("sentinel", encoding="utf-8")
    assert store.save("grimoire.md", "same", revision) == revision
    assert store.history("grimoire.md") == [revision]
    assert snapshot.read_text(encoding="utf-8") == "sentinel"
    with pytest.raises(ValueError, match="immutable"):
        store.save("grimoire.md", "next", revision)
    assert store.read("grimoire.md") == "same"
    assert snapshot.read_text(encoding="utf-8") == "sentinel"


def test_conflicting_new_snapshot_rejects_save_before_replacing_source(store: DocumentStore) -> None:
    revision = store.save("grimoire.md", "current", "")
    next_revision = hashlib.sha256(b"next").hexdigest()
    snapshot = store.root / ".document-history" / "grimoire.md" / f"{next_revision}.md"
    snapshot.write_bytes(b"sentinel")

    with pytest.raises(ValueError, match="immutable"):
        store.save("grimoire.md", "next", revision)

    assert store.read("grimoire.md") == "current"
    assert store.revision("grimoire.md") == revision
    assert snapshot.read_bytes() == b"sentinel"


def test_failed_replace_keeps_current_document_and_cleans_temporary_file(
    store: DocumentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = store.save("grimoire.md", "current", "")

    def fail_replace(source: str, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.save("grimoire.md", "replacement", revision)

    assert store.read("grimoire.md") == "current"
    assert store.history("grimoire.md") == [revision]
    assert list(store.root.glob(".grimoire.md.*")) == []


def test_failed_new_history_snapshot_keeps_current_document(
    store: DocumentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_revision = store.save("grimoire.md", "current", "")
    next_revision = hashlib.sha256(b"replacement").hexdigest()
    real_snapshot = store._snapshot

    def fail_after_snapshot(name: str, revision: str, content: bytes) -> None:
        real_snapshot(name, revision, content)
        if revision == next_revision:
            raise OSError("history write failed")

    monkeypatch.setattr(store, "_snapshot", fail_after_snapshot)
    with pytest.raises(OSError, match="history write failed"):
        store.save("grimoire.md", "replacement", current_revision)
    assert store.read("grimoire.md") == "current"
    assert store.revision("grimoire.md") == current_revision
    assert store.history("grimoire.md") == [current_revision]


def test_failed_temporary_file_preserves_existing_identical_history(
    store: DocumentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_revision = store.save("grimoire.md", "current", "")
    next_content = b"replacement"
    next_revision = hashlib.sha256(next_content).hexdigest()
    store._snapshot("grimoire.md", next_revision, next_content)

    def fail_temporary_file(*args, **kwargs):
        raise OSError("temporary file failed")

    monkeypatch.setattr(tempfile, "mkstemp", fail_temporary_file)
    with pytest.raises(OSError, match="temporary file failed"):
        store.save("grimoire.md", next_content.decode(), current_revision)
    assert store.read("grimoire.md") == "current"
    assert set(store.history("grimoire.md")) == {current_revision, next_revision}
    snapshot = store.root / ".document-history" / "grimoire.md" / f"{next_revision}.md"
    assert snapshot.read_bytes() == next_content


def test_read_with_revision_uses_one_source_read(
    store: DocumentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_text = "# Old source\n"
    old_revision = store.save("master-resume.md", old_text, "")
    source = store.root / "master-resume.md"
    real_read = Path.read_bytes
    reads = 0

    def replace_after_read(path: Path) -> bytes:
        nonlocal reads
        data = real_read(path)
        if path == source:
            reads += 1
            if reads == 1:
                source.write_text("# New source\n")
        return data

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    assert store.read_with_revision("master-resume.md") == (old_text, old_revision)
    assert reads == 1


@pytest.mark.parametrize(
    "text", ["", " \n\t", "x" * (2 * 1024 * 1024 + 1)], ids=["empty", "whitespace", "too-large"]
)
def test_save_rejects_empty_or_oversized_utf8(store: DocumentStore, text: str) -> None:
    with pytest.raises(ValueError):
        store.save("master-resume.md", text, "")
    assert store.revision("master-resume.md") == ""


def test_size_limit_counts_utf8_bytes(store: DocumentStore) -> None:
    with pytest.raises(ValueError, match="2 MiB"):
        store.save("grimoire.md", "é" * (1024 * 1024 + 1), "")


@pytest.mark.parametrize("name", ["../master-resume.md", "evidence.md", "/tmp/grimoire.md"])
def test_document_names_are_allowlisted(store: DocumentStore, name: str) -> None:
    with pytest.raises(ValueError, match="document name"):
        store.read(name)
    with pytest.raises(ValueError, match="document name"):
        store.revision(name)
    with pytest.raises(ValueError, match="document name"):
        store.history(name)
    with pytest.raises(ValueError, match="document name"):
        store.save(name, "text", "")


def test_original_upload_preserves_bytes_and_uses_content_hash(store: DocumentStore) -> None:
    content = b"\x00original\r\n\xff"
    revision = store.store_original("resume.pdf", content)
    assert revision == hashlib.sha256(content).hexdigest()
    assert (store.root / ".document-originals" / revision / "resume.pdf").read_bytes() == content
    assert store.store_original("resume.pdf", content) == revision


@pytest.mark.parametrize("filename", ["../outside.pdf", "nested/file.pdf", r"nested\file.pdf", "", "."])
def test_original_upload_rejects_unsafe_names(store: DocumentStore, filename: str) -> None:
    with pytest.raises(ValueError, match="filename"):
        store.store_original(filename, b"file")


def test_original_upload_does_not_overwrite_existing_bytes(store: DocumentStore) -> None:
    content = b"file"
    revision = store.store_original("resume.pdf", content)
    original = store.root / ".document-originals" / revision / "resume.pdf"
    original.write_bytes(b"sentinel")
    with pytest.raises(ValueError, match="immutable"):
        store.store_original("resume.pdf", content)
    assert original.read_bytes() == b"sentinel"


@pytest.mark.parametrize("failure", ["write", "close"])
def test_failed_immutable_write_cleans_only_its_new_file_and_retry_succeeds(
    store: DocumentStore, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    content = b"complete original"
    revision = hashlib.sha256(content).hexdigest()
    original = store.root / ".document-originals" / revision / "resume.pdf"
    real_open = Path.open

    class FailingFile:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def write(self, data):
            if failure == "write":
                self.stream.write(data[:4])
                raise OSError("immutable write failed")
            return self.stream.write(data)

        def __exit__(self, exc_type, exc_value, traceback):
            self.stream.__exit__(exc_type, exc_value, traceback)
            if failure == "close":
                raise OSError("immutable close failed")

    def fail_target_open(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        if path == original and mode == "xb":
            return FailingFile(stream)
        return stream

    monkeypatch.setattr(Path, "open", fail_target_open)
    with pytest.raises(OSError, match=f"immutable {failure} failed"):
        store.store_original("resume.pdf", content)
    assert not original.exists()
    monkeypatch.setattr(Path, "open", real_open)
    assert store.store_original("resume.pdf", content) == revision
    assert original.read_bytes() == content


def test_original_upload_rejects_symlink_in_place_of_immutable_file(
    store: DocumentStore, tmp_path: Path
) -> None:
    content = b"file"
    revision = hashlib.sha256(content).hexdigest()
    original = store.root / ".document-originals" / revision / "resume.pdf"
    original.parent.mkdir(parents=True)
    external = tmp_path / "external.pdf"
    external.write_bytes(content)
    original.symlink_to(external)

    with pytest.raises(ValueError, match="symlink"):
        store.store_original("resume.pdf", content)
    assert external.read_bytes() == content


def test_purge_original_removes_upload_directory(store: DocumentStore) -> None:
    content = b"sensitive personal data"
    revision = store.store_original("resume.pdf", content)
    original_dir = store.root / ".document-originals" / revision
    assert original_dir.is_dir()
    assert (original_dir / "resume.pdf").read_bytes() == content

    assert store.purge_original(revision) is True
    assert not original_dir.exists()
    assert store.purge_original(revision) is False


def test_purge_original_rejects_invalid_hashes(store: DocumentStore) -> None:
    content = b"file"
    revision = store.store_original("resume.pdf", content)
    assert store.purge_original("") is False
    assert store.purge_original("../parent") is False
    assert store.purge_original("sub/path") is False
    assert store.purge_original(r"sub\path") is False
    assert (store.root / ".document-originals" / revision / "resume.pdf").exists()
