"""Download manager with streaming, pause/resume/cancel support."""
import os
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

import requests


class State(Enum):
    QUEUED = "Queued"
    DOWNLOADING = "Downloading"
    PAUSED = "Paused"
    DONE = "Done"
    ERROR = "Error"
    CANCELLED = "Cancelled"


class DownloadItem:
    def __init__(self, id: str, url: str, dest_dir: str, file_name: str, total_bytes: int):
        self.id = id
        self.url = url
        self.dest_dir = dest_dir
        self.file_name = file_name
        self.state = State.QUEUED
        self.total_bytes = total_bytes
        self.done_bytes = 0
        self.speed = 0.0
        self.error = ""
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
    def __init__(self, on_change: Callable[[], None]):
        self._items: list[DownloadItem] = []
        self._lock = threading.Lock()
        self._on_change = on_change

    def items(self) -> list[DownloadItem]:
        with self._lock:
            return list(self._items)

    def add(self, id: str, url: str, dest_dir: str, file_name: str, total_bytes: int) -> DownloadItem:
        item = DownloadItem(id, url, dest_dir, file_name, total_bytes)
        with self._lock:
            self._items.append(item)
        threading.Thread(target=self._run, args=(item,), daemon=True).start()
        return item

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

    def remove(self, id: str):
        self.cancel(id)
        with self._lock:
            self._items = [i for i in self._items if i.id != id]
        self._notify()

    def delete(self, id: str):
        item = self._find(id)
        if not item:
            return
        self.cancel(id)
        with self._lock:
            self._items = [i for i in self._items if i.id != id]
        dest = Path(item.dest_dir) / item.file_name
        for p in (dest, dest.with_suffix(dest.suffix + ".part")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        self._notify()

    def clear_completed(self):
        with self._lock:
            self._items = [i for i in self._items if i.state in (State.QUEUED, State.DOWNLOADING, State.PAUSED)]
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
        with item._lock:
            item.state = State.DOWNLOADING
        self._notify()

        dest = Path(item.dest_dir) / item.file_name
        part_path = dest.with_suffix(dest.suffix + ".part")

        try:
            self._download(item, part_path, dest)
        except Exception as e:
            with item._lock:
                if item._cancelled:
                    item.state = State.CANCELLED
                else:
                    item.state = State.ERROR
                    item.error = str(e)
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
            # Already complete
            part_path.unlink(missing_ok=True)
            with item._lock:
                item.state = State.DONE
            return

        if resp.status_code not in (200, 206):
            raise RuntimeError(f"HTTP {resp.status_code}")

        if item.total_bytes == 0:
            cl = resp.headers.get("Content-Length")
            if cl:
                with item._lock:
                    item.total_bytes = int(cl) + start_byte

        os.makedirs(item.dest_dir, exist_ok=True)
        with open(part_path, "ab") as f:
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
        with item._lock:
            item.state = State.DONE
            item.speed = 0


def build_filename(uploaded_name: str, mod_id: int, version: str,
                   append_mod_id: bool, append_version: bool) -> str:
    """Construct download filename per Wrye Bash convention."""
    ext = Path(uploaded_name).suffix
    stem = uploaded_name[: len(uploaded_name) - len(ext)] if ext else uploaded_name

    mod_id_str = str(mod_id)
    safe_version = version.replace(" ", "-").replace(".", "-").replace("/", "-").replace("\\", "-")

    suffix = ""
    if append_mod_id and mod_id_str not in stem:
        suffix += "-" + mod_id_str
    if append_version and safe_version and safe_version not in stem:
        suffix += "-" + safe_version

    return stem + suffix + ext


def _format_speed(bps: float) -> str:
    if bps <= 0:
        return "\u2014"
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    return f"{bps / 1024:.0f} KB/s"


def _format_size(b: int) -> str:
    if b <= 0:
        return "\u2014"
    if b >= 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024 * 1024):.1f} GB"
    if b >= 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / 1024:.0f} KB"
