# ABOUTME: Route and flow tests for the Conjurer web UI.
# ABOUTME: Covers every screen renders, the curate flow stores picks, and review reflects them.

import asyncio
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape
from test_document_import import _docx, _pdf

from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.scripts_path import ensure_scripts_on_path
from app.adapters.verification_fake import NoVerificationPort
from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.data import EVIDENCE, _v, get_application
from app.document_import import import_document
from app.document_routes import MAX_UPLOAD_REQUEST_BYTES, DocumentUploadLimit
from app.document_store import DocumentStore
from app.domain import Application, Frame, Support, Unit, Variant
from app.main import SLUG, create_app
from app.runs import RunManager, RunStatus

ensure_scripts_on_path()

import verify  # noqa: E402


@pytest.fixture
def repo():
    return FakeWorkspaceRepository()


@pytest.fixture
def client(repo):
    gen = FakeGenerationPort()
    app = create_app(repo=repo, gen=gen, run_manager=RunManager(repo=repo, gen=gen, verifier=NoVerificationPort()), live=False)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def document_store(tmp_path):
    (tmp_path / "master-resume.md").write_text("# Master\n- Original claim\n")
    (tmp_path / "grimoire.md").write_text("# Voice\nWrite plainly.\n")
    return DocumentStore(tmp_path)


@pytest.fixture
def document_gen():
    return FakeGenerationPort()


@pytest.fixture
def document_runs(repo, document_gen):
    return RunManager(repo=repo, gen=document_gen, verifier=NoVerificationPort())


@pytest.fixture
def document_client(repo, document_store, document_runs, document_gen):
    app = create_app(repo=repo, gen=document_gen, run_manager=document_runs,
                     documents=document_store, live=False)
    with TestClient(app) as c:
        yield c


def test_document_workbench_shows_saved_sources_and_entry_link(document_client, document_store, client):
    assert "/documents" not in client.get("/").text
    assert 'href="/documents"' in document_client.get("/").text

    master = document_client.get("/documents")
    assert master.status_code == 200
    assert "# Master\n- Original claim" in master.text
    assert 'aria-current="page"' in master.text
    assert 'name="document_name" value="master-resume.md"' in master.text
    assert f'name="revision" value="{document_store.revision("master-resume.md")}"' in master.text
    assert 'action="/documents/import"' in master.text
    assert 'action="/documents/save"' in master.text

    grimoire = document_client.get("/documents?name=grimoire.md")
    assert grimoire.status_code == 200
    assert "Write plainly." in grimoire.text
    assert 'name="document_name" value="grimoire.md"' in grimoire.text


def test_document_workbench_renders_text_and_revision_from_one_read(
    document_client, document_store, monkeypatch
):
    source = document_store.root / "master-resume.md"
    old_text = document_store.read("master-resume.md")
    old_revision = hashlib.sha256(old_text.encode()).hexdigest()
    real_read = Path.read_bytes
    reads = 0

    def replace_after_read(path):
        nonlocal reads
        data = real_read(path)
        if path == source:
            reads += 1
            if reads == 1:
                source.write_text("# Replaced during render\n")
        return data

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    response = document_client.get("/documents")
    assert response.status_code == 200
    assert old_text.strip() in response.text
    assert f'name="revision" value="{old_revision}"' in response.text
    assert reads == 1


def test_document_workbench_escapes_source_and_rejects_invalid_names(document_client, document_store):
    source = "# Voice\n<script>alert(1)</script>\n"
    (document_store.root / "grimoire.md").write_text(source)
    html = document_client.get("/documents?name=grimoire.md").text
    assert str(escape("<script>alert(1)</script>")) in html
    assert "<script>alert(1)</script>" not in html
    assert document_client.get("/documents?name=../secrets.md").status_code == 400


def test_document_routes_require_configured_workspace(client):
    assert client.get("/documents").status_code == 503
    response = client.post("/documents/save", data={
        "document_name": "master-resume.md", "text": "# Replaced", "revision": "irrelevant",
    })
    assert response.status_code == 503


def test_final_routes_require_configured_workspace(client):
    assert client.get("/finals").status_code == 503
    assert client.post("/review/compose", data={}).status_code == 503
    assert client.post("/finals/save", data={"document_name": "resume.md", "text": "x", "revision": "x"}).status_code == 503


