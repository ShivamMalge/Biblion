"""Book configuration.

A build should be `biblion build` in a folder, not five mandatory flags every
time. Settings resolve in this order, later winning:

    defaults  ->  book.toml  ->  command-line flags
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

CONFIG_NAME = "book.toml"


@dataclass
class BookConfig:
    # content
    input: str = "."
    output: str = ""
    title: str = ""
    subtitle: str = ""
    author: str = ""
    eyebrow: str = ""

    # layout
    theme: str = "textbook"
    css: str = ""
    toc: bool = True
    toc_depth: int = 3
    cover: bool = True

    # diagrams
    diagram_theme: str = "0"
    diagram_width: int = 1400
    diagram_background: str = "white"
    # Re-render a too-wide diagram the other way round so it fits the page.
    autofit: bool = True
    puppeteer_config: str = ""

    # build
    per_module: bool = False
    strict: bool = False
    allow_downloads: bool = False
    cache_dir: str = ""

    _source: Path | None = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls, directory: Path) -> "BookConfig":
        """Read book.toml from `directory`, or return defaults if absent."""
        path = directory / CONFIG_NAME
        if not path.is_file():
            return cls()

        with path.open("rb") as handle:
            data = tomllib.load(handle)

        # Accept both a flat table and a [book] section, since both read
        # naturally and guessing wrong shouldn't be a hard error.
        merged: dict = {}
        for key, value in data.items():
            if isinstance(value, dict):
                merged.update(value)
            else:
                merged[key] = value

        known = {f.name for f in fields(cls)} - {"_source"}
        unknown = set(merged) - known
        if unknown:
            raise ValueError(
                f"{path}: unknown setting(s): {', '.join(sorted(unknown))}. "
                f"Known settings: {', '.join(sorted(known))}")

        config = cls(**{k: v for k, v in merged.items() if k in known})
        config._source = path
        return config

    def merge_cli(self, args) -> "BookConfig":
        """Overlay any explicitly-passed CLI arguments on top of this config."""
        for f in fields(self):
            if f.name == "_source":
                continue
            value = getattr(args, f.name, None)
            # argparse defaults are None here, so only real user input wins.
            if value is not None:
                setattr(self, f.name, value)
        return self

    def resolve(self, base: Path) -> "BookConfig":
        """Fill in anything still empty, relative to the project directory."""
        # With no explicit input, prefer a modules/ folder -- that is what
        # `biblion init` scaffolds -- and fall back to the project root so a
        # bare folder of .md files also just works.
        if self.input == "." and any((base / "modules").glob("*.md")):
            self.input = "modules"

        input_dir = (base / self.input).resolve()

        if not self.title:
            self.title = input_dir.name.replace("_", " ").replace("-", " ").title()

        if not self.output:
            slug = "".join(ch for ch in self.title if ch.isalnum() or ch in " -_")
            slug = "_".join(slug.split()) or "book"
            self.output = str(base / "output" / f"{slug}.pdf")

        if not self.cache_dir:
            self.cache_dir = str(Path(self.output).resolve().parent / "_diagram_cache")

        return self


TEMPLATE = '''# Biblion book configuration.
# Run `biblion build` in this folder to rebuild the PDF.

title    = "{title}"
subtitle = ""
author   = ""
# Small uppercase line above the title on the cover. Leave empty to omit.
eyebrow  = ""

# Folder of .md files, merged in filename order.
input  = "modules"
output = "output/{slug}.pdf"

# Contents page: include it, and how deep to go (1 = H1 only).
toc       = true
toc_depth = 3

# Diagram rendering. d2 theme id; see `d2 themes`.
diagram_theme = "0"
diagram_width = 1400

# Re-lay-out diagrams that are too wide for a portrait page.
autofit = true

# Fail the build (non-zero exit) if any diagram fails to render.
strict = false
'''
