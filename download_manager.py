"""Download manager with streaming, queueing, retries and pause/resume/cancel."""
import hashlib
import os
import time
import threading
from enum import Enum
from pathlib import Path
from typing import Callable

import requests

# How often a failed download is retried, resuming from the partial file
# (MO2: DownloadManager::AUTOMATIC_RETRIES = 3).
AUTOMATIC_RETRIES = 3

# Cap for set_max_parallel (Vortex's "Download Threads" setting allows 1-10).
MAX_PARALLEL_LIMIT = 10


class State(Enum):
    QUEUED = "Queued"
    DOWNLOADING = "Downloading"
    PAUSED = "Paused"
    DONE = "Done"
    ERROR = "Error"
    CANCELLED = "Cancelled"
    SKIPPED = "Skipped"  # already in the target folder; nothing downloaded
    WAITING = "Waiting"  # a link waiting for Nexus to answer; not a download yet


FINISHED = (State.DONE, State.ERROR, State.CANCELLED, State.SKIPPED)


class DownloadItem:
    def __init__(self, id: str, url: str, dest_dir: str, file_name: str, total_bytes: int,
                 expected_md5: str = ""):
        self.id = id
        self.url = url
        self.dest_dir = dest_dir
        self.file_name = file_name
        self.state = State.QUEUED
        self.total_bytes = total_bytes
        self.done_bytes = 0
        self.speed = 0.0
        self.error = ""
        # Checked against the finished file; a mismatch is an error and the
        # file is kept.
        self.expected_md5 = expected_md5.lower()
        self.started = False  # its download thread has been scheduled
        self._lock = threading.Lock()
        self._pause_event = threading.Event()
        self._pause_event.set()  # starts unpaused
        self._cancelled = False

    def progress(self) -> dict:
        with self._lock:
            total = self.total_bytes or 0
            return {
                "id": self.id,
                "fileName": self.file_name,
                "status": self.state.value,
                "percent": int(self.done_bytes * 100 / total) if total > 0 else 0,
                "speed": _format_speed(self.speed),
                "size": _format_size(total),
                "doneBytes": self.done_bytes,
                "totalBytes": total,
                "error": self.error,
            }