def test_document_import_previews_without_overwriting_and_saves_explicitly(document_client, document_store):
    original = document_store.read("master-resume.md")
    revision = document_store.revision("master-resume.md")
    content = b"# Imported\n- Verify this claim\n"
    response = document_client.post("/documents/import", data={
        "document_name": "master-resume.md", "revision": revision,
    }, files={"file": ("resume.md", content, "text/markdown")})
    assert response.status_code == 200
    assert "Review the imported text" in response.text
    assert "# Imported\n- Verify this claim" in response.text
    assert 'name="import_key"' in response.text
    assert "Cancel import" in response.text
    assert "No usable composer slots" in response.text
    assert "Prepare master resume" in response.text
    assert document_store.read("master-resume.md") == original
    digest = hashlib.sha256(content).hexdigest()
    assert (document_store.root / ".document-originals" / digest / "resume.md").read_bytes() == content

    saved = document_client.post("/documents/save", data={
        "document_name": "master-resume.md", "text": "# Imported\n- Checked claim\n",
        "revision": revision, "import_key": digest,
    }, follow_redirects=False)
    assert saved.status_code == 303
    assert saved.headers["location"] == "/documents?name=master-resume.md&saved=true"
    assert document_store.read("master-resume.md") == "# Imported\n- Checked claim\n"
    reloaded = document_client.get(saved.headers["location"])
    assert "Saved. Review existing applications" in reloaded.text
    assert "- Checked claim" in reloaded.text


