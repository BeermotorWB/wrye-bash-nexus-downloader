"""JS-callable API bridge between pywebview frontend and Python backend."""
import json
import os
import threading
import webbrowser

import webview

from config import Config
from download_manager import DownloadManager, build_filename
from modl_parser import parse_modl
from nexus_client import NexusClient
from nxm_parser import parse_nxm
from focus import bring_to_front
import registry


class Api:
    def __init__(self, cfg: Config, window_ref: list):
        self.cfg = cfg
        self._window_ref = window_ref  # mutable list holding [window] once created
        self._dl_mgr = DownloadManager(on_change=self._emit_progress)
        self._next_id = 0
        self._lock = threading.Lock()

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

    # -- Config --
    def get_config(self):
        return {
            "api_key": self.cfg.api_key,
            "download_dir": self.cfg.download_dir,
            "minimize_to_tray": self.cfg.minimize_to_tray,
            "append_mod_id": self.cfg.append_mod_id,
            "append_version": self.cfg.append_version,
            "seven_zip_path": self.cfg.seven_zip_path,
        }

    def save_config(self, api_key: str, download_dir: str, minimize_to_tray: bool,
                    append_mod_id: bool, append_version: bool, seven_zip_path: str = ""):
        self.cfg.api_key = api_key
        self.cfg.download_dir = download_dir
        self.cfg.minimize_to_tray = minimize_to_tray
        self.cfg.append_mod_id = append_mod_id
        self.cfg.append_version = append_version
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
        badge = " [Premium]" if premium else ""
        return name + badge

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
        """Process an nxm:// URL (called from IPC or startup)."""
        if not self.cfg.api_key:
            self._emit_error("No API key configured. Open Settings to add one.")
            return
        try:
            link = parse_nxm(url)
        except ValueError as e:
            self._emit_error(f"Invalid NXM link: {e}")
            return
        threading.Thread(target=self._start_nxm_download, args=(link,), daemon=True).start()

    def handle_modl_url(self, url: str):
        """Process a modl:// URL."""
        try:
            link = parse_modl(url)
        except ValueError as e:
            self._emit_error(f"Invalid MODL link: {e}")
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

            default_name = build_filename(file_info.file_name, link.mod_id, file_info.version,
                                          self.cfg.append_mod_id, self.cfg.append_version)
            self._show_and_focus()
            save_path = self._save_dialog(default_name)
            if not save_path:
                return

            dir_path = os.path.dirname(save_path)
            file_name = os.path.basename(save_path)

            with self._lock:
                self._next_id += 1
                dl_id = str(self._next_id)

            self._dl_mgr.add(dl_id, links[0].uri, dir_path, file_name, file_info.size_in_bytes or 0)
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

            with self._lock:
                self._next_id += 1
                dl_id = str(self._next_id)

            self._dl_mgr.add(dl_id, link.download_url, dir_path, file_name, 0)
        except Exception as e:
            self._emit_error(f"Download error: {e}")

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
            safe = json.dumps(msg)
            w.evaluate_js(f"window.onError && window.onError({safe})")
