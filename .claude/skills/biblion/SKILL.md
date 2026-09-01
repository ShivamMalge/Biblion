---
name: biblion
description: Produce a typeset PDF book, report, or study notes from written content. Use whenever the user asks for a PDF, a book, a printable document, study notes, course notes, a handbook, or a report — and whenever they ask to turn markdown into a nicely formatted PDF. Writes content-only markdown and renders it with the local `biblion` CLI, which owns all layout and renders mermaid/d2 diagrams. Do NOT hand-build PDF layout, HTML, or CSS when this skill applies.
---

# Biblion

Biblion turns plain markdown into a typeset PDF: cover page, contents with real
page numbers, callout boxes, syntax highlighting, and rendered mermaid/d2
diagrams.

## Why this skill exists

Generating a beautiful PDF directly costs an enormous number of tokens — you
would be emitting layout, spacing, colours and page structure, and the user
pays that cost again on every revision.

**Your job is the information. Biblion's job is the presentation.** Write
content-only markdown and shell out. The layout is already built and costs
nothing to re-run.

So: do not write HTML, CSS, inline styles, ASCII-art boxes, or a hand-numbered
table of contents. Do not reach for a PDF library. Write markdown.

## Workflow

**1. Check the toolchain once.**

```bash
biblion doctor
```

This reports whether `mmdc` (mermaid) and `d2` are available. If a renderer is
missing, tell the user the one-line install it printed, and either proceed
without that diagram type or use the one that works. Never silently emit a
diagram that cannot render.

**2. Set up the project** (skip if `book.toml` already exists):

```bash
biblion init <folder> --title "Some Title"
```

That scaffolds `book.toml` and a `modules/` folder. Edit `book.toml` for
title, subtitle, author, and the cover's `eyebrow` line.

**3. Write the content** as `modules/01_*.md`, `modules/02_*.md`, ... They are
merged in filename order, so zero-pad the numbers. One file per chapter is a
good default; split long material rather than writing one enormous file.

**4. Build:**

```bash
biblion build <folder>
```

Read the `Diagrams:` line in the output. If it reports failures, fix the
diagram source and rebuild — do not leave a book with unrendered figures.
Add `--strict` to make a failed diagram fail the build.

## The markdown contract

Run `biblion prompt` for the full spec. The essentials:

- `#` starts a new page, so use one per chapter. `##` and `###` for sections.
- Normal paragraphs, `**bold**`, `*italic*`, `` `code` ``, `-` and `1.` lists,
  `>` blockquotes, and GitHub pipe tables (keep them under ~6 columns; the
  page is A4).
- Fenced code blocks **must** carry a language tag — that drives highlighting.
- No table of contents. Biblion generates one with real page numbers.

Callouts use admonition syntax, body indented four spaces:

```
!!! deepdive "Why this exists"
    The long explanation.
```

Types: `deepdive`, `interview`, `workhelp`, `note`, `tip`.

## Diagrams

This is where the token saving is largest. Never describe a diagram in prose
and never draw one in ASCII. Emit diagram source — about thirty tokens — and
Biblion renders a real figure.

Use ```mermaid for flows, sequences and state machines:

````
```mermaid
flowchart LR
    A["Source code"] -->|docker build| B["Image"]
```
````

Use ```d2 for architecture and anything where nesting matters:

````
```d2
cluster: "Kubernetes cluster" {
  svc: Service
  pod: Pod
  svc -> pod
}
client: Client { shape: person }
client -> cluster.svc
```
````

Caption anything worth finding again, with `caption="..."` on the fence:

````
```d2 caption="How the pieces fit together."
a -> b
```
````

Biblion numbers captioned figures, keeps caption and figure on the same page,
and builds a "Figures" page. Never number a figure yourself.

Rules:

- Quote labels containing spaces or punctuation: `A["Like this"]`.
- `<br/>` for line breaks in mermaid labels; `\n` in d2 labels.
- Roughly 12 nodes maximum. Two clear diagrams beat one crowded one.
- Do not set colours or styles; the theme handles it.
- **Do not think about direction or orientation.** Biblion measures the
  rendered figure and re-lays it out if it is too wide for the page. Write
  whichever direction reads naturally.

## Common mistakes

- Writing HTML or CSS "to make it look nicer" — it is overridden, and wasted.
- Building one 3,000-line module instead of several chapter files.
- Emitting a diagram type whose renderer `biblion doctor` said is missing.
- Adding a manual contents list or manual page numbers.
- Styling diagram nodes with explicit colours.
