import sqlite3
from pathlib import Path

DB_PATH = Path("data/app.db")


def column_names(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row[1] for row in rows]


def main():
    if not DB_PATH.exists():
        raise SystemExit("Database file not found: data/app.db")

    conn = sqlite3.connect(DB_PATH)
    try:
        cols = column_names(conn, "observation_runs")

        required = {
            "unresolved_link_count": "INTEGER NOT NULL DEFAULT 0",
            "included_file_count": "INTEGER NOT NULL DEFAULT 0",
            "excluded_file_count": "INTEGER NOT NULL DEFAULT 0",
            "max_files_limit": "INTEGER NOT NULL DEFAULT 500",
            "failure_reason": "TEXT",
        }

        added = []

        for name, ddl in required.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE observation_runs ADD COLUMN {name} {ddl}")
                added.append(name)

        conn.commit()

        print("ADDED_COLUMNS", added)
        print("FINAL_COLUMNS", column_names(conn, "observation_runs"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
