import json

from app.db import SessionLocal
from app.models import ProjectEvent


def record_project_event(
    project_id: int,
    event_type: str,
    related_object_type: str | None,
    related_object_id: int | None,
    event_summary: str,
    event_payload: dict | None = None,
) -> int:
    db = SessionLocal()
    try:
        row = ProjectEvent(
            project_id=project_id,
            event_type=event_type,
            related_object_type=related_object_type,
            related_object_id=related_object_id,
            event_summary=event_summary,
            event_payload_json=json.dumps(event_payload or {}, sort_keys=True),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()
