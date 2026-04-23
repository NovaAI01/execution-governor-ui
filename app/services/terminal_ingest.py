import json
from pathlib import Path

from app.db import SessionLocal
from app.models import WorkLog


AUDIT_DIR = Path.home() / "terminal_audit" / "sessions"


def ingest_latest_session(project_id: int) -> int:
    db = SessionLocal()
    try:
        if not AUDIT_DIR.exists():
            return 0

        session_files = sorted(AUDIT_DIR.glob("**/*.jsonl"), reverse=True)
        if not session_files:
            return 0

        latest_file = session_files[0]
        count = 0

        with latest_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                cmd = str(data.get("cmd", "")).strip()
                if not cmd:
                    continue

                ts_value = data.get("ts")

                log = WorkLog(
                    project_id=project_id,
                    source="terminal",
                    command_text=cmd,
                    notes=f"auto-ingested from {latest_file.name}",
                )

                if ts_value:
                    log.ts = ts_value

                db.add(log)
                count += 1

        db.commit()
        return count
    finally:
        db.close()
