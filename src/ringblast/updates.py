"""Check on GitHub whether a newer version of RingBlast has been released.

The latest *release* of the repository is read from the public GitHub API (no login needed).  If the
repository has no release yet, the highest version tag is used.  Nothing is downloaded or installed
here: the program only tells the user that a new version exists and opens the download page.

Release tags must look like `v0.2.0`.  When a release carries a `RingBlast-portable-*.zip` file
(attached by the GitHub Actions workflow), the download link points directly to it.
"""
from __future__ import annotations

import json
import sys
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

from .about import VERSION

REPO = "stebond/RingBlast"
API = f"https://api.github.com/repos/{REPO}"
PAGE = f"https://github.com/{REPO}/releases"
TIMEOUT_S = 6
CHECK_EVERY_DAYS = 1                       # automatic check at start-up: at most once a day


class UpdateError(Exception):
    """The check could not be done (no network, GitHub unreachable, unexpected answer)."""


@dataclass
class UpdateInfo:
    version: str                           # e.g. "0.2.0"
    tag: str                               # e.g. "v0.2.0"
    page_url: str                          # release page
    asset_url: str = ""                    # direct link to the portable Windows zip, if any
    notes: str = ""
    published: str = ""


def parse_version(text: str) -> tuple:
    """'v0.2.1' -> (0, 2, 1, 1); a pre-release suffix ('0.2.0rc1', '0.2.0-beta') sorts before the release."""
    m = re.match(r"^\s*[vV]?(\d+(?:\.\d+)*)(.*)$", text or "")
    if not m:
        raise ValueError(f"not a version: {text!r}")
    nums = [int(x) for x in m.group(1).split(".")]
    while len(nums) < 3:
        nums.append(0)
    pre = 0 if m.group(2).strip() else 1
    return (*nums, pre)


def is_newer(latest: str, current: str = VERSION) -> bool:
    try:
        return parse_version(latest) > parse_version(current)
    except ValueError:
        return False


def _get(url: str, opener: Callable = urllib.request.urlopen):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"RingBlast/{VERSION}"})
    try:
        with opener(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise UpdateError(f"GitHub answered with error {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError("GitHub cannot be reached (is the computer online?)") from e


def _asset(assets: list) -> str:
    """Portable archive of the running platform (zip on Windows/macOS, tar.gz on Linux)."""
    plat = "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"
    cands = [a for a in assets or [] if str(a.get("name", "")).lower().endswith((".zip", ".tar.gz"))]
    best = (next((a for a in cands if plat in a["name"].lower()), None)
            or next((a for a in cands if "portable" in a["name"].lower()), None))
    return best.get("browser_download_url", "") if best else ""


def fetch_latest(opener: Callable = urllib.request.urlopen) -> Optional[UpdateInfo]:
    """Latest published release (or highest tag); None if the repository has neither."""
    rel = _get(f"{API}/releases/latest", opener)
    if rel and rel.get("tag_name"):
        tag = rel["tag_name"]
        return UpdateInfo(tag.lstrip("vV"), tag, rel.get("html_url", PAGE), _asset(rel.get("assets")),
                          (rel.get("body") or "").strip(), (rel.get("published_at") or "")[:10])
    tags = _get(f"{API}/tags", opener) or []
    best = None
    for t in tags:
        try:
            key = parse_version(t.get("name", ""))
        except ValueError:
            continue
        if best is None or key > best[0]:
            best = (key, t["name"])
    if best is None:
        return None
    return UpdateInfo(best[1].lstrip("vV"), best[1], f"https://github.com/{REPO}/releases/tag/{best[1]}")


# ------------------------------------------------------------------ remembered choices
def _file():
    from . import db                      # same user folder as the other settings
    return db.USER_DIR / "ui_settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(**changes) -> None:
    """Merge `changes` into ui_settings.json (shared with the tooltip option)."""
    d = load_settings()
    d.update(changes)
    try:
        f = _file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass


def auto_check_enabled() -> bool:
    return bool(load_settings().get("check_updates", True))


def due_for_auto_check(today: Optional[date] = None) -> bool:
    """True if the start-up check is enabled and has not been done today."""
    if os.environ.get("RINGBLAST_NO_UPDATE_CHECK") or not auto_check_enabled():
        return False
    last = load_settings().get("last_update_check", "")
    return last != (today or date.today()).isoformat()


def check(manual: bool = False, current: str = VERSION,
          opener: Callable = urllib.request.urlopen) -> Optional[UpdateInfo]:
    """Return the newer release, or None if this is the latest version.

    An automatic check also returns None for a version the user chose to skip; a manual one never does.
    Raises UpdateError when the check fails."""
    info = fetch_latest(opener)
    save_settings(last_update_check=date.today().isoformat())
    if info is None or not is_newer(info.version, current):
        return None
    if not manual and load_settings().get("skip_version") == info.version:
        return None
    return info