def test_import_normalization_requires_correction_then_saves_reviewed_master(document_client, document_store):
    content = _docx(
        '<w:p><w:r><w:t>Casey | casey@example.com</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Experience</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Acme</w:t></w:r></w:p>'
        '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Staff Engineer</w:t></w:r>'
        '<w:r><w:t> | 2021-2024</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="ListBullet"/></w:pPr><w:r><w:t>Reduced cost 42%</w:t></w:r></w:p>'
    )
    extracted = import_document("resume.docx", content).text
    before = document_store.read("master-resume.md")
    revision = document_store.revision("master-resume.md")
    imported = document_client.post("/documents/import", data={
        "document_name": "master-resume.md", "revision": revision,
    }, files={"file": ("resume.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert imported.status_code == 200
    assert "needs correction" in imported.text
    assert document_store.read("master-resume.md") == before
    digest = hashlib.sha256(content).hexdigest()
    assert (document_store.root / ".document-originals" / digest / "resume.docx").read_bytes() == content

    preview = document_client.post("/documents/normalize", data={
        "document_name": "master-resume.md", "revision": revision, "text": extracted,
    })
    assert preview.status_code == 200
    assert "Source line 5" in preview.text
    assert "### Acme -- [enter employer context]" in preview.text
    assert "Reduced cost 42%" in preview.text
    assert "employer context" in preview.text
    assert document_store.read("master-resume.md") == before

    normalized = extracted.replace("### Acme", "### Acme -- 2021-2024").replace("**Staff Engineer** |", "**Staff Engineer** --")
    uncorrected = normalized.replace("### Acme -- 2021-2024", "### Acme -- [enter employer context]")
    blocked = document_client.post("/documents/normalize/accept", data={
        "document_name": "master-resume.md", "revision": revision,
        "text": uncorrected,
    })
    assert blocked.status_code == 422
    assert document_store.read("master-resume.md") == before
    accepted = document_client.post("/documents/normalize/accept", data={
        "document_name": "master-resume.md", "revision": revision, "text": normalized,
    }, follow_redirects=False)
    assert accepted.status_code == 303
    assert document_store.read("master-resume.md") == normalized
    assert revision in document_store.history("master-resume.md")


def test_normalization_requires_explicit_reading_order_review_for_docx_table(document_client, document_store):
    content = _docx(
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Experience</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Acme | 2021-2024</w:t></w:r></w:p>'
        '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Engineer</w:t></w:r><w:r><w:t> | 2021-2024</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="ListBullet"/></w:pPr><w:r><w:t>Saved 42%</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Training</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t>Systems course</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    )
    revision = document_store.revision("master-resume.md")
    imported = document_client.post("/documents/import", data={
        "document_name": "master-resume.md", "revision": revision,
    }, files={"file": ("resume.docx", content)})
    assert 'name="order_review_required" value="true"' in imported.text
    source = import_document("resume.docx", content).text
    preview = document_client.post("/documents/normalize", data={
        "document_name": "master-resume.md", "revision": revision, "text": source,
        "order_review_required": "true",
    })
    assert "reading order against the original file" in preview.text
    reviewed = preview.text
    assert "Training | Systems course" in reviewed
    draft = source.replace("### Acme |", "### Acme --").replace("**Engineer** |", "**Engineer** --")
    blocked = document_client.post("/documents/normalize/accept", data={
        "document_name": "master-resume.md", "revision": revision, "text": draft,
        "order_review_required": "true",
    })
    assert blocked.status_code == 422
    assert "Review and correct the reading order" in blocked.text
    assert document_store.read("master-resume.md") != draft
    accepted = document_client.post("/documents/normalize/accept", data={
        "document_name": "master-resume.md", "revision": revision, "text": draft,
        "order_review_required": "true", "order_corrected": "true",
    }, follow_redirects=False)
    assert accepted.status_code == 303
    assert "Training | Systems course" in document_store.read("master-resume.md")


def test_normalized_acceptance_rejects_stale_revision_with_draft_recovery(document_client, document_store):
    revision = document_store.revision("master-resume.md")
    draft = "## Experience\n### Acme -- 2021-2024\n**Staff Engineer** -- 2021-2024\n- Reduced cost 42%\n"
    document_store.save("master-resume.md", "# Newer source\n", revision)
    for _ in range(2):
        conflict = document_client.post("/documents/normalize/accept", data={
            "document_name": "master-resume.md", "revision": revision, "text": draft,
        })
        assert conflict.status_code == 409
        assert "Recover your unsaved normalized draft" in conflict.text
        assert draft.strip() in conflict.text
        assert f'name="revision" value="{revision}"' in conflict.text
        assert document_store.read("master-resume.md") == "# Newer source\n"


@pytest.mark.parametrize("path", ["/documents/normalize", "/documents/normalize/accept"], ids=["preview", "accept"])
def test_normalization_only_accepts_master_resume(document_client, document_store, path):
    response = document_client.post(path, data={
        "document_name": "grimoire.md", "revision": document_store.revision("grimoire.md"),
        "text": "## Experience\n### Acme -- 2021-2024\n**Engineer** -- 2021-2024\n- Saved 42%",
    })
    assert response.status_code == 400
    assert document_store.read("grimoire.md") == "# Voice\nWrite plainly.\n"


@pytest.mark.parametrize("path", ["/documents/normalize", "/documents/normalize/accept"], ids=["preview", "accept"])
def test_normalization_rejects_text_over_editor_limit(document_client, document_store, monkeypatch, path):
    import app.document_routes as routes

    monkeypatch.setattr(routes, "MAX_SOURCE_BYTES", 30)
    revision = document_store.revision("master-resume.md")
    response = document_client.post(path, data={
        "document_name": "master-resume.md", "revision": revision,
        "text": "## Experience\n" + "x" * 31,
    })
    assert response.status_code == 400
    assert "2 MiB editor limit" in response.text
    assert document_store.revision("master-resume.md") == revision


def test_normalized_acceptance_requires_exact_reviewed_structure(document_client, document_store):
    draft = "## Experience\n### Acme | 2021-2024\n**Engineer** | 2021-2024\n- Saved 42%\n"
    response = document_client.post("/documents/normalize/accept", data={
        "document_name": "master-resume.md", "revision": document_store.revision("master-resume.md"), "text": draft,
    })
    assert response.status_code == 422
    assert draft.strip() in response.text
    assert document_store.read("master-resume.md") == "# Master\n- Original claim\n"


def test_normalized_acceptance_uses_browser_form_line_endings(document_client, document_store):
    draft = "## Experience\n### Acme -- 2021-2024\n**Engineer** -- 2021-2024\n- Saved 42%\n"
    revision = document_store.revision("master-resume.md")
    preview = document_client.post("/documents/normalize", data={
        "document_name": "master-resume.md", "revision": revision, "text": draft,
    })
    assert preview.status_code == 200
    assert "1 usable composer slots found" in preview.text
    accepted = document_client.post("/documents/normalize/accept", data={
        "document_name": "master-resume.md", "revision": revision,
        "text": draft.replace("\n", "\r\n"),
    }, follow_redirects=False)
    assert accepted.status_code == 303
    assert document_store.read("master-resume.md") == draft


def test_normalized_acceptance_preserves_draft_on_concurrent_filesystem_change(document_client, document_store, monkeypatch):
    draft = "## Experience\n### Acme -- 2021-2024\n**Engineer** -- 2021-2024\n- Saved 42%\n"
    revision = document_store.revision("master-resume.md")
    source = document_store.root / "master-resume.md"
    read_bytes = Path.read_bytes
    replaced = False

    def concurrent_read(path):
        nonlocal replaced
        content = read_bytes(path)
        if path == source and not replaced:
            replaced = True
            source.write_text("# Newer source\n")
        return content

    monkeypatch.setattr(Path, "read_bytes", concurrent_read)
    response = document_client.post("/documents/normalize/accept", data={
        "document_name": "master-resume.md", "revision": revision, "text": draft,
    })
    assert response.status_code == 409
    assert draft.strip() in response.text
    assert f'name="revision" value="{revision}"' in response.text
    assert document_store.read("master-resume.md") == "# Newer source\n"


def test_normalized_acceptance_preserves_draft_on_immutable_snapshot_conflict(document_client, document_store):
    draft = "## Experience\n### Acme -- 2021-2024\n**Engineer** -- 2021-2024\n- Saved 42%\n"
    revision = document_store.revision("master-resume.md")
    digest = hashlib.sha256(draft.encode()).hexdigest()
    snapshot = document_store.root / ".document-history" / "master-resume.md" / f"{digest}.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("# Different immutable content\n")
    response = document_client.post("/documents/normalize/accept", data={
        "document_name": "master-resume.md", "revision": revision, "text": draft,
    })
    assert response.status_code == 400
    assert "Existing immutable content differs" in response.text
    assert draft.strip() in response.text
    assert f'name="revision" value="{revision}"' in response.text
    assert document_store.read("master-resume.md") == "# Master\n- Original claim\n"


@pytest.mark.parametrize(
    ("filename", "content", "expected", "warning"),
    [
        ("resume.docx", _docx('<w:p><w:pPr><w:pStyle w:val="ListBullet"/></w:pPr><w:r><w:t>Built 42 services</w:t></w:r></w:p>'), "- Built 42 services", None),
        ("resume.pdf", _pdf("Casey 2023", ""), "Casey 2023", "Page 2 has no extractable text"),
    ],
    ids=["docx-bullets", "pdf-missing-page"],
)
def test_document_import_previews_docx_and_pdf(document_client, document_store, filename, content, expected, warning):
    response = document_client.post("/documents/import", data={
        "document_name": "grimoire.md", "revision": document_store.revision("grimoire.md"),
    }, files={"file": (filename, content, "application/octet-stream")})
    assert response.status_code == 200
    assert expected in response.text
    if warning:
        assert warning in response.text
    else:
        assert "Check these parts" not in response.text
    assert document_store.read("grimoire.md") == "# Voice\nWrite plainly.\n"


@pytest.mark.parametrize(
    ("filename", "content", "status", "error"),
    [
        ("resume.rtf", b"{\\rtf1 text}", 400, "Unsupported document type"),
        ("resume.md", b"x" * (10 * 1024 * 1024 + 1), 400, "10 MiB size limit"),
        ("../resume.md", b"# Unsafe name", 400, "Invalid original filename"),
        ("", b"# No filename", 422, "UploadFile"),
        ("large.md", b"x" * (2 * 1024 * 1024 + 1), 400, "editor limit"),
    ],
    ids=["unsupported", "too-large", "unsafe-filename", "empty-filename", "extracted-too-large"],
)
def test_document_import_rejects_invalid_files_without_changing_source(
    document_client, document_store, filename, content, status, error
):
    response = document_client.post("/documents/import", data={
        "document_name": "master-resume.md", "revision": document_store.revision("master-resume.md"),
    }, files={"file": (filename, content, "application/octet-stream")})
    assert response.status_code == status
    assert error in response.text
    assert document_store.read("master-resume.md") == "# Master\n- Original claim\n"


def test_document_import_rejects_invalid_target(document_client):
    response = document_client.post("/documents/import", data={
        "document_name": "../grimoire.md", "revision": "irrelevant",
    }, files={"file": ("resume.md", b"# Text", "text/markdown")})
    assert response.status_code == 400


def test_document_import_rejects_oversized_request_before_multipart_parsing(document_client):
    response = document_client.post(
        "/documents/import",
        content=b"x" * (10 * 1024 * 1024 + 64 * 1024 + 1),
        headers={"content-type": "multipart/form-data; boundary=missing", "content-length": "1"},
    )
    assert response.status_code == 413
    assert "10 MiB" in response.text


def test_upload_limit_counts_chunked_body_without_content_length():
    messages = [
        {"type": "http.request", "body": b"x" * (MAX_UPLOAD_REQUEST_BYTES // 2), "more_body": True},
        {"type": "http.request", "body": b"x" * (MAX_UPLOAD_REQUEST_BYTES // 2 + 1), "more_body": False},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        pytest.fail("Multipart parsing must not receive an oversized request")

    scope = {"type": "http", "method": "POST", "path": "/documents/import", "headers": []}
    asyncio.run(DocumentUploadLimit(downstream)(scope, receive, send))
    assert sent[0]["status"] == 413


def test_upload_limit_replays_all_chunks_once_and_passes_later_receive():
    messages = [
        {"type": "http.request", "body": b"first ", "more_body": True},
        {"type": "http.request", "body": b"second", "more_body": False},
        {"type": "http.disconnect"},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        assert await receive() == {"type": "http.request", "body": b"first second", "more_body": False}
        assert await receive() == {"type": "http.disconnect"}
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    scope = {"type": "http", "method": "POST", "path": "/documents/import", "headers": []}
    asyncio.run(DocumentUploadLimit(downstream)(scope, receive, send))
    assert sent[0]["status"] == 204


def test_upload_limit_stops_when_client_disconnects():
    sent = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        pytest.fail("Disconnected upload must not reach the form parser")

    scope = {"type": "http", "method": "POST", "path": "/documents/import", "headers": []}
    asyncio.run(DocumentUploadLimit(downstream)(scope, receive, send))
    assert sent == []


def test_document_save_conflict_preserves_submitted_text(document_client, document_store):
    revision = document_store.revision("master-resume.md")
    document_store.save("master-resume.md", "# Another tab\n", revision)
    response = document_client.post("/documents/save", data={
        "document_name": "master-resume.md", "text": "# My unsaved claim\n", "revision": revision,
    })
    assert response.status_code == 409
    assert "changed in another tab" in response.text
    assert "Recover your unsaved changes" in response.text
    assert "Reload saved document" in response.text
    assert "Review the imported text" not in response.text
    assert "# My unsaved claim" in response.text
    assert document_store.read("master-resume.md") == "# Another tab\n"


@pytest.mark.parametrize("text", ["  \n  ", "x" * (2 * 1024 * 1024 + 1)], ids=["whitespace", "too-large-edit"])
def test_document_save_rejects_invalid_text_without_changing_source(document_client, document_store, text):
    response = document_client.post("/documents/save", data={
        "document_name": "grimoire.md", "text": text, "revision": document_store.revision("grimoire.md"),
    })
    assert response.status_code == 400
    assert document_store.read("grimoire.md") == "# Voice\nWrite plainly.\n"


def test_document_save_rejects_invalid_target(document_client, document_store):
    response = document_client.post("/documents/save", data={
        "document_name": "../grimoire.md", "text": "# Wrong target", "revision": "irrelevant",
    })
    assert response.status_code == 400
    assert document_store.read("grimoire.md") == "# Voice\nWrite plainly.\n"


@pytest.mark.parametrize("headers", [
    {"origin": "https://other.example"},
    {"sec-fetch-site": "cross-site"},
], ids=["cross-origin", "cross-site"])
def test_document_mutations_reject_cross_origin_requests(document_client, document_store, headers):
    revision = document_store.revision("master-resume.md")
    saved = document_client.post("/documents/save", data={
        "document_name": "master-resume.md", "text": "# Replaced", "revision": revision,
    }, headers=headers)
    uploaded = document_client.post("/documents/import", data={
        "document_name": "master-resume.md", "revision": revision,
    }, files={"file": ("resume.md", b"# Imported", "text/markdown")}, headers=headers)
    prepared = document_client.post("/documents/normalize", data={
        "document_name": "master-resume.md", "revision": revision, "text": "## Experience",
    }, headers=headers)
    accepted = document_client.post("/documents/normalize/accept", data={
        "document_name": "master-resume.md", "revision": revision, "text": "## Experience",
    }, headers=headers)
    assert saved.status_code == uploaded.status_code == prepared.status_code == accepted.status_code == 403
    assert document_store.read("master-resume.md") == "# Master\n- Original claim\n"


def test_document_mutations_wait_for_generation(document_client, document_store, document_runs):
    document_runs._status[SLUG] = RunStatus(state="running")
    revision = document_store.revision("master-resume.md")
    saved = document_client.post("/documents/save", data={
        "document_name": "master-resume.md", "text": "# Replaced", "revision": revision,
    })
    uploaded = document_client.post("/documents/import", data={
        "document_name": "master-resume.md", "revision": revision,
    }, files={"file": ("resume.md", b"# Imported", "text/markdown")})
    prepared = document_client.post("/documents/normalize", data={
        "document_name": "master-resume.md", "revision": revision, "text": "## Experience",
    })
    accepted = document_client.post("/documents/normalize/accept", data={
        "document_name": "master-resume.md", "revision": revision, "text": "## Experience",
    })
    assert saved.status_code == uploaded.status_code == prepared.status_code == accepted.status_code == 409
    assert "Wait for generation to finish" in saved.text
    assert document_store.read("master-resume.md") == "# Master\n- Original claim\n"


def test_entry_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Tailor your resume" in r.text
    assert "Staff Platform Engineer" in r.text


def test_start_redirects_to_outline(client):
    r = client.post("/start", data={"source": "reuse", "jd": "x"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/outline"


def test_outline_lists_units_and_frame(client):
    r = client.get("/outline")
    assert r.status_code == 200
    assert "Frame · Scale" in r.text
    for unit in get_application().units:
        assert unit.label in r.text


def test_curate_start_redirects_to_first_unit(client):
    r = client.get("/curate", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/curate/0"


def test_curate_renders_four_variants_with_evidence(client):
    r = client.get("/curate/0")
    assert r.status_code == 200
    assert "Line 1 of" in r.text
    assert r.text.count('name="variant_id"') == 4
    assert "Evidence" in r.text


def test_curate_shows_limited_evidence_note(client):
    units = get_application().units
    idx = next(i for i, u in enumerate(units) if u.grounding_note)
    r = client.get(f"/curate/{idx}")
    assert "Limited evidence" in r.text
    assert "The cited evidence does not state Kubernetes experience" in r.text
    assert "These variants stay within" not in r.text


@pytest.mark.parametrize("pick", [None, "cover-open-2"])
def test_curate_requires_a_line_choice_with_native_validation(client, pick):
    if pick:
        client.post("/curate/0", data={"variant_id": pick}, follow_redirects=False)
    html = client.get("/curate/0").text
    cards = _cards(html)
    assert 'aria-describedby="variant-choice-hint"' in html
    assert "Choose a line before continuing." in html
    for variant_id, card in cards.items():
        input_tag = card.split("<input", 1)[1].split(">", 1)[0]
        assert " required" in input_tag
        assert ("checked" in input_tag) == (variant_id == pick)


def _cards(html: str) -> dict[str, str]:
    """Each variant card's HTML on the curate page, keyed by its variant id, in page order."""
    stack = html.split('<div class="actions', 1)[0]
    cards = stack.split('<div class="variant">')[1:]
    return {card.split('value="', 1)[1].split('"', 1)[0]: card for card in cards}


def _page(variants: list[Variant], path: str) -> str:
    """One page rendered for an application holding a single unit with these variants."""
    unit = Unit(id="resume.northwind.billing.bullet_1", kind="resume_bullet", label="Billing bullet",
                context="Surface the migration.", variants=variants)
    app_data = Application(slug=SLUG, company="Globex", role="Staff Platform Engineer", jd_excerpt="x",
                           frame=Frame(name="Scale", rationale="why"), units=[unit], evidence=dict(EVIDENCE))

    class _StubRepo(FakeWorkspaceRepository):
        def load_application(self, slug: str) -> Application:
            return app_data

    stub = _StubRepo()
    gen = FakeGenerationPort()
    app = create_app(repo=stub, gen=gen, run_manager=RunManager(repo=stub, gen=gen, verifier=NoVerificationPort()), live=False)
    with TestClient(app) as c:
        r = c.get(path)
    assert r.status_code == 200
    return r.text


def test_curate_notes_a_flagged_variant_and_leaves_a_traced_one_unchanged():
    note = verify.note_for("adds_detail", ["12"])
    evidence = (EVIDENCE["billing-migration"],)

    def variants(traced_support: Support | None) -> list[Variant]:
        return [
            Variant(id="bullet#1", text="Cut invoicing to 2s.", evidence_items=evidence, support=traced_support),
            Variant(id="bullet#2", text="Cut invoicing to 2s for 12 teams.", evidence_items=evidence,
                    support=Support(verdict="adds_detail", note=note, unsourced_numbers=("12",))),
        ]

    cards = _cards(_page(variants(Support(verdict="traced")), "/curate/0"))

    assert list(cards) == ["bullet#1", "bullet#2"]
    flagged = cards["bullet#2"]
    foot = flagged.index('class="variant__foot"')
    assert foot < flagged.index(str(escape(note))) < flagged.index('<details class="trace" open>')

    traced = cards["bullet#1"]
    assert traced == _cards(_page(variants(None), "/curate/0"))["bullet#1"]
    assert "checked" not in traced.lower() and "verified" not in traced.lower()


def test_curate_notes_the_fixture_overreaches(client):
    units = get_application().units
    note = str(escape(verify.note_for("adds_detail", [])))
    for unit_id, flagged_id, clean_id in [
        ("cover-open", "cover-open-1", "cover-open-2"),
        ("bullet-kubernetes", "bullet-kubernetes-1", "bullet-kubernetes-2"),
    ]:
        idx = next(i for i, u in enumerate(units) if u.id == unit_id)
        cards = _cards(client.get(f"/curate/{idx}").text)
        assert list(cards) == [v.id for v in units[idx].variants]
        assert note in cards[flagged_id]
        assert note not in cards[clean_id]
    assert "the last three years" in _cards(client.get("/curate/0").text)["cover-open-1"]


def test_curate_out_of_range_goes_to_review(client):
    r = client.get("/curate/999", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/review"


def test_pick_rejects_variant_not_in_unit(client, repo):
    r = client.post("/curate/0", data={"variant_id": "not-a-real-id"}, follow_redirects=False)
    assert r.status_code == 422
    assert "cover-open" not in repo.get_picks(SLUG)  # nothing stored on rejection


def test_pick_out_of_range_idx_returns_404(client, repo):
    r = client.post("/curate/999", data={"variant_id": "cover-open-1"}, follow_redirects=False)
    assert r.status_code == 404
    assert repo.get_picks(SLUG) == {}


def test_pick_stores_selection_and_advances(client, repo):
    r = client.post("/curate/0", data={"variant_id": "cover-open-2"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/curate/1"
    assert repo.get_picks(SLUG)["cover-open"] == "cover-open-2"


def test_last_pick_advances_to_review(client):
    units = get_application().units
    last = len(units) - 1
    last_unit = units[last]
    page = client.get(f"/curate/{last}")
    assert "Review your picks" in page.text
    assert "Stitch the documents" not in page.text
    r = client.post(
        f"/curate/{last}",
        data={"variant_id": last_unit.variants[0].id},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/review"


def test_review_reflects_chosen_variant(client):
    client.post("/curate/0", data={"variant_id": "cover-open-4"}, follow_redirects=False)
    r = client.get("/review")
    assert r.status_code == 200
    assert "Forty seconds to two." in r.text  # text of cover-open-4
    assert "Style check" in r.text


def test_review_incomplete_banner_when_not_all_picked(client):
    r = client.get("/review")
    assert "haven’t chosen every line yet" in r.text


def test_review_complete_hides_incomplete_banner(client):
    units = get_application().units
    for idx, unit in enumerate(units):
        client.post(
            f"/curate/{idx}",
            data={"variant_id": unit.variants[0].id},
            follow_redirects=False,
        )
    r = client.get("/review")
    assert "haven’t chosen every line yet" not in r.text


SUPPORT_ROW_LABEL = "Claim check of picked lines"
EXPORT_LINK = '<a class="btn btn--primary" href="/export">'


def _support_row(html: str) -> str | None:
    """The review checklist row for the claim check, or None when the page has none."""
    rows = [row.split("</li>", 1)[0] for row in html.split('<li class="lint__row')[1:]]
    return next((row for row in rows if SUPPORT_ROW_LABEL in row), None)


@pytest.mark.parametrize(
    ("support", "state"),
    [
        pytest.param(Support(verdict="conflicts", note="Conflicts with your evidence"), "fail", id="flagged-pick-fails"),
        pytest.param(Support(verdict="traced"), "pass", id="unflagged-pick-passes"),
        pytest.param(Support(verdict="untraced"), "fail", id="untraced-pick-fails"),
        pytest.param(Support(verdict="unchecked"), "fail", id="failed-check-fails"),
        pytest.param(None, None, id="unchecked-pick-no-row"),
    ],
)
def test_review_support_row_follows_the_pick_and_never_blocks_export(support: Support | None, state: str | None):
    variant = Variant(id="bullet#1", text="Cut invoicing to 2s.", evidence_items=(EVIDENCE["billing-migration"],),
                      support=support)
    html = _page([variant], "/review")

    row = _support_row(html)
    if state is None:
        assert row is None
    else:
        assert row is not None and row.startswith(f' lint__row--{state}"')
    assert EXPORT_LINK in html
    assert "Every picked line traces to your evidence" not in html
    if support is not None and support.verdict == "untraced":
        assert row is not None and "Unverified citation" in row
    if support is not None and support.verdict == "unchecked":
        assert row is not None and "Couldn&#39;t check this line" in row


def test_review_names_each_flagged_pick_with_its_note(client):
    units = get_application().units
    picks = {"cover-open": "cover-open-1", "bullet-kubernetes": "bullet-kubernetes-1"}
    for idx, unit in enumerate(units):
        client.post(f"/curate/{idx}", data={"variant_id": picks.get(unit.id, unit.variants[1].id)})

    html = client.get("/review").text

    note = "Adds detail your evidence doesn&#39;t state"
    row = _support_row(html)
    assert row is not None and row.startswith(' lint__row--fail"')
    opening_note = f"Opening paragraph: {note}."
    kubernetes_note = f"Kubernetes bullet: {note}."
    assert opening_note in row and kubernetes_note in row
    assert row.index(opening_note) < row.index(kubernetes_note)
    assert "No current claim check" in row
    assert "Every sentence still traces to your evidence" not in html
    assert EXPORT_LINK in html


def test_review_unselected_unit_shows_first_variant(client):
    # Pin the documented fallback: an uncurated unit renders its variant[0].
    units = get_application().units
    bullet = next(u for u in units if u.kind == "resume_bullet")
    r = client.get("/review")  # nothing selected
    assert bullet.variants[0].text in r.text


def test_review_word_count_is_computed_not_hardcoded(client):
    # The old fixture hardcoded "312 words"; the count must reflect the real text.
    units = get_application().units
    cover = [u for u in units if u.kind == "cover_paragraph"]
    expected = sum(len(u.variants[0].text.split()) for u in cover)
    r = client.get("/review")
    assert "312 words" not in r.text
    assert f"{expected} words." in r.text


def test_every_variant_resolves_its_evidence(client):
    # Integrity sweep: every variant carries resolved evidence drawn from the pool.
    pool = get_application().evidence
    for unit in get_application().units:
        for v in unit.variants:
            traces = v.evidence()
            assert traces == list(v.evidence_items)
            assert all(pool.get(e.id) is e for e in traces)


def test_variant_builder_rejects_unknown_evidence_id():
    # The trust invariant now lives in the adapter that resolves ids, not the type.
    with pytest.raises(ValueError, match="unknown evidence"):
        _v("bad", "x", "does-not-exist")
    # sanity: a real id resolves fine
    real_id = next(iter(EVIDENCE))
    assert _v("ok", "x", real_id).evidence_items[0].id == real_id


def test_review_skips_zero_variant_unit_without_500(repo):
    # A unit that arrives with no variants must not crash review (it can't be indexed);
    # it is silently skipped, and the other units still render.
    from app.domain import Application, Frame, Unit, Variant

    empty_unit = Unit(
        id="resume.empty.bullet_1",
        kind="resume_bullet",
        label="Empty bullet",
        context="No variants were generated for this line.",
        variants=[],
    )
    full_unit = Unit(
        id="resume.full.bullet_1",
        kind="resume_bullet",
        label="Full bullet",
        context="A normal line.",
        variants=[Variant(id="resume.full.bullet_1#1", text="A real bullet.", evidence_items=())],
    )
    app_data = Application(
        slug=SLUG,
        company="Globex",
        role="Staff Platform Engineer",
        jd_excerpt="x",
        frame=Frame(name="Scale", rationale="why"),
        units=[empty_unit, full_unit],
    )

    class _StubRepo(FakeWorkspaceRepository):
        def load_application(self, slug: str) -> Application:
            return app_data

    stub = _StubRepo()
    gen = FakeGenerationPort()
    app = create_app(repo=stub, gen=gen, run_manager=RunManager(repo=stub, gen=gen, verifier=NoVerificationPort()), live=False)
    with TestClient(app) as c:
        r = c.get("/review")
    assert r.status_code == 200
    assert "A real bullet." in r.text


def test_curate_renders_zero_variant_unit_without_500(repo):
    # A zero-variant unit renders an empty radiogroup rather than crashing the curate screen.
    from app.domain import Application, Frame, Unit

    empty_unit = Unit(
        id="resume.empty.bullet_1",
        kind="resume_bullet",
        label="Empty bullet",
        context="No variants were generated for this line.",
        variants=[],
    )
    app_data = Application(
        slug=SLUG,
        company="Globex",
        role="Staff Platform Engineer",
        jd_excerpt="x",
        frame=Frame(name="Scale", rationale="why"),
        units=[empty_unit],
    )

    class _StubRepo(FakeWorkspaceRepository):
        def load_application(self, slug: str) -> Application:
            return app_data

    stub = _StubRepo()
    gen = FakeGenerationPort()
    app = create_app(repo=stub, gen=gen, run_manager=RunManager(repo=stub, gen=gen, verifier=NoVerificationPort()), live=False)
    with TestClient(app) as c:
        r = c.get("/curate/0")
    assert r.status_code == 200
    assert "Empty bullet" in r.text
    assert "data-continue disabled" in r.text
    assert "No variants are available for this line." in r.text


def test_export_renders(client):
    r = client.get("/export")
    assert r.status_code == 200
    assert "pandoc" in r.text
    assert "The bundled sample does not create downloadable files." in r.text
    assert 'href="#"' not in r.text
    assert "/export/download/" not in r.text


def test_fixture_download_returns_not_found(client):
    response = client.get("/export/download/resume.md")
    assert response.status_code == 404


def test_reset_clears_selections(client, repo):
    client.post("/curate/0", data={"variant_id": "cover-open-1"}, follow_redirects=False)
    assert repo.get_picks(SLUG)
    r = client.post("/reset", follow_redirects=False)
    assert r.status_code == 303
    assert repo.get_picks(SLUG) == {}


def test_entry_is_honest_and_has_no_dead_upload(client):
    # Fake config: the Start screen states the bundled sample, with no fabricated
    # "last updated"/count copy and no non-functional upload affordance.
    r = client.get("/")
    assert "Using the bundled sample resume." in r.text
    assert "2 days ago" not in r.text
    assert "7 evidence entries" not in r.text
    assert "Upload a different one" not in r.text
    assert "Live generation sends your source text to Claude." in r.text
    assert "Optional claim checks send claims and evidence to TypeSafe." in r.text
    assert "Review each claim before using it." in r.text
    assert "Compare each line with its cited evidence." in r.text
    assert "Nothing is sent anywhere" not in r.text
    assert "never invents" not in r.text
    assert "Every claim traces back" not in r.text
