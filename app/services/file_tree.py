from pathlib import Path


IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "venv",
}


def scan_project_tree(root_path: str, max_items: int = 200):
    if not root_path:
        return {"root_exists": False, "items": [], "error": "No root path set."}

    root = Path(root_path).expanduser()
    if not root.exists() or not root.is_dir():
        return {"root_exists": False, "items": [], "error": "Root path does not exist."}

    items = []

    for path in sorted(root.rglob("*")):
        if len(items) >= max_items:
            break

        relative = path.relative_to(root)
        parts = relative.parts
        if any(part in IGNORED_DIRS for part in parts):
            continue

        item_type = "dir" if path.is_dir() else "file"
        depth = max(len(parts) - 1, 0)
        name = path.name + ("/" if item_type == "dir" else "")

        items.append(
            {
                "path": str(relative),
                "name": name,
                "type": item_type,
                "depth": depth,
            }
        )

    return {"root_exists": True, "items": items, "error": None}


def read_project_file(root_path: str, relative_path: str, max_chars: int = 20000):
    if not root_path:
        return {"ok": False, "error": "No root path set.", "content": "", "path": relative_path}

    root = Path(root_path).expanduser().resolve()
    target = (root / relative_path).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        return {"ok": False, "error": "Path is outside the project root.", "content": "", "path": relative_path}

    if not target.exists() or not target.is_file():
        return {"ok": False, "error": "File does not exist.", "content": "", "path": relative_path}

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "File is not UTF-8 text.", "content": "", "path": relative_path}

    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n...[truncated]..."

    return {"ok": True, "error": None, "content": content, "path": relative_path}
