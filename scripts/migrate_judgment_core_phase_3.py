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
            CREATE TABLE IF NOT EXISTS scope_bindings (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                binding_name VARCHAR(255) NOT NULL,
                included_paths_json TEXT NOT NULL DEFAULT '[]',
                excluded_paths_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT,
                created_at DATETIME NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS policy_rules (
                id INTEGER PRIMARY KEY,
                rule_name VARCHAR(255) NOT NULL UNIQUE,
                rule_kind VARCHAR(64) NOT NULL,
                severity VARCHAR(32) NOT NULL DEFAULT 'info',
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS governor_checks (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                observation_diff_id INTEGER NOT NULL,
                scope_binding_id INTEGER NOT NULL,
                policy_rule_id INTEGER NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'completed',
                decision VARCHAR(32) NOT NULL,
                rationale TEXT NOT NULL,
                details_json TEXT,
                created_at DATETIME NOT NULL
            )
            """,
        ]

        for stmt in statements:
            conn.execute(stmt)

        conn.commit()

        print("scope_bindings", table_exists(conn, "scope_bindings"))
        print("policy_rules", table_exists(conn, "policy_rules"))
        print("governor_checks", table_exists(conn, "governor_checks"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
