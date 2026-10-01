"""Collection pieces: link parsing, already-downloaded detection, cancelling
unqueued mods, and stopping at the first 403 (Premium needed)."""
import pytest

import api as api_module
from api import Api, CollectionRun, ExistingFiles, PendingMod
from config import Config
from download_manager import DownloadManager, State
from nexus_client import NexusClient, RevisionInfo
from nxm_parser import is_collection_url, parse_collection
from tests.conftest import reply


def test_parse_collection():
    link = parse_collection("nxm://skyrimspecialedition/collections/xk05aw/revisions/325")
    assert (link.game_domain, link.collection_slug, link.revision_number) == (
        "skyrimspecialedition", "xk05aw", 325)
    assert is_collection_url("nxm://skyrimspecialedition/collections/xk05aw/revisions/325")
    assert not is_collection_url("nxm://skyrimspecialedition/mods/30379/files/795992")
    with pytest.raises(ValueError, match="latest"):
        parse_collection("nxm://skyrimspecialedition/collections/xk05aw/revisions/latest")


def test_existing_files(tmp_path):
    # md5("hello") = 5d41402abc4b2a76b9719d911017c592
    name = "Some Mod-1234-1-0-1700000000.7z"
    (tmp_path / name).write_bytes(b"hello")
    (tmp_path / "sub").mkdir()
    e = ExistingFiles(str(tmp_path))
    assert e.find(5, "5d41402abc4b2a76b9719d911017c592") == name
    assert e.find(5, "5D41402ABC4B2A76B9719D911017C592") == name  # case-insensitive
    assert e.find(5, "0" * 32) == ""
    assert e.find(6, "5d41402abc4b2a76b9719d911017c592") == ""  # size must match
    assert e.find(5, "") == ""  # no MD5 (e.g. bundled)
    assert e.find(0, "5d41402abc4b2a76b9719d911017c592") == ""


def make_api(tmp_path, monkeypatch):
    errors = []
    a = Api(Config(api_key="test-key", download_dir=str(tmp_path)), [])
    monkeypatch.setattr(a, "_emit_error", errors.append)
    return a, errors


def pending(n):
    return [PendingMod("skyrimspecialedition", 100 + i, 200 + i, f"Mod {i} {i}.0", "")
            for i in range(n)]


def test_cancel_all_queued_lists_unqueued_mods(tmp_path, monkeypatch):
    """"Cancel all queued" lists every collection mod not queued yet as a
    Cancelled row and counts it."""
    a, _ = make_api(tmp_path, monkeypatch)
    run = CollectionRun(dest_dir=str(tmp_path), todo=pending(5), next=2)
    a._runs[id(run)] = run
    assert a.cancel_all_queued() == 3
    rows = a._dl_mgr.items()
    assert [r.file_name for r in rows] == ["Mod 2 2.0", "Mod 3 3.0", "Mod 4 4.0"]
    assert all(r.state == State.CANCELLED for r in rows)
    assert a.cancel_all_queued() == 0
    assert not run.skip(), "the queuing loop must stop after a cancel"
    a._dl_mgr.clear_completed()
    assert a._dl_mgr.items() == []


def test_collection_stops_at_first_403(http_server, tmp_path, monkeypatch):
    """A free account's keyless download_link gets 403: one message, and no
    further mods are tried."""
    srv, url = http_server(lambda req: reply(req, 403, body=b'{"message":"forbidden"}'))
    a, errors = make_api(tmp_path, monkeypatch)
    client = NexusClient("test-key")
    client.host = url
    rev = RevisionInfo(1, 2, "", "Essential Mods for Skyrim", "xk05aw", "skyrimspecialedition")
    run = CollectionRun(dest_dir=str(tmp_path), todo=pending(5))
    a._queue_collection_mods(client, rev, {}, run)
    assert len(srv.requests) == 1
    assert errors == [f'Stopped queuing "Essential Mods for Skyrim": {api_module.PREMIUM_NEEDED}']
    assert a._dl_mgr.items() == []


def test_collection_continues_past_other_errors(http_server, tmp_path, monkeypatch):
    """Errors other than 403 skip that mod and go on, as before."""
    srv, url = http_server(lambda req: reply(req, 404, body=b'{"message":"not found"}'))
    a, errors = make_api(tmp_path, monkeypatch)
    client = NexusClient("test-key")
    client.host = url
    rev = RevisionInfo(1, 2, "", "C", "c", "skyrimspecialedition")
    run = CollectionRun(dest_dir=str(tmp_path), todo=pending(3))
    a._queue_collection_mods(client, rev, {}, run)
    assert len(srv.requests) == 3
    assert len(errors) == 3 and all("Failed to get download link" in e for e in errors)
