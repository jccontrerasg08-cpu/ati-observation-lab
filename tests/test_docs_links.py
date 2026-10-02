"""Every relative link in the repository's Markdown resolves to a file that exists.

Documentation that points at a moved or deleted file is a broken window: it quietly
teaches readers the wrong layout. External URLs are out of scope; they are not
checked offline.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_SKIPPED_DIRECTORIES = {".git", ".venv", "node_modules", "build", "dist"}


def _markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not _SKIPPED_DIRECTORIES.intersection(path.relative_to(ROOT).parts)
    )


def _relative_targets(markdown: Path) -> list[str]:
    targets = []
    in_fence = False
    for line in markdown.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for target in _LINK.findall(line):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            targets.append(target.split("#", 1)[0])
    return [target for target in targets if target]


def test_every_relative_markdown_link_resolves() -> None:
    broken = [
        f"{markdown.relative_to(ROOT)} -> {target}"
        for markdown in _markdown_files()
        for target in _relative_targets(markdown)
        if not (markdown.parent / target).exists()
    ]

    assert broken == []
