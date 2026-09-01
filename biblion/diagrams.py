"""Rendering fenced ```mermaid and ```d2 blocks into images.

Design notes, because two of these were real bugs in the first version:

* Ask the renderers for PNG **directly** where we can. mermaid-cli drives a
  headless browser, so ``mmdc -o out.png`` is a single step -- routing it
  through SVG and then rsvg-convert added a hard dependency that has no sane
  Windows installer, for no benefit.
* Never conclude "it worked" from ``path.exists()``. A stale PNG left by an
  earlier run made failed conversions look successful. Every render writes to
  a fresh path and checks the exit code.
* Cache on a hash of (source, renderer, options). Diagram rendering is by far
  the slowest part of a build; the first version hashed the source into the
  filename but then re-rendered it anyway.
"""

from __future__ import annotations

import hashlib
import os
import re
import struct
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import tools


def png_size(path: Path) -> tuple[int, int]:
    """Width and height straight out of the PNG IHDR chunk.

    Avoids taking a Pillow dependency just to read two integers.
    """
    header = path.read_bytes()[16:24]
    width, height = struct.unpack(">II", header)
    return width, height


def fit_scale(width: int, height: int) -> float:
    """How much a figure gets scaled to fit the page box.

    Doubles as a legibility score: two renders of the same diagram come out of
    the same renderer at the same font size, so the one with the larger fit
    scale is the one whose text ends up physically bigger on the page.
    """
    if width <= 0 or height <= 0:
        return 0.0
    return min(BOX_W / width, BOX_H / height)


MERMAID_BLOCK_RE = re.compile(r"```mermaid[ \t]*\n(.*?)\n```", re.DOTALL)
D2_BLOCK_RE = re.compile(r"```d2[ \t]*\n(.*?)\n```", re.DOTALL)

# Rendered wide, then scaled down by CSS into a ~16cm column. 1400px across
# roughly 16.6cm works out to ~215dpi in the PDF, which stays crisp in print.
DEFAULT_WIDTH = 1400

# Per-renderer wall-clock ceiling. Generous enough for a big diagram, short
# enough that a stuck renderer surfaces as an error rather than a hung build.
RENDER_TIMEOUT = int(os.environ.get("BIBLION_RENDER_TIMEOUT", "120"))

# The usable figure box on an A4 page with this theme's margins, in CSS px
# at 96dpi: 16.6cm of column width by 21cm of height.
BOX_W = 627
BOX_H = 794

# Above this width:height ratio a figure is squeezed into an unreadable strip
# by the portrait text column, and is worth re-rendering the other way round.
RESHAPE_ABOVE_ASPECT = 2.2

# Above this, even after reshaping, let the figure use the full page width
# rather than just the text column.
FULL_BLEED_ABOVE_ASPECT = 2.6

# `flowchart LR` / `graph RL` and friends. Direction is pure presentation, and
# presentation is Biblion's job -- the authoring contract tells writers not to
# spend tokens on it.
MERMAID_DIRECTION_RE = re.compile(
    r"^([ \t]*(?:flowchart|graph)[ \t]+)(LR|RL)\b", re.MULTILINE)

# d2's equivalent: a top-level `direction: right`. Only a declaration at the
# start of a line counts, so a nested container's own direction is left alone.
D2_DIRECTION_RE = re.compile(
    r"^(direction[ \t]*:[ \t]*)(right|left)[ \t]*$", re.MULTILINE)

# d2 sequence diagrams read top-to-bottom by definition; rewriting their
# direction does nothing useful and only costs a second render.
D2_SEQUENCE_RE = re.compile(r"^[ \t]*shape[ \t]*:[ \t]*sequence_diagram",
                            re.MULTILINE)


def _d2_downward(code: str) -> str:
    """Turn a horizontal d2 diagram vertical, where that makes sense."""
    if D2_SEQUENCE_RE.search(code):
        return code
    return D2_DIRECTION_RE.sub(r"\1down", code, count=1)


