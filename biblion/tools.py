"""Locating the external binaries Biblion shells out to.

The original build_book.py used a bare ``shutil.which(name)``, which meant a
``d2.exe`` sitting right next to the script was invisible and every diagram
silently degraded to a code block. Discovery here is deliberately generous:
we look everywhere a user could reasonably have put the thing.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Where Biblion keeps downloaded binaries, generated puppeteer configs and the
# diagram cache. Overridable so CI can point it at a writable scratch dir.
HOME = Path(os.environ.get("BIBLION_HOME", Path.home() / ".biblion"))
BIN_DIR = HOME / "bin"
CACHE_DIR = HOME / "cache"

IS_WINDOWS = platform.system() == "Windows"

# Executable suffixes to try when probing an explicit directory. shutil.which
# consults PATHEXT for us, but only for PATH lookups -- not for the extra
# directories we search below, and npm installs its shims as `.cmd` on Windows.
_SUFFIXES = ["", ".exe", ".cmd", ".bat"] if IS_WINDOWS else [""]


def _fallback_bin_dirs() -> list[Path]:
    """Places a tool can be without being on PATH.

    Covers npm's global shim directories (so `npm i -g mermaid-cli` is found
    even from a shell that has not picked up the PATH change) and the usual
    user-local prefixes that installers write to.
    """
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "npm")
    candidates += [
        Path.home() / ".npm-global" / "bin",
        Path.home() / ".local" / "bin",
        Path("/usr/local/bin"),
        Path("/opt/homebrew/bin"),
    ]
    return [c for c in candidates if c.is_dir()]


def _probe(directory: Path, name: str) -> Path | None:
    for suffix in _SUFFIXES:
        candidate = directory / (name + suffix)
        if candidate.is_file():
            # Always absolute: Windows CreateProcess does not resolve a bare
            # relative "d2.exe" the way a shell would, so a relative hit here
            # would blow up with WinError 2 at call time.
            return candidate.resolve()
    return None


@lru_cache(maxsize=None)
def find_binary(name: str, extra_dirs: tuple[str, ...] = ()) -> Path | None:
    """Find an executable by name, searching (in order):

    1. ``BIBLION_<NAME>`` env var pointing straight at the binary
    2. the caller's extra directories (e.g. the project root)
    3. ``PATH``
    4. ``~/.biblion/bin`` (where ``biblion install`` puts things)
    5. npm's global shims and user-local bin directories
    """
    override = os.environ.get("BIBLION_" + name.upper().replace("-", "_"))
    if override:
        path = Path(override)
        if path.is_file():
            return path.resolve()

    for directory in extra_dirs:
        hit = _probe(Path(directory), name)
        if hit:
            return hit

    on_path = shutil.which(name)
    if on_path:
        return Path(on_path).resolve()

    for directory in [BIN_DIR, *_fallback_bin_dirs()]:
        hit = _probe(directory, name)
        if hit:
            return hit

    return None


# --------------------------------------------------------------------------
# Browser discovery, so mermaid-cli never has to download its own Chrome.
# --------------------------------------------------------------------------

_BROWSER_CANDIDATES = {
    "Windows": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "Linux": [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
        "/snap/bin/chromium",
    ],
}


@lru_cache(maxsize=1)
def find_browser() -> Path | None:
    """An already-installed Chromium-family browser, if there is one.

    Every Windows machine ships Edge, and most desktops have Chrome, so this
    almost always hits -- which is what lets us skip puppeteer's private
    Chrome download entirely.
    """
    override = os.environ.get("BIBLION_BROWSER")
    if override and Path(override).is_file():
        return Path(override)

    for candidate in _BROWSER_CANDIDATES.get(platform.system(), []):
        if Path(candidate).is_file():
            return Path(candidate)

    for name in ("google-chrome", "chromium", "chromium-browser", "msedge", "brave"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


_SVG_VIEWBOX_RE = re.compile(
    r'<svg[^>]*\bviewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)', re.IGNORECASE)
_SVG_WH_RE = re.compile(
    r'<svg[^>]*\bwidth="([\d.]+)"[^>]*\bheight="([\d.]+)"', re.IGNORECASE)


def svg_dimensions(svg_path: Path) -> tuple[int, int] | None:
    """The intrinsic pixel size of an SVG, from its viewBox or width/height."""
    # The interesting attributes are on the root element, so a prefix is plenty.
    head = svg_path.read_text(encoding="utf-8", errors="replace")[:4000]
    for pattern in (_SVG_VIEWBOX_RE, _SVG_WH_RE):
        match = pattern.search(head)
        if match:
            width, height = float(match.group(1)), float(match.group(2))
            if width > 0 and height > 0:
                return int(round(width)), int(round(height))
    return None


BROWSER_TIMEOUT = int(os.environ.get("BIBLION_BROWSER_TIMEOUT", "90"))


def browser_svg_to_png(browser: Path, svg_path: Path, png_path: Path,
                       target_width: int = 1400, max_scale: int = 4,
                       timeout: int = BROWSER_TIMEOUT) -> tuple[bool, str]:
    """Rasterise an SVG by screenshotting it in headless Chrome/Edge.

    This is how Biblion renders d2 without rsvg-convert (which has no sane
    Windows install) and without d2's own ~150MB Chromium download: the
    browser we already found for mermaid does the job, and unlike WeasyPrint's
    or cairosvg's SVG engines it handles d2's nested <svg> and base64
    @font-face correctly.
    """
    size = svg_dimensions(svg_path)
    if size is None:
        return False, f"could not read SVG dimensions from {svg_path.name}"
    width, height = size

    # Render above the final print size so the PDF stays crisp, but do not
    # blow up a tiny diagram to absurd pixel dimensions.
    scale = max(1, min(max_scale, round(target_width / max(width, 1))))

    # A throwaway profile per invocation. Sharing one directory means Chrome
    # writes a SingletonLock into it, and a previous run that did not exit
    # cleanly leaves that lock behind -- the next launch then blocks on it
    # forever instead of failing. A fresh directory cannot collide.
    profile_dir = Path(tempfile.mkdtemp(prefix="biblion-browser-"))

    png_path.unlink(missing_ok=True)
    cmd = [
        str(browser), "--headless=new",
        "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
        # Keep a CI or first-run browser from waiting on anything interactive
        # or network-bound. None of this is needed to draw a local SVG.
        "--no-first-run", "--no-default-browser-check", "--disable-extensions",
        "--disable-background-networking", "--disable-sync",
        "--disable-default-apps", "--disable-dev-shm-usage", "--mute-audio",
        f"--user-data-dir={profile_dir}",
        f"--force-device-scale-factor={scale}",
        f"--window-size={width},{height}",
        f"--screenshot={png_path}",
        svg_path.as_uri(),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, (
            f"browser timed out after {timeout}s rendering {svg_path.name}. "
            f"Set BIBLION_BROWSER_TIMEOUT to raise the limit, or "
            f"BIBLION_BROWSER to point at a different browser.")
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

    if png_path.is_file() and png_path.stat().st_size > 0:
        return True, ""
    detail = (result.stderr or result.stdout or "").strip()
    return False, detail.splitlines()[-1][:200] if detail else "browser wrote no image"


def puppeteer_config(explicit: str | None = None) -> Path | None:
    """Return a puppeteer config file for mermaid-cli.

    If the user passed one, use it. Otherwise synthesise one pointing at a
    browser we found and cache it under ~/.biblion. Returns None when no
    browser exists, in which case mermaid-cli falls back to whatever Chrome
    puppeteer downloaded for itself at install time.
    """
    if explicit:
        return Path(explicit)

    browser = find_browser()
    if browser is None:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    config_path = CACHE_DIR / "puppeteer-config.json"
    payload = {
        "executablePath": str(browser),
        # --no-sandbox is required in containers and CI, and is harmless on a
        # desktop where we only ever load our own local diagram source.
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }
    desired = json.dumps(payload, indent=2)
    if not config_path.is_file() or config_path.read_text(encoding="utf-8") != desired:
        config_path.write_text(desired, encoding="utf-8")
    return config_path


# --------------------------------------------------------------------------
# `biblion doctor`
# --------------------------------------------------------------------------

@dataclass
class ToolStatus:
    name: str
    path: Path | None
    version: str | None
    required_for: str
    install_hint: str

    @property
    def ok(self) -> bool:
        return self.path is not None


def _version_of(path: Path | None, args: list[str]) -> str | None:
    if path is None:
        return None
    try:
        result = subprocess.run([str(path), *args], capture_output=True,
                                text=True, timeout=60)
    except Exception:
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0][:60] if output else None


def survey(project_dirs: tuple[str, ...] = ()) -> list[ToolStatus]:
    """Inspect every external dependency and report what is actually usable."""
    d2 = find_binary("d2", project_dirs)
    mmdc = find_binary("mmdc", project_dirs)
    rsvg = find_binary("rsvg-convert", project_dirs)
    browser = find_browser()

    return [
        ToolStatus("mmdc", mmdc, _version_of(mmdc, ["--version"]),
                   "```mermaid diagrams",
                   "npm install -g @mermaid-js/mermaid-cli"),
        ToolStatus("d2", d2, _version_of(d2, ["--version"]),
                   "```d2 diagrams",
                   "https://d2lang.com/tour/install (or drop d2/d2.exe in your project root)"),
        ToolStatus("browser", browser, None,
                   "rasterising mermaid and d2 diagrams",
                   "install Chrome/Edge, or set BIBLION_BROWSER=/path/to/chrome"),
        ToolStatus("rsvg-convert", rsvg, _version_of(rsvg, ["--version"]),
                   "d2 diagrams (optional: only used when no browser is found)",
                   "Linux: apt install librsvg2-bin | macOS: brew install librsvg"),
    ]