class DownloadManager:
    """Coordinates downloads. At most max_parallel run at once; the rest wait
    as Queued, in the order they were added."""

    def __init__(self, on_change: Callable[[], None]):
        self._items: list[DownloadItem] = []
        self._lock = threading.Lock()
        self._on_change = on_change
        self._max_parallel = 1
        self._active = 0

    def items(self) -> list[DownloadItem]:
        with self._lock:
            return list(self._items)

    def set_max_parallel(self, n: int) -> None:
        """How many downloads may run at once, clamped to 1..MAX_PARALLEL_LIMIT
        (Vortex: 1 by default, and always 1 without Premium)."""
        with self._lock:
            self._max_parallel = max(1, min(n, MAX_PARALLEL_LIMIT))
        self._start_queued()

    def add(self, id: str, url: str, dest_dir: str, file_name: str, total_bytes: int,
            expected_md5: str = "") -> DownloadItem:
        """Queue a download; it starts when a slot is free."""
        item = DownloadItem(id, url, dest_dir, file_name, total_bytes, expected_md5)
        with self._lock:
            self._items.append(item)
        self._notify()
        self._start_queued()
        return item

    def add_skipped(self, id: str, dest_dir: str, file_name: str, size: int) -> DownloadItem:
        """List a file that was not downloaded because it is already in
        dest_dir under file_name."""
        item = DownloadItem(id, "", dest_dir, file_name, size)
        item.state = State.SKIPPED
        item.done_bytes = size
        item.started = True
        with self._lock:
            self._items.append(item)
        self._notify()
        return item

    def add_waiting(self, id: str, label: str) -> DownloadItem:
        """List a link that is still waiting for Nexus to answer, so a slow API
        shows up in the list. The caller removes it once Nexus answers; cancel
        marks it Cancelled, and the caller then drops the link."""
        item = DownloadItem(id, "", "", label, 0)
        item.state = State.WAITING
        with self._lock:
            self._items.append(item)
        self._notify()
        return item

    def add_cancelled(self, dest_dir: str, rows: list[tuple[str, str]]) -> None:
        """List downloads that were cancelled before they were queued
        (collection mods not yet reached when "Cancel all queued" was used),
        given as (id, name) pairs. All rows are added at once with a single
        update: each update re-renders the whole list and waits for the page,
        so one per row made them trickle in after "Clear All Completed"."""
        items = []
        for id, name in rows:
            item = DownloadItem(id, "", dest_dir, name, 0)
            item.state = State.CANCELLED
            item._cancelled = True
            items.append(item)
        if not items:
            return
        with self._lock:
            self._items.extend(items)
        self._notify()

    def _start_queued(self) -> None:
        """Start queued items, in the order they were added, while there are
        free slots."""
        start = []
        with self._lock:
            for item in self._items:
                if self._active >= self._max_parallel:
                    break
                with item._lock:
                    if item.state == State.QUEUED and not item.started:
                        item.started = True
                        self._active += 1
                        start.append(item)
        for item in start:
            threading.Thread(target=self._run, args=(item,), daemon=True).start()

    def pause(self, id: str):
        item = self._find(id)
        if not item:
            return
        with item._lock:
            if item.state == State.DOWNLOADING:
                item.state = State.PAUSED
                item._pause_event.clear()
        self._notify()

    def resume(self, id: str):
        item = self._find(id)
        if not item:
            return
        with item._lock:
            if item.state == State.PAUSED:
                item.state = State.DOWNLOADING
                item._pause_event.set()
        self._notify()

    def cancel(self, id: str):
        item = self._find(id)
        if not item:
            return
        with item._lock:
            item.state = State.CANCELLED
            item._cancelled = True
            item._pause_event.set()  # unblock if paused
        self._notify()

    def cancel_queued(self) -> int:
        """Cancel every download still waiting to start; return how many.
        Running and paused downloads are untouched."""
        n = 0
        for item in self.items():
            with item._lock:
                if item.state == State.QUEUED and not item.started:
                    item.state = State.CANCELLED
                    item._cancelled = True
                    n += 1
        if n:
            self._notify()
        return n

    def remove(self, id: str):
        self.cancel(id)
        with self._lock:
            self._items = [i for i in self._items if i.id != id]
        self._notify()

    def delete(self, id: str):
        """Cancel, remove from the list, and delete the item's files."""
        item = self._find(id)
        if not item:
            return
        # A skipped item's file predates it, and an item cancelled before it
        # started never wrote anything: never delete files for either.
        with item._lock:
            owns_files = item.state != State.SKIPPED and item.started
        self.cancel(id)
        with self._lock:
            self._items = [i for i in self._items if i.id != id]
        if owns_files:
            dest = Path(item.dest_dir) / item.file_name
            for p in (dest, dest.with_suffix(dest.suffix + ".part")):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
        self._notify()

    def clear_completed(self):
        with self._lock:
            self._items = [i for i in self._items if i.state not in FINISHED]
        self._notify()

    def _find(self, id: str) -> DownloadItem | None:
        with self._lock:
            for item in self._items:
                if item.id == id:
                    return item
        return None

    def _notify(self):
        if self._on_change:
            self._on_change()

    def _run(self, item: DownloadItem):
        try:
            self._run_item(item)
        finally:
            with self._lock:
                self._active -= 1
            self._start_queued()

    def _run_item(self, item: DownloadItem):
        with item._lock:
            if item.state != State.QUEUED:  # cancelled while queued
                return
            item.state = State.DOWNLOADING
        self._notify()

        dest = Path(item.dest_dir) / item.file_name
        part_path = dest.with_suffix(dest.suffix + ".part")

        error = None
        for attempt in range(AUTOMATIC_RETRIES + 1):
            try:
                self._download(item, part_path, dest)
                error = None
                break
            except Exception as e:  # noqa: BLE001 - any failure is retried
                error = e
                if item._cancelled:
                    break

        if error is None and item.expected_md5:
            try:
                got = file_md5(dest)
            except OSError as e:
                error = RuntimeError(f"MD5 check: {e}")
            else:
                if got != item.expected_md5:
                    with item._lock:
                        item.state = State.ERROR
                        item.error = (f"MD5 mismatch: file {got}, expected "
                                      f"{item.expected_md5} (file kept)")
                    self._notify()
                    return

        with item._lock:
            if error is None:
                item.state = State.DONE
                item.speed = 0
            elif item._cancelled:
                item.state = State.CANCELLED
            else:
                item.state = State.ERROR
                item.error = str(error)
        if error is not None:
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
        self._notify()

    def _download(self, item: DownloadItem, part_path: Path, dest: Path):
        start_byte = 0
        if part_path.exists():
            start_byte = part_path.stat().st_size

        headers = {}
        if start_byte > 0:
            headers["Range"] = f"bytes={start_byte}-"
            with item._lock:
                item.done_bytes = start_byte

        resp = requests.get(item.url, headers=headers, stream=True, timeout=60)

        if resp.status_code == 416:
            # Range starts at the end: the partial file is already complete
            resp.close()
            if dest.exists():
                dest.unlink()
            part_path.rename(dest)
            return

        if resp.status_code not in (200, 206):
            resp.close()
            raise RuntimeError(f"HTTP {resp.status_code}")

        mode = "ab"
        if start_byte > 0 and resp.status_code == 200:
            # the server ignored Range and is sending the whole file: start over
            mode = "wb"
            start_byte = 0
            with item._lock:
                item.done_bytes = 0

        if item.total_bytes == 0:
            cl = resp.headers.get("Content-Length")
            if cl:
                with item._lock:
                    item.total_bytes = int(cl) + start_byte

        os.makedirs(item.dest_dir, exist_ok=True)
        with open(part_path, mode) as f:
            last_report = time.time()
            bytes_since = 0

            for chunk in resp.iter_content(chunk_size=262144):
                # Check pause
                item._pause_event.wait()

                # Check cancel
                if item._cancelled:
                    resp.close()
                    raise RuntimeError("cancelled")

                if chunk:
                    f.write(chunk)
                    n = len(chunk)
                    bytes_since += n
                    with item._lock:
                        item.done_bytes += n

                    elapsed = time.time() - last_report
                    if elapsed >= 0.5:
                        with item._lock:
                            item.speed = bytes_since / elapsed
                        bytes_since = 0
                        last_report = time.time()
                        self._notify()

        # Rename .part to final
        if dest.exists():
            dest.unlink()
        part_path.rename(dest)


def file_md5(path) -> str:
    """Lowercase hex MD5 of the file at path."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


_ILLEGAL_NAME_CHARS = str.maketrans({c: "_" for c in '<>:"/\\|?*'})


def safe_filename(name: str) -> str:
    """Nexus's file_name with the characters Windows forbids in file names
    replaced by "_". Downloads otherwise keep Nexus's own name."""
    return name.translate(_ILLEGAL_NAME_CHARS)


def _format_speed(bps: float) -> str:
    if bps <= 0:
        return "—"
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    return f"{bps / 1024:.0f} KB/s"


def _format_size(b: int) -> str:
    if b <= 0:
        return "—"
    if b >= 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024 * 1024):.1f} GB"
    if b >= 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / 1024:.0f} KB"
