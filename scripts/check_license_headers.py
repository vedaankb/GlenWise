# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju
"""Fail if any owned source file is missing the project SPDX header.

Owned sources: ``.py``, ``.ts``, ``.tsx``, ``.js``, ``.mjs``, ``.cjs`` under the
repo root, excluding generated files, lockfiles, vendored trees, and build output.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        ".git",
        ".pnpm-store",
        "__pycache__",
        ".next",
        "out",
        "playwright",
        ".cache",
        "data",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
    }
)
SKIP_NAMES = frozenset(
    {
        "schema.d.ts",  # openapi-typescript output
    }
)
EXTS = frozenset({".py", ".ts", ".tsx", ".js", ".mjs", ".cjs"})
SPDX = re.compile(r"SPDX-License-Identifier\s*:\s*AGPL-3\.0-or-later")
COPYRIGHT = re.compile(r"Copyright\s*\(C\)\s*20\d{2}\b")


def is_owned(path: Path) -> bool:
    if path.name in SKIP_NAMES or path.suffix not in EXTS:
        return False
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return False
    return not any(part in SKIP_DIRS for part in rel.parts)


def has_header(path: Path) -> bool:
    head = path.read_text(encoding="utf-8", errors="replace")[:1200]
    return bool(SPDX.search(head) and COPYRIGHT.search(head))


def main() -> int:
    missing: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or not is_owned(path):
            continue
        if not has_header(path):
            missing.append(str(path.relative_to(ROOT)))
    if missing:
        print("Missing SPDX / copyright header:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        print(
            f"\n{len(missing)} file(s). Expected near the top:\n"
            "  SPDX-License-Identifier: AGPL-3.0-or-later\n"
            "  Copyright (C) 2026 …",
            file=sys.stderr,
        )
        return 1
    print("license headers: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
