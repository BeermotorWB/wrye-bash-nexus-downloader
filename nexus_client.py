"""Nexus Mods API client (REST v1 and GraphQL v2).

Every API request carries the header set Vortex's nexus-api client sends
(node-nexus-api src/Nexus.ts), with this application's name. CDN requests
carry none of these.

Rate limits follow nexus-api: x-rl-* is read from every response; a 429 is
retried up to MAX_RATE_LIMIT_RETRIES times unless the known budget is used
up, in which case no further requests are sent.
"""
import platform
import sys
import threading
import time
from dataclasses import dataclass, field
from email.message import Message

import requests

from version import VERSION

API_HOST = "https://api.nexusmods.com"
TIMEOUT = 30

APP_NAME = "WBNXMLink"
# The value nexus-api sends: its own package version (src/parameters.ts
# PROTOCOL_VERSION), 1.7.3 at the commit Vortex pins.
PROTOCOL_VERSION = "1.7.3"

MAX_RATE_LIMIT_RETRIES = 2
DELAY_AFTER_429 = 1.0  # seconds


def _os_release() -> str:
    """Node's os.release() on Windows, e.g. "10.0.26200"."""
    if sys.platform == "win32":
        v = sys.getwindowsversion()
        return f"{v.major}.{v.minor}.{v.build}"
    return platform.release() or "unknown"


def _node_arch() -> str:
    """Node's process.arch names."""
    machine = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "x86": "ia32", "i386": "ia32",
            "i686": "ia32", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)


def user_agent() -> str:
    """nexus-api's format, "NexusApiClient/1.7.3 (Windows_NT 10.0.26200; x64)
    Node/22.1.0", with this application's name and version and the Python
    runtime."""
    os_type = "Windows_NT" if sys.platform == "win32" else platform.system()
    return (f"{APP_NAME}/{VERSION} ({os_type} {_os_release()}; {_node_arch()}) "
            f"Python/{platform.python_version()}")


class NexusAPIError(RuntimeError):
    """An API request failed with an HTTP status code."""

    def __init__(self, status: int, body: str):
        super().__init__(f"Nexus API Error {status}: {body}")
        self.status = status


class RateLimitedError(RuntimeError):
    """Nexus's request budget is used up."""


@dataclass
class RateLimits:
    """The budget reported by the last response that carried x-rl-*."""
    known: bool = False
    hourly_remaining: int = 0
    daily_remaining: int = 0
    hourly_reset: str = ""  # as sent, e.g. "2026-09-30 15:00:00 +0000"
    daily_reset: str = ""

    def remaining(self) -> int:
        """The budget nexus-api uses: daily while it lasts, then hourly."""
        return self.daily_remaining if self.daily_remaining > 0 else self.hourly_remaining

    def exhausted(self) -> bool:
        return self.known and self.remaining() <= 0


@dataclass
class FileInfo:
    file_id: int
    uid: int
    file_name: str  # Nexus's file name; downloads are saved under it
    name: str       # display name
    version: str
    size_kb: int
    size_in_bytes: int
    mod_version: str


@dataclass
class DownloadLink:
    name: str
    short_name: str
    uri: str


@dataclass
class RevisionModFile:
    """GraphQL collectionRevision.modFiles[].file."""
    mod_id: int
    file_id: int
    name: str
    version: str
    uid: int  # served as a decimal string
    size_in_bytes: int  # served as a string
    domain: str


@dataclass
class RevisionInfo:
    id: int
    revision_number: int
    download_link: str
    collection_name: str
    collection_slug: str
    domain: str
    mod_files: list[RevisionModFile] = field(default_factory=list)


REVISION_QUERY = """query collectionRevision($slug: String!, $revision: Int, $viewAdultContent: Boolean) {
  collectionRevision(slug: $slug, revision: $revision, viewAdultContent: $viewAdultContent) {
    id
    revisionNumber
    downloadLink
    fileSize
    collection {
      id
      slug
      name
      game { domainName }
    }
    modFiles {
      file {
        modId
        fileId
        size
        name
        version
        uri
        uid
        sizeInBytes
        game { domainName }
      }
    }
  }
}"""


def content_disposition_file_name(header: str) -> str:
    """The filename parameter of a Content-Disposition header (RFC 2231
    filename* is decoded)."""
    if not header:
        return ""
    msg = Message()
    msg["content-disposition"] = header
    return msg.get_filename() or ""


