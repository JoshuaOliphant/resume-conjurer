# ABOUTME: Proves the synthetic MCP panel uses existing picks and read-only opening semantics.
# ABOUTME: Exercises reopen, stale writers, malformed input, metadata and atomic write failures.
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app import chatgpt_demo as demo


@pytest.fixture
def store(tmp_path):
    value = demo.FixtureStore(tmp_path / "synthetic")
    value.initialize()
    return value


def test_read_does_not_initialize(tmp_path):
    value = demo.FixtureStore(tmp_path / "absent")
    with pytest.raises(FileNotFoundError):
        value.read()
    assert not value.path.parent.exists()


def test_persistence_reopen_and_plugin_interoperability(store):
    from stitch import collect_picks, parse_variants_md

    before = store.path.read_bytes()
    current = store.read()
    assert len(current["variants"]) == 4
    assert current["selected_variant"] is None
    assert all(v["support"] == "unchecked" for v in current["variants"])
    assert store.path.read_bytes() == before
    saved = store.pick(demo.UNIT_ID, 3, current["revision"])
    assert saved["status"] == "saved"
    assert saved["selected_variant"] == 3
    restarted = demo.FixtureStore(store.path.parent)
    restarted.initialize()
    assert restarted.read()["selected_variant"] == 3
    _, picks = collect_picks(parse_variants_md(store.path.read_text()))
    assert picks == [(demo.UNIT_ID, current["variants"][2]["text"])]
    assert set(p.name for p in store.path.parent.iterdir()) == {"variants.md"}
    again = store.pick(demo.UNIT_ID, 3, saved["revision"])
    assert again == saved


def test_stale_and_concurrent_choices_do_not_overwrite(store):
    revision = store.read()["revision"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda n: store.pick(demo.UNIT_ID, n, revision), [1, 2]))
    assert sorted(r["status"] for r in results) == ["conflict", "saved"]
    saved = next(r for r in results if r["status"] == "saved")
    conflict = next(r for r in results if r["status"] == "conflict")
    assert store.read()["selected_variant"] == saved["selected_variant"]
    assert conflict["revision"] == saved["revision"]


@pytest.mark.parametrize("unit,n", [("../other", 1), (demo.UNIT_ID, 5), (demo.UNIT_ID, True)])
def test_invalid_choice_never_writes(store, unit, n):
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="Unknown"):
        store.pick(unit, n, store.read()["revision"])
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("content,match", [("", "one synthetic"),
    (demo.FIXTURE.replace(demo.UNIT_ID, "resume.other"), "one synthetic"),
    (demo.FIXTURE.replace("### Variant 4", "### Variant 5"), "four synthetic"),
    (demo.FIXTURE.replace("- [ ]", "- [x]"), "4 picks")])
def test_malformed_existing_workspace_is_not_reset(tmp_path, content, match):
    path = tmp_path / "variants.md"
    path.write_text(content)
    with pytest.raises(ValueError, match=match):
        demo.FixtureStore(tmp_path).initialize()
    assert path.read_text() == content


def test_failed_replace_preserves_document_and_removes_temp(store, monkeypatch):
    before = store.path.read_bytes()
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(demo.os, "replace", fail)
    with pytest.raises(OSError):
        store.pick(demo.UNIT_ID, 1, store.read()["revision"])
    assert store.path.read_bytes() == before
    assert list(store.path.parent.iterdir()) == [store.path]


def test_mcp_tools_resources_and_bounded_schema(store):
    async def run():
        server = demo.create_server(store)
        tools = {t.name: t for t in await server.list_tools()}
        assert set(tools) == {"open_curation_demo", "set_variant_pick"}
        opening = tools["open_curation_demo"]
        assert opening.annotations is not None and opening.meta is not None
        assert opening.outputSchema is not None
        assert opening.annotations.readOnlyHint is True
        assert opening.meta["openai/ui"]["entrypoints"] == [{"type": "thread"}]
        assert opening.meta["ui"]["resourceUri"] == demo.RESOURCE_URI
        mutation = tools["set_variant_pick"]
        assert mutation.meta is not None and mutation.annotations is not None
        assert mutation.meta["ui"]["visibility"] == ["app"]
        assert mutation.annotations.readOnlyHint is False
        assert set(mutation.inputSchema["properties"]) == {"unit_id", "variant_id", "expected_revision"}
        resources = await server.list_resources()
        assert len(resources) == 1
        assert resources[0].mimeType == "text/html;profile=mcp-app"
        contents = list(await server.read_resource(demo.RESOURCE_URI))
        assert contents[0].meta is not None
        assert isinstance(contents[0].content, str)
        assert contents[0].meta["ui"]["csp"]["connectDomains"] == []
        assert '<html lang="en">' in contents[0].content
        before = store.path.read_bytes()
        async def call(name, arguments):
            result = await server.call_tool(name, arguments)
            assert isinstance(result, tuple)
            return result[1]
        current = await call("open_curation_demo", {})
        assert store.path.read_bytes() == before
        saved = await call("set_variant_pick", {
            "unit_id": demo.UNIT_ID, "variant_id": 2, "expected_revision": current["revision"]})
        assert saved["selected_variant"] == 2
        stale = await call("set_variant_pick", {
            "unit_id": demo.UNIT_ID, "variant_id": 1, "expected_revision": current["revision"]})
        assert stale["status"] == "conflict"
        for args in [{"unit_id": "../../real", "variant_id": 1, "expected_revision": saved["revision"]},
                     {"unit_id": demo.UNIT_ID, "variant_id": True, "expected_revision": saved["revision"]},
                     {"unit_id": demo.UNIT_ID, "variant_id": 5, "expected_revision": saved["revision"]},
                     {"unit_id": demo.UNIT_ID, "variant_id": 1, "expected_revision": "bad"}]:
            with pytest.raises(ToolError):
                await server.call_tool("set_variant_pick", args)
        assert store.read()["selected_variant"] == 2
    asyncio.run(run())


