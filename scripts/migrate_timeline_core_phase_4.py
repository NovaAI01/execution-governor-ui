import sqlite3
from pathlib import Path

DB_PATH = Path("data/app.db")


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def main():
    if not DB_PATH.exists():
        raise SystemExit("Database file not found: data/app.db")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_events (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                event_type VARCHAR(64) NOT NULL,
                related_object_type VARCHAR(64),
                related_object_id INTEGER,
                event_summary TEXT NOT NULL,
                event_payload_json TEXT,
                created_at DATETIME NOT NULL
            )
            """
        )
        conn.commit()

        print("project_events", table_exists(conn, "project_events"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
