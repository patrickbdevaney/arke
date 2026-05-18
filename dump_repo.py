#!/usr/bin/env python3
"""
dump_repo.py — Dump full repo tree + file contents to a single text file

Usage:
    python dump_repo.py                    # dumps ~/arke/ to repo_dump.txt
    python dump_repo.py /path/to/repo      # dumps specified path
    python dump_repo.py /path/to/repo out.txt  # custom output file

Output format:
    - Directory tree at the top
    - Each file's full path as a header
    - File contents below it
    - Clear delimiters between files
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────

SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".next",
    "venv",
    "arke_env",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".turbo",
    ".vercel",
    "coverage",
    ".nyc_output",
}

SKIP_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "arke.db",
    "arke.db-wal",
    "arke.db-shm",
}

SKIP_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".class",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".ico",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".bin",
    ".exe",
    ".pkl",
    ".model",
}

MAX_FILE_BYTES = 200_000  # skip files larger than 200KB

DELIMITER = "=" * 80


# ── Tree builder ───────────────────────────────────────────────────────────


def build_tree(root: Path, prefix: str = "") -> list[str]:
    lines = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return lines

    entries = [
        e
        for e in entries
        if not (e.is_dir() and e.name in SKIP_DIRS)
        and e.name not in SKIP_FILES
        and not e.name.startswith(".")
        or e.name in {".env.example", ".gitignore", ".github"}
    ]

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{entry.name}")
        if entry.is_dir():
            extension = "    " if is_last else "│   "
            lines.extend(build_tree(entry, prefix + extension))

    return lines


# ── File collector ─────────────────────────────────────────────────────────


def collect_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # Skip hidden except .env.example and .gitignore
        if any(
            part.startswith(".")
            and part not in {".env.example", ".gitignore", ".github"}
            for part in path.parts
        ):
            continue
        # Skip dirs
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        # Skip files
        if path.name in SKIP_FILES:
            continue
        # Skip extensions
        if path.suffix.lower() in SKIP_EXTENSIONS:
            continue
        # Skip large files
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        files.append(path)
    return files


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    # Args
    repo_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "arke"
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("repo_dump.txt")

    if not repo_root.exists():
        print(f"ERROR: {repo_root} does not exist")
        sys.exit(1)

    repo_root = repo_root.resolve()
    print(f"Dumping: {repo_root}")
    print(f"Output:  {output_file}")

    files = collect_files(repo_root)
    tree_lines = build_tree(repo_root)

    with open(output_file, "w", encoding="utf-8") as out:

        # Header
        out.write(DELIMITER + "\n")
        out.write(f"REPO DUMP — {repo_root.name}\n")
        out.write(f"Generated: {datetime.now().isoformat()}\n")
        out.write(f"Root: {repo_root}\n")
        out.write(f"Files: {len(files)}\n")
        out.write(DELIMITER + "\n\n")

        # Directory tree
        out.write("DIRECTORY TREE\n")
        out.write(DELIMITER + "\n")
        out.write(f"{repo_root.name}/\n")
        out.write("\n".join(tree_lines))
        out.write("\n\n")

        # File contents
        out.write("FILE CONTENTS\n")
        out.write(DELIMITER + "\n\n")

        for path in files:
            rel = path.relative_to(repo_root)

            # File header
            out.write(DELIMITER + "\n")
            out.write(f"FILE: {rel}\n")
            out.write(DELIMITER + "\n")

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                out.write(content)
                if not content.endswith("\n"):
                    out.write("\n")
            except Exception as e:
                out.write(f"[ERROR reading file: {e}]\n")

            out.write("\n")

        # Footer
        out.write(DELIMITER + "\n")
        out.write(f"END OF DUMP — {len(files)} files\n")
        out.write(DELIMITER + "\n")

    size_kb = output_file.stat().st_size / 1024
    print(f"Done. {len(files)} files → {output_file} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