def test_cli_requires_explicit_scratch_and_runs_loopback(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        demo.main([])
    calls = []
    class Server:
        def run(self, **kwargs):
            calls.append(kwargs)
    def create(store):
        assert store.path == tmp_path / "variants.md"
        assert store.read()["selected_variant"] is None
        return Server()
    monkeypatch.setattr(demo, "create_server", create)
    demo.main(["--scratch-dir", str(tmp_path)])
    assert calls == [{"transport": "streamable-http"}]


def test_reject_missing_pick_line_or_modified_fixture(store):
    for text in [demo.FIXTURE.replace("- [ ] Pick", ""), demo.FIXTURE.replace("Built a Python", "Real private data")]:
        store.path.write_text(text)
        with pytest.raises(ValueError, match="unchanged synthetic"):
            store.read()


def test_streamable_http_protocol(store):
    """Exercise the actual JSON-RPC transport without opening a network socket."""
    from starlette.testclient import TestClient

    server = demo.create_server(store)
    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:8401") as client:
        headers = {"Accept": "application/json, text/event-stream"}
        def rpc(method, params=None):
            response = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
            assert response.status_code == 200, response.text
            return response.json()["result"]
        initialized = rpc("initialize", {"protocolVersion": "2025-11-25",
            "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
        assert initialized["serverInfo"]["name"] == "Conjurer synthetic curation"
        tools = rpc("tools/list")["tools"]
        assert tools[0]["outputSchema"]["type"] == "object"
        opened = rpc("tools/call", {"name": "open_curation_demo", "arguments": {}})
        snapshot = opened["structuredContent"]
        assert snapshot["selected_variant"] is None
        resource = rpc("resources/read", {"uri": demo.RESOURCE_URI})
        assert resource["contents"][0]["mimeType"] == "text/html;profile=mcp-app"
        assert resource["contents"][0]["_meta"]["ui"]["csp"]["connectDomains"] == []
        saved = rpc("tools/call", {"name": "set_variant_pick", "arguments": {
            "unit_id": demo.UNIT_ID, "variant_id": 3, "expected_revision": snapshot["revision"]}})
        assert saved["structuredContent"]["selected_variant"] == 3
        assert rpc("tools/call", {"name": "open_curation_demo", "arguments": {}})["structuredContent"]["selected_variant"] == 3


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o644])
def test_pick_preserves_original_permissions(store, mode):
    store.path.chmod(mode)
    revision = store.read()["revision"]
    store.pick(demo.UNIT_ID, 2, revision)
    assert store.path.stat().st_mode & 0o777 == mode


def test_exact_replay_has_no_additional_effect_and_keeps_stale_protection(store):
    revision = store.read()["revision"]
    saved = store.pick(demo.UNIT_ID, 2, revision)
    before = store.path.stat()
    repeated = store.pick(demo.UNIT_ID, 2, revision)
    assert repeated["status"] == "conflict"
    assert repeated["revision"] == saved["revision"]
    assert repeated["selected_variant"] == 2
    assert store.path.stat().st_mtime_ns == before.st_mtime_ns
    assert store.path.stat().st_ino == before.st_ino
    unchanged = store.pick(demo.UNIT_ID, 2, saved["revision"])
    assert unchanged["status"] == "saved"
    assert store.path.stat().st_ino == before.st_ino
    store.pick(demo.UNIT_ID, 3, saved["revision"])
    assert store.pick(demo.UNIT_ID, 2, revision)["status"] == "conflict"
    assert store.read()["selected_variant"] == 3


def test_permission_copy_failure_does_not_replace_document(store, monkeypatch):
    before = store.path.read_bytes()
    def fail(*args):
        raise OSError("cannot preserve permissions")
    monkeypatch.setattr(demo.os, "chmod", fail)
    with pytest.raises(OSError, match="preserve permissions"):
        store.pick(demo.UNIT_ID, 2, store.read()["revision"])
    assert store.path.read_bytes() == before
    assert list(store.path.parent.iterdir()) == [store.path]
