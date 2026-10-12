"""Look for a newer version: read a small JSON file from the network (see core/version.py)."""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from .version import UPDATE_URL, VERSION


@dataclass
class UpdateInfo:
    version: str
    url: str
    notes: str = ""


def _key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)


def is_newer(remote: str, local: str = VERSION) -> bool:
    return _key(remote) > _key(local)


def check(url: str = UPDATE_URL, timeout: float = 6.0) -> UpdateInfo | None:
    """Newer version described at ``url`` or None. Raises OSError/ValueError when the file cannot be read."""
    if not url:
        raise ValueError("update url is not set")
    if not url.lower().startswith("https://"):
        raise ValueError("update url must be https")
    req = urllib.request.Request(url, headers={"User-Agent": f"KopiTehnik-Converter/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read(65536).decode("utf-8"))
    info = UpdateInfo(str(data["version"]), str(data.get("url", "")), str(data.get("notes", "")))
    if info.url and not info.url.lower().startswith("https://"):
        info.url = ""
    return info if is_newer(info.version) else None
