"""JS-callable API bridge between pywebview frontend and Python backend."""
import json
import os
import shutil
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

import webview

import archive
from config import Config
from download_manager import DownloadManager, State, file_md5, safe_filename
from modl_parser import parse_modl
from nexus_client import NexusAPIError, NexusClient, RateLimitedError, RevisionModFile
from nxm_parser import is_collection_url, parse_collection, parse_nxm
from focus import bring_to_front
import registry

PREMIUM_NEEDED = ("downloading collections needs a Nexus Premium account "
                  "(Nexus refused the download link: HTTP 403)")


@dataclass
class PendingMod:
    """A collection mod that still has to be queued."""
    domain: str
    mod_id: int
    file_id: int
    label: str  # mod name and version, for its row if cancelled
    md5: str


@dataclass
class CollectionRun:
    """Tracks the mods a collection has not queued yet, so that "Cancel all
    queued" can list them as cancelled too."""
    dest_dir: str
    todo: list[PendingMod] = field(default_factory=list)
    next: int = 0  # todo[next:] are not queued yet
    cancelled: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def cancel(self, mgr: DownloadManager) -> int:
        """List every mod not queued yet as cancelled; return how many."""
        with self.lock:
            if self.cancelled:
                return 0
            self.cancelled = True
            rest = self.todo[self.next:]
            mgr.add_cancelled(self.dest_dir,
                              [(f"cancel-{p.domain}-{p.file_id}", p.label) for p in rest])
            return len(rest)

    def skip(self) -> bool:
        """Move past the current mod without queuing it; False if cancelled."""
        with self.lock:
            if self.cancelled:
                return False
            self.next += 1
            return True


class ExistingFiles:
    """Finds files already in a folder by size and MD5. Files are hashed only
    when their size matches, and each at most once."""

    def __init__(self, dir_path: str):
        self._by_size: dict[int, list[str]] = {}
        self._hashes: dict[str, str] = {}
        try:
            entries = list(os.scandir(dir_path))
        except OSError:
            entries = []
        for e in entries:
            try:
                if e.is_file(follow_symlinks=False):
                    self._by_size.setdefault(e.stat().st_size, []).append(e.path)
            except OSError:
                pass

    def find(self, size: int, md5_hex: str) -> str:
        """The name of a file in the folder with this size and MD5, or ""."""
        if size <= 0 or not md5_hex:
            return ""
        for path in self._by_size.get(size, []):
            h = self._hashes.get(path)
            if h is None:
                try:
                    h = file_md5(path)
                except OSError:
                    h = ""
                self._hashes[path] = h
            if h and h == md5_hex.lower():
                return os.path.basename(path)
        return ""


