"""Parser for nxm:// protocol URLs."""
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs


@dataclass
class NXMLink:
    game_domain: str
    mod_id: int
    file_id: int
    key: str = ""
    expires: str = ""


def parse_nxm(raw: str) -> NXMLink:
    """Parse an nxm:// URL. Raises ValueError on malformed input."""
    u = urlparse(raw)
    if u.scheme.lower() != "nxm":
        raise ValueError(f"Not an nxm:// URL: scheme={u.scheme!r}")
    if not u.hostname:
        raise ValueError("Missing game domain")

    parts = [p for p in u.path.strip("/").split("/") if p]
    if len(parts) < 4 or parts[0] != "mods" or parts[2] != "files":
        raise ValueError(f"Invalid path: expected /mods/{{id}}/files/{{id}}, got {u.path!r}")

    try:
        mod_id = int(parts[1])
    except ValueError:
        raise ValueError(f"Invalid mod_id: {parts[1]!r}")
    try:
        file_id = int(parts[3])
    except ValueError:
        raise ValueError(f"Invalid file_id: {parts[3]!r}")

    q = parse_qs(u.query)
    return NXMLink(
        game_domain=u.hostname,
        mod_id=mod_id,
        file_id=file_id,
        key=q.get("key", [""])[0],
        expires=q.get("expires", [""])[0],
    )


