# Changelog

All notable changes to Biblion are recorded here. The distribution is
published to PyPI as [`biblion-pdf`](https://pypi.org/project/biblion-pdf/).

This project follows [Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-09-02

### Added

- **A second theme, `report`**, for API documentation, specifications and
  technical reports. Sans-serif throughout, tighter margins, a flat
  typographic title page and light bordered code blocks — deliberately
  austere where `textbook` is warm. It fits about 20% more on a page: the
  same book renders in 91 pages instead of 113. Choose it with
  `--theme report` or `theme = "report"` in `book.toml`.

### Changed

- **A bad `book.toml` now prints one clear line instead of a Python
  traceback.** Malformed TOML, unknown settings, and settings of the wrong
  type are each reported with the file, the setting, and what was expected —
  for example, `'toc_depth' must be a whole number, but got 'three'`.
  Previously a typo in a config file produced a stack trace, and a
  wrong-typed value crashed much later inside the page-numbering code.

## [0.2.0] — 2026-09-02

First public release.

### Added

- `biblion build`, `doctor`, `init`, `prompt` and `skill`.
- The `textbook` theme: cover page, contents with real page numbers, callout
  boxes, syntax highlighting and page-break rules.
- mermaid and d2 rendering, using a browser already installed on the machine,
  so neither puppeteer nor d2 needs to download its own ~150MB Chromium.
- **Diagram auto-fit.** A diagram too wide for a portrait page is re-rendered
  the other way round, and whichever version puts physically larger text on
  the page is kept. Anything still wide breaks out to the full page width.
- **Figure captions.** `caption="..."` on a diagram fence makes it a numbered
  figure, listed on a **Figures** page with real page numbers and kept in the
  same unbreakable block as its caption.
- **Running headers** naming the current chapter, updating at each `#` and
  carrying across continuation pages.
- `biblion skill` installs a Claude Code skill that teaches an agent to write
  content-only markdown and shell out to Biblion instead of hand-building a
  document.
- A persistent diagram cache keyed on source and render options, and
  per-diagram progress output so a long build is not silent.
- `book.toml` configuration, with command-line flags taking precedence.

[0.3.0]: https://github.com/ShivamMalge/Biblion/releases/tag/v0.3.0
[0.2.0]: https://github.com/ShivamMalge/Biblion/releases/tag/v0.2.0