@dataclass
class DiagramReport:
    """What happened to every diagram in the build."""
    rendered: int = 0
    cached: int = 0
    reshaped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped_missing_tool: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (self.rendered + self.cached + len(self.failed)
                + len(self.skipped_missing_tool))

    @property
    def ok(self) -> bool:
        return not self.failed and not self.skipped_missing_tool

    def summary(self) -> str:
        if self.total == 0:
            return "No diagrams found."
        parts = [f"{self.rendered + self.cached}/{self.total} diagrams rendered"]
        if self.cached:
            parts.append(f"{self.cached} from cache")
        if self.reshaped:
            parts.append(f"{self.reshaped} re-laid out to fit the page")
        if self.failed:
            parts.append(f"{len(self.failed)} FAILED")
        if self.skipped_missing_tool:
            missing = ", ".join(sorted(set(self.skipped_missing_tool)))
            parts.append(f"{len(self.skipped_missing_tool)} skipped (missing: {missing})")
        return " | ".join(parts)


class DiagramRenderer:
    """Turns diagram source into PNGs on disk, with a persistent cache."""

    def __init__(self, cache_dir: Path, project_dirs: tuple[str, ...] = (),
                 puppeteer_config: str | None = None, theme: str = "0",
                 width: int = DEFAULT_WIDTH, background: str = "white",
                 allow_downloads: bool = False, autofit: bool = True,
                 pad: int = 20, progress=None):
        # Resolved so rendered images can be referenced as absolute file://
        # URIs regardless of what the caller passed in.
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.width = width
        self.theme = theme
        self.background = background
        self.allow_downloads = allow_downloads
        self.autofit = autofit
        # d2 defaults to 100px of padding, which is a lot of dead space
        # once the figure is scaled into a text column.
        self.pad = pad
        # Called with a one-line status per diagram. Rendering is slow and
        # silent otherwise, which makes a stall indistinguishable from work.
        self.progress = progress or (lambda message: None)
        self.report = DiagramReport()

        self.mmdc = tools.find_binary("mmdc", project_dirs)
        self.d2 = tools.find_binary("d2", project_dirs)
        self.rsvg = tools.find_binary("rsvg-convert", project_dirs)
        self.browser = tools.find_browser()
        self.puppeteer_config = tools.puppeteer_config(puppeteer_config)

    # -- cache ------------------------------------------------------------

    def _cache_key(self, code: str, renderer: str) -> str:
        material = "\x00".join([
            renderer, code, str(self.width), str(self.theme), self.background,
            # Bust the cache when the renderer binary itself changes.
            str(self.mmdc or ""), str(self.d2 or ""), str(self.pad),
            str(self.browser or ""),
        ])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    # -- mermaid ----------------------------------------------------------

    def render_mermaid(self, code: str) -> Path | None:
        if self.mmdc is None:
            self.report.skipped_missing_tool.append("mmdc")
            return None

        key = self._cache_key(code, "mermaid")
        png_path = self.cache_dir / f"mermaid_{key}.png"
        if png_path.is_file() and png_path.stat().st_size > 0:
            self.report.cached += 1
            return png_path

        self.progress(f"  rendering mermaid diagram {key[:8]} ...")
        started = time.monotonic()
        if not self._mermaid_to_png(code, png_path, key):
            self.progress(f"  mermaid {key[:8]} FAILED: {self._last_error()}")
            return None

        self._autofit(code, png_path, key, "mermaid",
                      lambda src: MERMAID_DIRECTION_RE.sub(r"\1TD", src, count=1),
                      self._mermaid_to_png)
        self.progress(f"  mermaid {key[:8]} done in {time.monotonic() - started:.1f}s")
        self.report.rendered += 1
        return png_path

    def _mermaid_to_png(self, code: str, png_path: Path, key: str) -> bool:
        mmd_path = png_path.with_suffix(".mmd")
        mmd_path.write_text(code, encoding="utf-8")
        cmd = [str(self.mmdc), "-i", str(mmd_path), "-o", str(png_path),
               "-b", self.background, "-w", str(self.width)]
        if self.puppeteer_config:
            cmd += ["-p", str(self.puppeteer_config)]
        return self._run(cmd, png_path, "mermaid", key)

    # -- d2 ---------------------------------------------------------------

    def render_d2(self, code: str) -> Path | None:
        if self.d2 is None:
            self.report.skipped_missing_tool.append("d2")
            return None

        key = self._cache_key(code, "d2")
        png_path = self.cache_dir / f"d2_{key}.png"
        if png_path.is_file() and png_path.stat().st_size > 0:
            self.report.cached += 1
            return png_path

        self.progress(f"  rendering d2 diagram {key[:8]} ...")
        started = time.monotonic()
        if not self._d2_to_png(code, png_path, key):
            self.progress(f"  d2 {key[:8]} FAILED: {self._last_error()}")
            return None

        self._autofit(code, png_path, key, "d2", _d2_downward, self._d2_to_png)
        self.progress(f"  d2 {key[:8]} done in {time.monotonic() - started:.1f}s")
        self.report.rendered += 1
        return png_path

    def _d2_to_png(self, code: str, png_path: Path, key: str) -> bool:
        d2_path = png_path.with_suffix(".d2")
        d2_path.write_text(code, encoding="utf-8")

        # d2 always compiles to SVG without needing a browser; the only
        # question is who rasterises it.
        svg_path = png_path.with_suffix(".svg")
        if not self._run([str(self.d2), "--theme", str(self.theme),
                          "--pad", str(self.pad), str(d2_path), str(svg_path)],
                         svg_path, "d2", key):
            return False

        # Rasterisers in order of preference. Each is tried until one works,
        # rather than giving up on the first -- a browser that cannot screenshot
        # on this machine should not take d2 support down with it.
        #
        # 1. A browser we already found. Best fidelity (d2 embeds its fonts as
        #    base64 @font-face, which rsvg does not always honour) and no
        #    install cost, since mermaid needs the same browser anyway.
        # 2. rsvg-convert, if the user happens to have it.
        # 3. d2 rasterising itself, which needs its own Chromium (~150MB)
        #    behind an interactive prompt, so only with consent.
        attempts: list[tuple[str, object]] = []

        if self.browser is not None:
            attempts.append(("browser", lambda: tools.browser_svg_to_png(
                self.browser, svg_path, png_path, target_width=self.width)))

        if self.rsvg is not None:
            attempts.append(("rsvg-convert", lambda: self._run_quiet(
                [str(self.rsvg), "-o", str(png_path), "-w", str(self.width),
                 "--background-color=white", str(svg_path)], png_path)))

        attempts.append(("d2 native", lambda: self._run_quiet(
            [str(self.d2), "--theme", str(self.theme), "--pad", str(self.pad),
             str(d2_path), str(png_path)], png_path,
            stdin_text="y\n" if self.allow_downloads else "n\n")))

        errors = []
        for name, attempt in attempts:
            ok, detail = attempt()
            if ok:
                return True
            errors.append(f"{name}: {detail}")
            self.progress(f"    {name} could not rasterise d2 {key[:8]}: {detail}")

        self.report.failed.append((f"d2:{key}", " | ".join(errors)[:400]))
        return False

    # -- shared -----------------------------------------------------------

    def _last_error(self) -> str:
        return self.report.failed[-1][1] if self.report.failed else "unknown error"

    def _autofit(self, code: str, png_path: Path, key: str, kind: str,
                 rewrite, render) -> None:
        """Re-render a too-wide figure the other way round, and keep the better.

        A long left-to-right chain becomes an unreadable strip in a portrait
        column. Direction is presentation, and the authoring contract tells
        writers not to spend tokens on presentation -- so Biblion decides it.
        """
        if not self.autofit:
            return
        width, height = png_size(png_path)
        if width / max(height, 1) <= RESHAPE_ABOVE_ASPECT:
            return

        reshaped = rewrite(code)
        if reshaped == code:
            return

        alt_path = png_path.with_name(png_path.stem + "_alt.png")
        if not render(reshaped, alt_path, key + ":alt"):
            return

        if fit_scale(*png_size(alt_path)) > fit_scale(width, height):
            png_path.unlink(missing_ok=True)
            alt_path.replace(png_path)
            self.report.reshaped += 1
        else:
            alt_path.unlink(missing_ok=True)

    def _run_quiet(self, cmd: list[str], expected: Path,
                   stdin_text: str | None = None) -> tuple[bool, str]:
        """Run a renderer and verify it genuinely produced the file.

        Returns (ok, detail) without recording anything, so a caller trying
        several rasterisers can fall through to the next one. Deletes any
        pre-existing target first, so a stale artefact from an earlier run can
        never be mistaken for a successful render.
        """
        expected.unlink(missing_ok=True)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    input=stdin_text, timeout=RENDER_TIMEOUT)
        except subprocess.TimeoutExpired:
            return False, f"timed out after {RENDER_TIMEOUT}s"
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller
            return False, f"{type(exc).__name__}: {exc}"

        if result.returncode != 0 or not expected.is_file() or expected.stat().st_size == 0:
            detail = (result.stderr or result.stdout or "").strip()
            last_line = detail.splitlines()[-1] if detail else "no output"
            return False, _explain(detail, last_line)
        return True, ""

    def _run(self, cmd: list[str], expected: Path, kind: str, key: str,
             stdin_text: str | None = None) -> bool:
        """_run_quiet, but a failure is recorded in the report."""
        ok, detail = self._run_quiet(cmd, expected, stdin_text)
        if not ok:
            self.report.failed.append((f"{kind}:{key}", detail))
        return ok

    # -- markdown substitution -------------------------------------------

    def process(self, md_text: str) -> str:
        """Replace every diagram block in a markdown document with an <img>."""
        md_text = MERMAID_BLOCK_RE.sub(
            lambda m: self._substitute(m.group(1), self.render_mermaid, "mermaid"),
            md_text)
        md_text = D2_BLOCK_RE.sub(
            lambda m: self._substitute(m.group(1), self.render_d2, "d2"),
            md_text)
        return md_text

    def _substitute(self, code, render, kind: str) -> str:
        png_path = render(code)
        if png_path is not None:
            width, height = png_size(png_path)
            # A figure that is still wide after reshaping gets to use the full
            # page width instead of just the text column -- the extra 3cm is
            # the difference between readable and not.
            wide = " diagram-wide" if width / max(height, 1) > FULL_BLEED_ABOVE_ASPECT else ""
            # A file:// URI keeps Windows drive letters and spaces intact,
            # which a bare path in an src= attribute does not.
            return (f'<div class="diagram{wide}">'
                    f'<img src="{png_path.as_uri()}"></div>')
        # Preserve the source so nothing is lost from the document, but make
        # it visibly a failure rather than a mysterious black box.
        return (f'<div class="diagram-failed">'
                f'<div class="diagram-failed-label">Unrendered {kind} diagram</div>'
                f'<pre><code>{_escape(code)}</code></pre></div>')


# The line that actually says what is wrong, as opposed to the stack frames
# that follow it. mermaid-cli in particular buries the parse error several
# lines above the end of its output.
_MEANINGFUL_ERROR_RE = re.compile(
    r"^.*(?:Parse error|Syntax error|Expecting|error:|Error:).*$",
    re.MULTILINE | re.IGNORECASE)


def _explain(full_output: str, last_line: str) -> str:
    """Translate a renderer's error into something the user can act on."""
    if "install Chromium" in full_output or "failed to read user input" in full_output:
        return ("d2 needs a one-time Chromium download to export PNG. "
                "Re-run with --allow-downloads, or install rsvg-convert to "
                "skip the download entirely.")
    if "Could not find Chrome" in full_output or "browserType.launch" in full_output:
        return ("mermaid-cli could not start a browser. Install Chrome/Edge, "
                "or set BIBLION_BROWSER=/path/to/chrome.")

    for match in _MEANINGFUL_ERROR_RE.finditer(full_output):
        line = match.group(0).strip()
        # Stack frames match "error:" too; they always start with "at ".
        if line and not line.startswith("at "):
            return line[:200]
    return last_line[:200]


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
