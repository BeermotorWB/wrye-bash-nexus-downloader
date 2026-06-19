"""Parser for modl:// protocol URLs (MO2 direct downloads)."""
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs
from posixpath import basename as url_basename


@dataclass
class ModlLink:
    game_domain: str
    download_url: str
    name: str = ""
    mod_name: str = ""
    version: str = ""
    source: str = ""


def parse_modl(raw: str) -> ModlLink:
    """Parse a modl:// URL. Raises ValueError on malformed input."""
    u = urlparse(raw)
    if u.scheme.lower() != "modl":
        raise ValueError(f"Not a modl:// URL: scheme={u.scheme!r}")
    if not u.hostname:
        raise ValueError("Missing game domain")

    q = parse_qs(u.query)
    dl_url = q.get("url", [""])[0]
    if not dl_url:
        raise ValueError("Missing required 'url' parameter")
    parsed_dl = urlparse(dl_url)
    if not parsed_dl.scheme:
        raise ValueError(f"Invalid download URL: {dl_url!r}")

    name = q.get("name", [""])[0]
    if not name:
        name = url_basename(parsed_dl.path)
        if name in (".", "/", ""):
            name = ""

    return ModlLink(
        game_domain=u.hostname,
        download_url=dl_url,
        name=name,
        mod_name=q.get("modName", [""])[0],
        version=q.get("version", [""])[0],
        source=q.get("source", [""])[0],
    )