class Api:
    def __init__(self, cfg: Config, window_ref: list):
        self.cfg = cfg
        self._window_ref = window_ref  # mutable list holding [window] once created
        self._dl_mgr = DownloadManager(on_change=self._emit_progress)
        self._next_id = 0
        self._lock = threading.Lock()
        # Changes on "Cancel all queued"; a collection whose archive was still
        # downloading at that point cancels all of its mods.
        self._cancel_gen = 0
        # collections that are still queuing their mods
        self._coll_lock = threading.Lock()
        self._runs: dict[int, CollectionRun] = {}

    @property
    def _window(self):
        return self._window_ref[0] if self._window_ref else None

    # -- Downloads --
    def get_downloads(self):
        return [item.progress() for item in self._dl_mgr.items()]

    def pause(self, id: str):
        self._dl_mgr.pause(id)

    def resume(self, id: str):
        self._dl_mgr.resume(id)

    def cancel(self, id: str):
        self._dl_mgr.cancel(id)

    def remove(self, id: str):
        self._dl_mgr.remove(id)

    def delete(self, id: str):
        self._dl_mgr.delete(id)

    def clear_completed(self):
        self._dl_mgr.clear_completed()

    def cancel_all_queued(self) -> int:
        """Cancel every download still waiting to start, plus every collection
        mod not queued yet (each gets a Cancelled row); return how many."""
        with self._coll_lock:
            self._cancel_gen += 1
            runs = list(self._runs.values())
        n = self._dl_mgr.cancel_queued()
        for run in runs:
            n += run.cancel(self._dl_mgr)
        return n

    # -- Config --
    def get_config(self):
        return {
            "api_key": self.cfg.api_key,
            "download_dir": self.cfg.download_dir,
            "minimize_to_tray": self.cfg.minimize_to_tray,
            "seven_zip_path": self.cfg.seven_zip_path,
        }

    def save_config(self, api_key: str, download_dir: str, minimize_to_tray: bool,
                    seven_zip_path: str = ""):
        self.cfg.api_key = api_key
        self.cfg.download_dir = download_dir
        self.cfg.minimize_to_tray = minimize_to_tray
        self.cfg.seven_zip_path = seven_zip_path
        self.cfg.save()

    def browse_7z(self) -> str:
        w = self._window
        if not w:
            return ""
        result = w.create_file_dialog(
            webview.OPEN_DIALOG,
            directory="C:\\Program Files\\7-Zip",
            allow_multiple=False,
            file_types=("Executable (*.exe)", "All Files (*.*)",),
        )
        if result and len(result) > 0:
            return result[0]
        return ""

    def validate_api_key(self, api_key: str) -> str:
        client = NexusClient(api_key)
        name, premium = client.validate_key()
        self._set_parallel_limit(premium)
        badge = " [Premium]" if premium else ""
        return name + badge

    def _set_parallel_limit(self, premium: bool):
        """Vortex's rule: Premium accounts get the configured number of
        parallel downloads, everyone else gets 1."""
        n = 1
        if premium and self.cfg.max_parallel_downloads > 0:
            n = self.cfg.max_parallel_downloads
        self._dl_mgr.set_max_parallel(n)

    # -- Registration --
    def register(self):
        registry.register()

    def deregister(self):
        registry.deregister()

    def is_registered(self) -> bool:
        return registry.is_registered()

    def register_modl(self):
        registry.register_modl()

    def deregister_modl(self):
        registry.deregister_modl()

    def is_modl_registered(self) -> bool:
        return registry.is_modl_registered()

    # -- Misc --
    def is_first_run(self) -> bool:
        return Config.is_first_run()

    def open_api_key_page(self):
        webbrowser.open("https://www.nexusmods.com/users/myaccount?tab=api")

    def browse_folder(self, current_path: str) -> str:
        w = self._window
        if not w:
            return ""
        result = w.create_file_dialog(webview.FOLDER_DIALOG, directory=current_path or "")
        if result and len(result) > 0:
            return result[0]
        return ""

    # -- Link handling --
    def handle_nxm_url(self, url: str):
        """Process an nxm:// URL (called from IPC or startup): a single file
        or a collection."""
        if not self.cfg.api_key:
            self._emit_error("No API key configured. Open Settings to add one.")
            return
        try:
            if is_collection_url(url):
                link = parse_collection(url)
                target = self._start_collection_download
            else:
                link = parse_nxm(url)
                target = self._start_nxm_download
        except ValueError as e:
            self._emit_error(f"Can't handle this link:\n{url}\n\n{e}")
            return
        threading.Thread(target=target, args=(link,), daemon=True).start()

    def handle_modl_url(self, url: str):
        """Process a modl:// URL."""
        try:
            link = parse_modl(url)
        except ValueError as e:
            self._emit_error(f"Can't handle this link:\n{url}\n\n{e}")
            return
        threading.Thread(target=self._start_modl_download, args=(link,), daemon=True).start()

    def _start_nxm_download(self, link):
        try:
            client = NexusClient(self.cfg.api_key)
            file_info = client.file_details(link.game_domain, link.mod_id, link.file_id)
            links = client.generate_download_link(link.game_domain, link.mod_id, link.file_id,
                                                  link.key, link.expires)
            if not links:
                self._emit_error("No download links returned.")
                return

            default_name = safe_filename(file_info.file_name)
            self._show_and_focus()
            save_path = self._save_dialog(default_name)
            if not save_path:
                return

            dir_path = os.path.dirname(save_path)
            file_name = os.path.basename(save_path)

            self._dl_mgr.add(str(file_info.uid), links[0].uri, dir_path, file_name,
                             file_info.size_in_bytes or 0)
        except Exception as e:
            self._emit_error(f"Download error: {e}")

    def _start_modl_download(self, link):
        try:
            default_name = link.name or "download"
            self._show_and_focus()
            save_path = self._save_dialog(default_name)
            if not save_path:
                return

            dir_path = os.path.dirname(save_path)
            file_name = os.path.basename(save_path)

            self._dl_mgr.add(self._new_id(), link.download_url, dir_path, file_name, 0)
        except Exception as e:
            self._emit_error(f"Download error: {e}")

    def _new_id(self, prefix: str = "") -> str:
        with self._lock:
            self._next_id += 1
            return f"{prefix}{self._next_id}"

    # -- Collections --
    def _start_collection_download(self, link):
        try:
            self._collection_download(link)
        except Exception as e:
            self._emit_error(f"Collection error: {e}")

    def _collection_download(self, link):
        with self._coll_lock:
            gen = self._cancel_gen
        client = NexusClient(self.cfg.api_key)

        try:
            _, premium = client.validate_key()
            self._set_parallel_limit(premium)
        except Exception:
            pass

        rev = client.get_collection_revision(link.collection_slug, link.revision_number)

        # let user pick destination folder
        self._show_and_focus()
        dest_dir = self._folder_dialog(self.cfg.download_dir)
        if not dest_dir:
            return  # user cancelled

        cdn_links = client.resolve_collection_download(rev.download_link)
        if not cdn_links:
            self._emit_error("No CDN links returned for collection archive.")
            return

        # download the archive (size unknown until the download starts)
        archive_name = f"{rev.collection_slug}-rev{rev.revision_number}.7z"
        archive_path = os.path.join(dest_dir, archive_name)
        archive_id = self._new_id("col-")
        item = self._dl_mgr.add(archive_id, cdn_links[0].uri, dest_dir, archive_name, 0)
        while item.state not in (State.DONE, State.ERROR, State.CANCELLED):
            time.sleep(0.25)
        if item.state == State.CANCELLED:
            return
        if item.state != State.DONE:
            self._emit_error(f"Collection archive download failed: {item.error}")
            return

        # extract collection.json, then drop the archive and its row
        temp_dir = archive_path + ".extracted"
        try:
            archive.extract(archive_path, temp_dir, self.cfg.seven_zip_path)
            try:
                os.remove(archive_path)
            except OSError:
                pass
            self._dl_mgr.remove(archive_id)
            try:
                data = json.loads(Path(temp_dir, "collection.json").read_text(encoding="utf-8"))
            except OSError:
                self._emit_error("collection.json not found in archive")
                return
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        # file metadata for every mod, already fetched with the revision
        rev_files = {(f.domain, f.file_id): f for f in rev.mod_files}

        # First, locally: list mods already in the folder as skipped (Vortex
        # matches collection files by MD5 too) and collect the rest.
        existing = ExistingFiles(dest_dir)
        run = CollectionRun(dest_dir=dest_dir)
        for mod in data.get("mods", []):
            src = mod.get("source") or {}
            mod_id, file_id = src.get("modId") or 0, src.get("fileId") or 0
            if src.get("type") != "nexus" or not mod_id or not file_id:
                continue
            domain = mod.get("domainName") or link.game_domain
            md5 = src.get("md5") or ""
            name = existing.find(src.get("fileSize") or 0, md5)
            if name:
                self._dl_mgr.add_skipped(f"skip-{domain}-{file_id}", dest_dir, name,
                                         src.get("fileSize") or 0)
                continue
            label = f"{mod.get('name', '')} {mod.get('version', '')}".strip()
            run.todo.append(PendingMod(domain, mod_id, file_id, label, md5))

        # Register the run so "Cancel all queued" can cancel what it hasn't
        # queued yet: a cancel either sees this run or is seen here.
        with self._coll_lock:
            cancelled_meanwhile = self._cancel_gen != gen
            if not cancelled_meanwhile:
                self._runs[id(run)] = run
        if cancelled_meanwhile:  # cancelled while the archive downloaded
            run.cancel(self._dl_mgr)
            return
        try:
            self._queue_collection_mods(client, rev, rev_files, run)
        finally:
            with self._coll_lock:
                self._runs.pop(id(run), None)

    def _queue_collection_mods(self, client: NexusClient, rev, rev_files, run: CollectionRun):
        """Queue the collection's remaining mods, one API round trip each."""
        name = rev.collection_name
        while True:
            with run.lock:
                if run.cancelled or run.next >= len(run.todo):
                    return
                p = run.todo[run.next]

            try:
                links = client.generate_download_link(p.domain, p.mod_id, p.file_id)
            except RateLimitedError as e:
                self._emit_error(f'Stopped queuing "{name}": {e}')
                return
            except NexusAPIError as e:
                if e.status == 403:  # keyless download_link: Premium only
                    self._emit_error(f'Stopped queuing "{name}": {PREMIUM_NEEDED}')
                    return
                self._emit_error(f"Failed to get download link for {p.label}: {e}")
                if not run.skip():
                    return
                continue
            if not links:
                if not run.skip():
                    return
                continue

            try:
                file_name, uid, size = self._collection_file_name(
                    client, rev_files.get((p.domain, p.file_id)), p, links[0].uri)
            except RateLimitedError as e:
                self._emit_error(f'Stopped queuing "{name}": {e}')
                return
            except Exception as e:
                self._emit_error(f"Failed to get info for {p.label}: {e}")
                if not run.skip():
                    return
                continue

            # queue it, unless "Cancel all queued" listed it as cancelled meanwhile
            with run.lock:
                if run.cancelled:
                    return
                self._dl_mgr.add(str(uid), links[0].uri, run.dest_dir, file_name, size, p.md5)
                run.next += 1

    def _collection_file_name(self, client: NexusClient, rf: RevisionModFile | None,
                              p: PendingMod, cdn_url: str) -> tuple[str, int, int]:
        """A collection mod's filename (Nexus's file_name, from the CDN's
        Content-Disposition), file UID and size in bytes, using the revision's
        GraphQL metadata. If either is unavailable, falls back to a v1
        file_details call."""
        if rf is not None and rf.uid:
            try:
                cdn_name = client.cdn_file_name(cdn_url)
            except Exception:
                cdn_name = ""
            if cdn_name:
                return safe_filename(cdn_name), rf.uid, rf.size_in_bytes

        fi = client.file_details(p.domain, p.mod_id, p.file_id)
        return safe_filename(fi.file_name), fi.uid, fi.size_in_bytes

    # -- Dialogs and events --
    def _save_dialog(self, default_name: str) -> str:
        w = self._window
        if not w:
            return ""
        ext = os.path.splitext(default_name)[1].lstrip(".")
        file_types = (f"{ext.upper()} file (*.{ext})", "All Files (*.*)",) if ext else ("All Files (*.*)",)
        result = w.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=self.cfg.download_dir,
            save_filename=default_name,
            file_types=file_types,
        )
        if result:
            return result if isinstance(result, str) else result[0] if result else ""
        return ""

    def _folder_dialog(self, directory: str) -> str:
        w = self._window
        if not w:
            return ""
        result = w.create_file_dialog(webview.FOLDER_DIALOG, directory=directory or "")
        if result:
            return result if isinstance(result, str) else result[0] if result else ""
        return ""

    def _show_and_focus(self):
        w = self._window
        if w:
            w.show()
            bring_to_front()

    def _emit_progress(self):
        w = self._window
        if w:
            rows = json.dumps(self.get_downloads())
            w.evaluate_js(f"window.onDownloadsUpdated && window.onDownloadsUpdated({rows})")

    def _emit_error(self, msg: str):
        w = self._window
        if w:
            w.show()
            safe = json.dumps(msg)
            w.evaluate_js(f"window.onError && window.onError({safe})")
