"""Download manager: queue, retries, resume, MD5, skipped/cancelled rows.
Mirrors the Go version's manager_test.go."""
import hashlib
import threading
import time
from pathlib import Path

import download_manager
from download_manager import AUTOMATIC_RETRIES, DownloadManager, State
from tests.conftest import reply

CONTENT = b"Nexus archive bytes. " * 1000
CONTENT_MD5 = hashlib.md5(CONTENT).hexdigest()


def wait_finished(item, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if item.state in download_manager.FINISHED:
            return item
        time.sleep(0.01)
    raise AssertionError(f"{item.file_name} did not finish: {item.state}")


def test_queue_limits_parallel_downloads(http_server, tmp_path):
    lock = threading.Lock()
    state = {"in_flight": 0, "peak": 0}
    release = threading.Event()

    def handler(req):
        with lock:
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
        release.wait(10)
        reply(req, body=CONTENT)
        with lock:
            state["in_flight"] -= 1

    srv, url = http_server(handler)
    m = DownloadManager(None)
    m.set_max_parallel(2)
    items = [m.add(n, url, str(tmp_path), n, 0) for n in ("a.7z", "b.7z", "c.7z", "d.7z")]
    time.sleep(0.3)
    assert items[3].state == State.QUEUED
    release.set()
    for it in items:
        assert wait_finished(it).state == State.DONE
    assert state["peak"] == 2


def test_cancel_while_queued(http_server, tmp_path):
    release = threading.Event()
    srv, url = http_server(lambda req: (release.wait(10), reply(req, body=CONTENT)))
    m = DownloadManager(None)
    first = m.add("a", url, str(tmp_path), "a.7z", 0)
    second = m.add("b", url, str(tmp_path), "b.7z", 0)
    m.cancel("b")
    release.set()
    wait_finished(first)
    time.sleep(0.1)
    assert second.state == State.CANCELLED
    assert not (tmp_path / "b.7z").exists()


def test_automatic_retries(http_server, tmp_path):
    """Failed downloads are retried AUTOMATIC_RETRIES times (MO2 behaviour)."""
    def handler(req):
        if len(req.server.requests) <= AUTOMATIC_RETRIES:
            reply(req, 502)
        else:
            reply(req, body=CONTENT)
    srv, url = http_server(handler)
    item = wait_finished(DownloadManager(None).add("a", url, str(tmp_path), "a.7z", 0))
    assert item.state == State.DONE, item.error
    assert len(srv.requests) == AUTOMATIC_RETRIES + 1


def test_retries_exhausted(http_server, tmp_path):
    srv, url = http_server(lambda req: reply(req, 502))
    item = wait_finished(DownloadManager(None).add("a", url, str(tmp_path), "a.7z", 0))
    assert item.state == State.ERROR
    assert len(srv.requests) == AUTOMATIC_RETRIES + 1


def test_resume_ignored_range_restarts(http_server, tmp_path):
    """A resume that gets 200 instead of 206 must replace the partial file,
    not append to it."""
    srv, url = http_server(lambda req: reply(req, body=CONTENT))  # ignores Range
    (tmp_path / "a.7z.part").write_bytes(b"stale partial")
    item = wait_finished(DownloadManager(None).add("a", url, str(tmp_path), "a.7z", 0, CONTENT_MD5))
    assert item.state == State.DONE, item.error
    assert (tmp_path / "a.7z").read_bytes() == CONTENT
    assert srv.requests[0].headers["Range"] == "bytes=13-"


def test_resume_416_keeps_complete_partial(http_server, tmp_path):
    """416 means the partial file is already complete: it becomes the file."""
    srv, url = http_server(lambda req: reply(req, 416))
    (tmp_path / "a.7z.part").write_bytes(CONTENT)
    item = wait_finished(DownloadManager(None).add("a", url, str(tmp_path), "a.7z", 0, CONTENT_MD5))
    assert item.state == State.DONE, item.error
    assert (tmp_path / "a.7z").read_bytes() == CONTENT
    assert not (tmp_path / "a.7z.part").exists()


def test_md5_verified(http_server, tmp_path):
    srv, url = http_server(lambda req: reply(req, body=CONTENT))
    m = DownloadManager(None)
    m.set_max_parallel(2)
    ok = m.add("ok", url, str(tmp_path), "ok.7z", 0, CONTENT_MD5.upper())
    bad = m.add("bad", url, str(tmp_path), "bad.7z", 0, "0" * 32)
    assert wait_finished(ok).state == State.DONE
    wait_finished(bad)
    assert bad.state == State.ERROR and "MD5 mismatch" in bad.error
    assert (tmp_path / "bad.7z").exists(), "mismatched file should be kept"


def test_skipped_item(tmp_path):
    """Skipped rows are cleared like finished ones, and deleting one never
    touches the file, which was already there before."""
    existing = tmp_path / "Existing Mod-1234-1-0-1700000000.7z"
    existing.write_bytes(CONTENT)
    m = DownloadManager(None)
    item = m.add_skipped("skip-1", str(tmp_path), existing.name, len(CONTENT))
    p = item.progress()
    assert p["status"] == "Skipped" and p["doneBytes"] == p["totalBytes"]
    m.delete("skip-1")
    assert existing.exists()
    assert m.items() == []
    m.add_skipped("skip-2", str(tmp_path), existing.name, len(CONTENT))
    m.clear_completed()
    assert m.items() == []


def blocking_server(http_server):
    """Holds /hold until released; records request paths in order."""
    release = threading.Event()

    def handler(req):
        if req.path == "/hold":
            release.wait(10)
        reply(req, body=CONTENT)
    srv, url = http_server(handler)
    return srv, url, release


def test_cancel_queued(http_server, tmp_path):
    srv, url, release = blocking_server(http_server)
    m = DownloadManager(None)
    running = m.add("run", url + "/hold", str(tmp_path), "run.7z", 0)
    queued = [m.add(n, f"{url}/{n}", str(tmp_path), n, 0) for n in ("a.7z", "b.7z", "c.7z")]
    time.sleep(0.2)
    assert m.cancel_queued() == 3
    release.set()
    assert wait_finished(running).state == State.DONE
    time.sleep(0.1)
    for it in queued:
        assert it.state == State.CANCELLED
        assert not (tmp_path / it.file_name).exists()


def test_delete_cancelled_queued_keeps_files(http_server, tmp_path):
    """Deleting an item cancelled before it started must not touch a file of
    the same name that was already there."""
    srv, url, release = blocking_server(http_server)
    existing = tmp_path / "b.7z"
    existing.write_bytes(b"user's file")
    m = DownloadManager(None)
    running = m.add("run", url + "/hold", str(tmp_path), "run.7z", 0)
    m.add("b", url + "/b", str(tmp_path), "b.7z", 0)
    m.cancel("b")
    m.delete("b")
    assert existing.read_bytes() == b"user's file"
    release.set()
    wait_finished(running)
