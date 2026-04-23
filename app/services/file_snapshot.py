import hashlib
from datetime import datetime, UTC
from pathlib import Path

from app.db import SessionLocal
from app.models import FileSnapshot, FileTreeEntry
from sqlalchemy import text

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "venv",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture_tree_snapshot(project_id: int, root_path: str, max_items: int = 500):
    root = Path(root_path).expanduser().resolve()
    if not root.exists():
        return 0

    db = SessionLocal()
    try:
        now = datetime.now(UTC)

        result = db.execute(
            text(
                "INSERT INTO tree_snapshots (project_id, root_path, item_count, captured_at) VALUES (:p, :r, 0, :t)"
            ),
            {"p": project_id, "r": str(root), "t": now},
        )

        snapshot_id = result.lastrowid
        count = 0

        for path in sorted(root.rglob("*")):
            if count >= max_items:
                break

            rel = path.relative_to(root)
            parts = rel.parts
            if any(p in IGNORED_DIRS for p in parts):
                continue

            entry_type = "dir" if path.is_dir() else "file"

            sha256 = None
            content = None

            if path.is_file():
                try:
                    raw = path.read_bytes()
                    sha256 = _sha256_bytes(raw)

                    if path.suffix in [".py", ".html", ".css", ".js", ".json", ".txt"]:
                        content = raw.decode("utf-8", errors="ignore")[:50000]

                except Exception:
                    continue

            db.execute(
                text(
                    "INSERT INTO file_tree_entries (snapshot_id, path, entry_type, sha256) VALUES (:s, :p, :t, :h)"
                ),
                {"s": snapshot_id, "p": str(rel), "t": entry_type, "h": sha256},
            )

            if content:
                db.execute(
                    text(
                        "INSERT INTO file_snapshots (snapshot_id, path, sha256, content_text) VALUES (:s, :p, :h, :c)"
                    ),
                    {"s": snapshot_id, "p": str(rel), "h": sha256, "c": content},
                )

            count += 1

        db.execute(
            text("UPDATE tree_snapshots SET item_count = :c WHERE id = :id"),
            {"c": count, "id": snapshot_id},
        )

        db.commit()
        return count

    finally:
        db.close()