class NexusClient:
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._session = requests.Session()
        self.host = API_HOST  # tests point it at a local server
        self.retry_delay = DELAY_AFTER_429
        self._limits_lock = threading.Lock()
        self._limits = RateLimits()

    # -- Rate limits --
    def limits(self) -> RateLimits:
        with self._limits_lock:
            return RateLimits(**vars(self._limits))

    def _update_limits(self, headers) -> None:
        try:
            hourly = int(headers["x-rl-hourly-remaining"])
            daily = int(headers["x-rl-daily-remaining"])
        except (KeyError, ValueError):
            return
        with self._limits_lock:
            self._limits = RateLimits(True, hourly, daily,
                                      headers.get("x-rl-hourly-reset", ""),
                                      headers.get("x-rl-daily-reset", ""))

    def _rate_limit_error(self) -> RateLimitedError:
        lim = self.limits()
        if lim.exhausted() and lim.hourly_reset:
            return RateLimitedError(
                f"Nexus API rate limit reached (hourly budget resets {lim.hourly_reset})")
        return RateLimitedError("Nexus API rate limit reached")

    def _api_headers(self) -> dict:
        return {
            "apikey": self._api_key,
            "Accept": "application/json",
            "Protocol-Version": PROTOCOL_VERSION,
            "Application-Name": APP_NAME,
            "Application-Version": VERSION,
            "User-Agent": user_agent(),
        }

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Send an API request, retrying a 429 as nexus-api does. Raises
        RateLimitedError or NexusAPIError; returns a 2xx response."""
        headers = {**self._api_headers(), **kwargs.pop("headers", {})}
        attempt = 0
        while True:
            if self.limits().exhausted():
                raise self._rate_limit_error()
            resp = self._session.request(method, self.host + path, headers=headers,
                                         timeout=TIMEOUT, **kwargs)
            self._update_limits(resp.headers)
            if resp.status_code != 429:
                break
            if self.limits().exhausted() or attempt >= MAX_RATE_LIMIT_RETRIES:
                raise self._rate_limit_error()
            attempt += 1
            time.sleep(self.retry_delay)
        if not resp.ok:
            raise NexusAPIError(resp.status_code, resp.text)
        return resp

    def _get(self, endpoint: str, params: dict | None = None):
        return self._request("GET", "/v1/" + endpoint, params=params).json()

    # -- REST v1 --
    def file_details(self, game_domain: str, mod_id: int, file_id: int) -> FileInfo:
        data = self._get(f"games/{game_domain}/mods/{mod_id}/files/{file_id}.json")
        return FileInfo(
            file_id=data.get("file_id", 0),
            uid=data.get("uid", 0),
            file_name=data.get("file_name", ""),
            name=data.get("name", ""),
            version=data.get("version", ""),
            size_kb=data.get("size_kb", 0),
            size_in_bytes=data.get("size_in_bytes") or 0,
            mod_version=data.get("mod_version", ""),
        )

    def generate_download_link(self, game_domain: str, mod_id: int, file_id: int,
                               key: str = "", expires: str = "") -> list[DownloadLink]:
        """CDN URLs for a file. key/expires (from the nxm:// link) are needed
        without Premium."""
        params = {}
        if key:
            params["key"] = key
        if expires:
            params["expires"] = expires
        data = self._get(f"games/{game_domain}/mods/{mod_id}/files/{file_id}/download_link.json", params)
        return [DownloadLink(name=d.get("name", ""), short_name=d.get("short_name", ""), uri=d["URI"])
                for d in data]

    def validate_key(self) -> tuple[str, bool]:
        data = self._get("users/validate.json")
        return data.get("name", ""), data.get("is_premium", False)

    # -- CDN --
    def cdn_file_name(self, cdn_url: str) -> str:
        """The file name from a CDN URL's Content-Disposition header (HEAD
        request). The CDN serves Nexus's file_name there; the URL path is
        only a storage hash."""
        resp = self._session.head(cdn_url, timeout=TIMEOUT, allow_redirects=True)
        if not resp.ok:
            raise RuntimeError(f"CDN HEAD HTTP {resp.status_code}")
        name = content_disposition_file_name(resp.headers.get("Content-Disposition", ""))
        if not name:
            raise RuntimeError("CDN response has no Content-Disposition file name")
        return name

    # -- GraphQL v2 / collections --
    def get_collection_revision(self, slug: str, revision: int) -> RevisionInfo:
        variables = {"slug": slug, "viewAdultContent": True}
        if revision > 0:
            variables["revision"] = revision
        resp = self._request("POST", "/v2/graphql",
                             json={"query": REVISION_QUERY, "variables": variables},
                             headers={"Content-Type": "application/json"})
        body = resp.json()
        errors = body.get("errors")
        if errors:
            code = (errors[0].get("extensions") or {}).get("code", "")
            raise RuntimeError(f"Nexus API Error: {errors[0].get('message', '')} (code: {code})")
        rev = (body.get("data") or {}).get("collectionRevision")
        if not rev:
            raise RuntimeError("collection revision not found")
        coll = rev.get("collection") or {}
        files = []
        for mf in rev.get("modFiles") or []:
            f = mf.get("file")
            if not f:
                continue
            files.append(RevisionModFile(
                mod_id=f.get("modId", 0), file_id=f.get("fileId", 0),
                name=f.get("name", ""), version=f.get("version", ""),
                uid=int(f.get("uid") or 0),
                size_in_bytes=int(f.get("sizeInBytes") or 0),
                domain=(f.get("game") or {}).get("domainName", "")))
        return RevisionInfo(
            id=rev.get("id", 0), revision_number=rev.get("revisionNumber", 0),
            download_link=rev.get("downloadLink", ""),
            collection_name=coll.get("name", ""), collection_slug=coll.get("slug", ""),
            domain=(coll.get("game") or {}).get("domainName", ""), mod_files=files)

    def resolve_collection_download(self, download_link: str) -> list[DownloadLink]:
        """Resolve a revision's downloadLink path into CDN URLs."""
        data = self._request("GET", download_link).json()
        if "download_links" in data:
            entries = data["download_links"]
        elif "download_link" in data:
            entries = [data["download_link"]]
        else:
            raise RuntimeError("unexpected response format: no download_links or download_link field")
        return [DownloadLink(name=d.get("name", ""), short_name=d.get("short_name", ""), uri=d["URI"])
                for d in entries]
