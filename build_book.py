#!/usr/bin/env python3
"""Backwards-compatible shim for the old build_book.py interface.

The tool now lives in the `biblion` package with a `biblion` entry point.
This forwards the old flags so existing commands and scripts keep working.
"""

import sys

from biblion.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and not argv[0].startswith("-"):
        sys.exit(main(argv))
    # Old usage was flag-only, e.g. build_book.py --input ... --output ...
    print("note: build_book.py is deprecated; use `biblion build` instead.",
          file=sys.stderr)
    # --course-num/--student were IBM-specific; map them onto the new names.
    forwarded, skip = [], False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if arg == "--student":
            forwarded += ["--author", argv[i + 1]]
            skip = True
        elif arg == "--course-num":
            forwarded += ["--eyebrow", f"COURSE {argv[i + 1]}"]
            skip = True
        else:
            forwarded.append(arg)
    sys.exit(main(["build", *forwarded]))
