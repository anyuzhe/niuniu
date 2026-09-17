#!/usr/bin/env python3
"""Offline documentation path and heading check; never modifies project files."""
from __future__ import annotations
import argparse
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT_ENTRIES = {"README.md", "README.en.md", "AGENTS.md"}
INLINE = re.compile(r"\]\(\s*(<[^>]+>|[^\s)]+)")
HTML = re.compile(r"\b(?:src|href)=[\x22\x27]([^\x22\x27]+)[\x22\x27]")
REFERENCE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)")

def visible_lines(text: str):
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield number, line

def anchors(path: Path) -> set[str]:
    result, seen = set(), {}
    for _, line in visible_lines(path.read_text(encoding="utf-8")):
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            heading = re.sub(r"<[^>]+>", "", match.group(1)).lower()
            heading = re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")
            count = seen.get(heading, 0)
            seen[heading] = count + 1
            result.add(heading + (f"-{count}" if count else ""))
        result.update(re.findall(r"\b(?:id|name)=[\x22\x27]([^\x22\x27]+)[\x22\x27]", line))
    return result

def check(root: Path):
    root = root.resolve()
    errors, anchor_cache = [], {}
    counts = dict(documents=0, local_links=0, external_links=0, runtime_links=0)
    present = {p.name for p in root.glob("*.md") if not p.name.startswith("._")}
    if present != ROOT_ENTRIES:
        errors.append(f"Root Markdown entries differ: {sorted(present ^ ROOT_ENTRIES)}")
    files = [root / name for name in sorted(ROOT_ENTRIES)]
    for folder in ("docs", "agent_memory"):
        files.extend(sorted((root / folder).rglob("*.md")))
    for path in files:
        if path.name.startswith("._"):
            continue
        if not path.is_file() or path.is_symlink():
            errors.append(f"Missing or symlink documentation: {path}")
            continue
        counts["documents"] += 1
        for number, line in visible_lines(path.read_text(encoding="utf-8")):
            targets = INLINE.findall(line) + HTML.findall(line)
            reference = REFERENCE.match(line)
            if reference:
                targets.append(reference.group(1))
            for raw in targets:
                value = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
                parts = urlsplit(value)
                if parts.scheme or parts.netloc:
                    counts["external_links"] += 1
                    continue
                destination = unquote(parts.path)
                target = (path.parent / destination).resolve() if destination else path
                if not target.is_relative_to(root):
                    counts["external_links"] += 1
                    continue
                relative = target.relative_to(root)
                if relative.parts and relative.parts[0] == "artifacts":
                    counts["runtime_links"] += 1
                    continue
                counts["local_links"] += 1
                location = f"{path.relative_to(root)}:{number}"
                if not target.exists():
                    errors.append(f"{location}: missing target {value}")
                elif parts.fragment and target.suffix.lower() == ".md":
                    if target not in anchor_cache:
                        anchor_cache[target] = anchors(target)
                    if unquote(parts.fragment) not in anchor_cache[target]:
                        errors.append(f"{location}: missing heading {value}")
    return errors, counts

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    errors, counts = check(parser.parse_args().root)
    print("Documentation check:", counts)
    for error in errors:
        print("ERROR:", error)
    print(f"Result: {'FAIL' if errors else 'PASS'} ({len(errors)} errors)")
    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
