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
        statements = [
            """
            CREATE TABLE IF NOT EXISTS overview_state (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                generated_at DATETIME NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS architecture_state (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                generated_at DATETIME NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS diff_state (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                generated_at DATETIME NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS governor_state (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                generated_at DATETIME NOT NULL
            )
            """,
        ]

        for stmt in statements:
            conn.execute(stmt)

        conn.commit()

        print("overview_state", table_exists(conn, "overview_state"))
        print("architecture_state", table_exists(conn, "architecture_state"))
        print("diff_state", table_exists(conn, "diff_state"))
        print("governor_state", table_exists(conn, "governor_state"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
