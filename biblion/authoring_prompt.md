# Markdown authoring contract for Biblion

Paste this into your AI chat before asking it to write a document.

---

You are writing **content-only markdown** that will be typeset into a PDF book
by a tool called Biblion. Biblion owns all presentation: fonts, page size,
margins, page breaks, the cover, the contents page, colours, syntax
highlighting and diagram rendering.

**Therefore: do not produce any styling.** No HTML, no CSS, no inline styles,
no `<div>`, no `<br>` outside diagram labels, no emoji bullets, no ASCII art
boxes, no manual page-break markers, no "─────" separators, no manually
numbered tables of contents. Every token you spend on appearance is a token
wasted, because Biblion will override it.

Write only these constructs:

## Structure

- `#` — one per chapter. Biblion starts a new page at every `#`.
- `##`, `###` — sections and subsections.
- Ordinary paragraphs, `**bold**`, `*italic*`, `` `inline code` ``.
- `-` bullets and `1.` numbered lists.
- `>` blockquotes for quoted definitions.
- GitHub-style pipe tables. Keep them under ~6 columns; the page is A4.
- Fenced code blocks **with a language tag** (```python, ```bash, ```yaml).
  The language tag drives syntax highlighting, so always include it.

Do **not** write a table of contents. Biblion generates one with real page
numbers.

## Callout boxes

Use admonition syntax. The body must be indented four spaces.

```
!!! deepdive "Why MCP exists"
    A language model is a brain in a jar. It needs hands.

!!! interview "Likely question"
    Q: How does MCP differ from a plain REST API?
    A: ...

!!! workhelp "When to use what"
    Use STDIO when the server is local.
```

Available types: `deepdive`, `interview`, `workhelp`, `note`, `tip`.

## Diagrams

This is the part that saves the most tokens. Do not describe a diagram in
prose and do not draw it in ASCII. Emit **diagram source**, which is perhaps
thirty tokens, and Biblion renders it into a real vector-quality image.

Use ```mermaid for flows, sequences, states and ER diagrams:

````
```mermaid
flowchart LR
    A["Source code<br/>+ Dockerfile"] -->|docker build| B["Image"]
    B -->|docker push| C[("Registry")]
```
````

Use ```d2 for architecture diagrams, containers and grouped systems, where
d2's nesting reads better than mermaid's `subgraph`:

````
```d2
cluster: "Kubernetes cluster" {
  pod: Pod
  svc: Service
  pod -> svc
}
client: Client { shape: person }
client -> cluster.svc: request
```
````

d2 also does sequence diagrams, which suit protocol walkthroughs:

````
```d2
shape: sequence_diagram
client -> gateway: "POST /orders"
gateway -> service: "forward"
service -> client: "201 Created"
```
````

Useful d2 shapes: `person`, `cylinder` (datastores), `page`, `document`,
`hexagon`, `queue`. Use them sparingly, where they carry meaning.

### Captions

Give a diagram a caption with `caption="..."` on the opening fence. Biblion
numbers it ("Figure 2.3"), keeps the caption glued to its figure across page
breaks, and lists it on a "Figures" page with a real page number.

````
```mermaid caption="How a request reaches a pod."
flowchart LR
    A["Client"] --> B["Ingress"]
```
````

Caption anything a reader might want to find again. Write the caption as a
sentence saying what the figure shows, not a restatement of its title, and do
not number it yourself -- Biblion does that.

Diagram rules:

- Always quote node labels that contain spaces or punctuation: `A["Like this"]`.
- Use `<br/>` inside mermaid labels for line breaks. It is the one HTML tag
  allowed. In d2 labels, use `\n`.
- Keep a diagram to roughly 12 nodes. Two clear diagrams beat one crowded one.
- Do not set colours or styles in the diagram source; the theme handles it.
- Do not worry about direction or which way a diagram flows. Biblion re-lays
  out anything too wide for the page, so pick whichever reads naturally.

## What you are optimising for

Produce the **information**. A dense, well-structured 2,000-line markdown file
costs a fraction of what it costs to have an AI lay out a PDF, and Biblion will
render it identically every time, for free, forever.
