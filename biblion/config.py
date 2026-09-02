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


class ConfigError(ValueError):
    """A book.toml that cannot be used.

    Raised instead of letting tomllib's TOMLDecodeError escape, so a typo in a
    config file prints one clear line rather than a Python traceback. Subclasses
    ValueError because that is what a bad setting is, and so code that already
    catches ValueError keeps working.
    """


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
    # A "Figures" page listing every captioned diagram.
    figure_list: bool = True

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

        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"Could not read {path}: {exc}") from exc

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
            raise ConfigError(
                f"{path}: unknown setting(s): {', '.join(sorted(unknown))}.\n"
                f"Known settings: {', '.join(sorted(known))}")

        cls._check_types(path, merged)

        try:
            config = cls(**{k: v for k, v in merged.items() if k in known})
        except TypeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        config._source = path
        return config

    # Human names for the types a setting can have, for error messages.
    _TYPE_NAMES = {"str": "text in quotes", "int": "a whole number",
                   "bool": "true or false"}

    @classmethod
    def _check_types(cls, path: Path, merged: dict) -> None:
        """Reject a setting of the wrong type at load time.

        Without this, `toc_depth = "three"` sails through the dataclass and
        fails much later with a TypeError from deep inside the page-numbering
        code, which tells the user nothing about their config file.
        """
        # `from __future__ import annotations` means f.type is the string name.
        expected = {"str": str, "int": int, "bool": bool}
        for f in fields(cls):
            if f.name not in merged:
                continue
            want = expected.get(str(f.type))
            if want is None:
                continue
            value = merged[f.name]
            # bool is a subclass of int, so check it explicitly both ways.
            ok = (isinstance(value, bool) if want is bool
                  else isinstance(value, want) and not isinstance(value, bool))
            if not ok:
                raise ConfigError(
                    f"{path}: {f.name!r} must be "
                    f"{cls._TYPE_NAMES[str(f.type)]}, "
                    f"but got {value!r}")

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

        # Anchor a relative output path to the project folder, not the cwd.
        # Otherwise `biblion build examples/foo` writes foo's diagram cache
        # into the *parent* project's output directory.
        output_path = Path(self.output)
        if not output_path.is_absolute():
            output_path = base / output_path
        self.output = str(output_path.resolve())

        if not self.cache_dir:
            self.cache_dir = str(output_path.resolve().parent / "_diagram_cache")

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

# Look: "textbook" for course notes, "report" for API docs and specs.
theme = "textbook"

# Contents page: include it, and how deep to go (1 = H1 only).
toc       = true
toc_depth = 3

# List every captioned diagram on its own "Figures" page.
figure_list = true

# Diagram rendering. d2 theme id; see `d2 themes`.
diagram_theme = "0"
diagram_width = 1400

# Re-lay-out diagrams that are too wide for a portrait page.
autofit = true

# Fail the build (non-zero exit) if any diagram fails to render.
strict = false
'''
