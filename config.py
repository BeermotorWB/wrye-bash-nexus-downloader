"""Configuration management — reads/writes wb_nxm_downloader.json next to executable."""
import json
import os
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

FILENAME = "wb_nxm_downloader.json"


def _config_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent
    return base / FILENAME


def _default_download_dir() -> str:
    return str(Path.home() / "Downloads")


@dataclass
class Config:
    api_key: str = ""
    download_dir: str = ""
    minimize_to_tray: bool = True
    append_mod_id: bool = True
    append_version: bool = True
    seven_zip_path: str = ""

    def __post_init__(self):
        if not self.download_dir:
            self.download_dir = _default_download_dir()

    def save(self) -> None:
        data = {
            "api_key": self.api_key,
            "download_dir": self.download_dir,
            "minimize_to_tray": self.minimize_to_tray,
            "append_mod_id": self.append_mod_id,
            "append_version": self.append_version,
            "seven_zip_path": self.seven_zip_path,
        }
        _config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def load() -> "Config":
        path = _config_path()
        cfg = Config()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                cfg.api_key = data.get("api_key", "")
                cfg.download_dir = data.get("download_dir", "") or _default_download_dir()
                cfg.minimize_to_tray = data.get("minimize_to_tray", True)
                cfg.append_mod_id = data.get("append_mod_id", True)
                cfg.append_version = data.get("append_version", True)
                cfg.seven_zip_path = data.get("seven_zip_path", "")
            except (json.JSONDecodeError, OSError):
                pass
        return cfg

    @staticmethod
    def is_first_run() -> bool:
        return not _config_path().exists()
