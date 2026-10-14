"""Updates from GitHub Releases: find a newer release, download its installer, check SHA-256."""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .version import RELEASES_API, VERSION

INSTALLER_NAME = "KopiTehnik-Converter-Setup.exe"
SUMS_NAME = "SHA256SUMS.txt"
MAX_INSTALLER = 600 * 1024 * 1024
_ALLOWED_HOSTS = ("https://github.com/", "https://objects.githubusercontent.com/",
                  "https://release-assets.githubusercontent.com/")


@dataclass
class UpdateInfo:
    version: str
    url: str = ""          # installer download (https), empty when the release has none
    sha256: str = ""       # expected hash of the installer, empty when the release has none
    size: int = 0
    notes: str = ""
    page: str = ""         # release page to open in the browser


def _key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)


def is_newer(remote: str, local: str = VERSION) -> bool:
    return _key(remote) > _key(local)


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": f"KopiTehnik-Converter/{VERSION}",
                                                "Accept": "application/vnd.github+json"})


def _fetch(url: str, limit: int, timeout: float) -> bytes:
    if not url.lower().startswith("https://"):
        raise ValueError("update url must be https")
    with urllib.request.urlopen(_request(url), timeout=timeout) as r:
        return r.read(limit)


def parse_sums(text: str, name: str = INSTALLER_NAME) -> str:
    """SHA-256 of ``name`` from a ``sha256sum``-style file ('<hash> *<name>' per line), else ''."""
    for line in text.splitlines():
        m = re.match(r"^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m and m.group(2) == name:
            return m.group(1).lower()
    return ""


def check(url: str = RELEASES_API, timeout: float = 8.0) -> UpdateInfo | None:
    """Newer release described at ``url`` or None. Raises OSError/ValueError when it cannot be read."""
    if not url:
        raise ValueError("update url is not set")
    data = json.loads(_fetch(url, 1 << 20, timeout).decode("utf-8"))
    if data.get("draft") or data.get("prerelease"):
        return None
    info = UpdateInfo(str(data["tag_name"]).lstrip("vV"), notes=str(data.get("body") or "")[:4000],
                      page=str(data.get("html_url") or ""))
    if not is_newer(info.version):
        return None
    assets = {a.get("name"): a for a in data.get("assets", [])}
    inst, sums = assets.get(INSTALLER_NAME), assets.get(SUMS_NAME)
    if inst and sums and str(inst.get("browser_download_url", "")).startswith(_ALLOWED_HOSTS):
        try:
            text = _fetch(str(sums["browser_download_url"]), 65536, timeout).decode("utf-8", "replace")
            digest = parse_sums(text)
        except (OSError, ValueError):
            digest = ""
        if digest:  # without a published hash the installer is not offered for automatic install
            info.url, info.sha256, info.size = str(inst["browser_download_url"]), digest, int(inst.get("size") or 0)
    return info


class HashMismatch(Exception):
    pass


def download(info: UpdateInfo, progress: Callable[[int, int], None] | None = None,
             should_stop: Callable[[], bool] | None = None, timeout: float = 30.0) -> Path:
    """Download the installer to a temp folder and return its path; raises HashMismatch on a wrong SHA-256."""
    if not (info.url and info.sha256):
        raise ValueError("release has no installer with a checksum")
    dest = Path(tempfile.mkdtemp(prefix="kopitehnik-update-")) / INSTALLER_NAME
    h = hashlib.sha256()
    got = 0
    try:
        with urllib.request.urlopen(_request(info.url), timeout=timeout) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or info.size or 0)
            while chunk := r.read(1 << 18):
                if should_stop and should_stop():
                    raise InterruptedError("cancelled")
                got += len(chunk)
                if got > MAX_INSTALLER:
                    raise ValueError("installer is too large")
                h.update(chunk)
                f.write(chunk)
                if progress:
                    progress(got, total)
        if h.hexdigest() != info.sha256.lower():
            raise HashMismatch(f"expected {info.sha256}, got {h.hexdigest()}")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return dest
