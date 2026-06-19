"""Nexus Mods v1 API client."""
from dataclasses import dataclass
import requests

BASE_URL = "https://api.nexusmods.com/v1/"
TIMEOUT = 30

@dataclass
class FileInfo:
    file_id: int
    file_name: str
    name: str
    version: str
    size_kb: int
    size_in_bytes: int
    mod_version: str


@dataclass
class DownloadLink:
    name: str
    short_name: str
    uri: str


class NexusClient:
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({
            "apikey": api_key,
            "accept": "application/json",
            "application-name": "NXMLink",
            "application-version": "2.1.0",
        })
        self._session.timeout = TIMEOUT

    def file_details(self, game_domain: str, mod_id: int, file_id: int) -> FileInfo:
        data = self._get(f"games/{game_domain}/mods/{mod_id}/files/{file_id}.json")
        return FileInfo(
            file_id=data.get("file_id", 0),
            file_name=data.get("file_name", ""),
            name=data.get("name", ""),
            version=data.get("version", ""),
            size_kb=data.get("size_kb", 0),
            size_in_bytes=data.get("size_in_bytes") or 0,
            mod_version=data.get("mod_version", ""),
        )

    def generate_download_link(self, game_domain: str, mod_id: int, file_id: int,
                               key: str = "", expires: str = "") -> list[DownloadLink]:
        params = {}
        if key:
            params["key"] = key
        if expires:
            params["expires"] = expires
        data = self._get(f"games/{game_domain}/mods/{mod_id}/files/{file_id}/download_link.json", params)
        return [DownloadLink(name=d.get("name", ""), short_name=d.get("short_name", ""), uri=d["URI"]) for d in data]

    def validate_key(self) -> tuple[str, bool]:
        data = self._get("users/validate.json")
        return data.get("name", ""), data.get("is_premium", False)

    def _get(self, endpoint: str, params: dict | None = None):
        resp = self._session.get(BASE_URL + endpoint, params=params, timeout=TIMEOUT)
        if resp.status_code == 429:
            raise RuntimeError("API rate limit reached")
        if not resp.ok:
            raise RuntimeError(f"API error {resp.status_code}: {resp.text}")
        return resp.json()
