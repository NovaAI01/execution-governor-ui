import json

from app.db import SessionLocal
from app.models import (
    ComponentDiff,
    ComponentLink,
    FileDiff,
    LinkDiff,
    ObservationDiff,
    ObservedComponent,
    ObservedFile,
)
from app.services.timeline_core import record_project_event


def _stable_json(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _file_index(db, run_id: int):
    rows = (
        db.query(ObservedFile)
        .filter(ObservedFile.observation_run_id == run_id)
        .all()
    )
    return {
        row.path: {
            "path": row.path,
            "sha256": row.sha256,
            "file_kind": row.file_kind,
            "size_bytes": row.size_bytes,
            "line_count": row.line_count,
        }
        for row in rows
    }


def _component_index(db, run_id: int):
    rows = (
        db.query(ObservedComponent)
        .filter(ObservedComponent.observation_run_id == run_id)
        .all()
    )
    return {
        row.component_key: {
            "component_key": row.component_key,
            "component_kind": row.component_kind,
            "source_path": row.source_path,
            "layer": row.layer,
            "metadata_json": _stable_json(row.metadata_json),
        }
        for row in rows
    }


def _link_index(db, run_id: int):
    rows = (
        db.query(ComponentLink, ObservedComponent.source_path)
        .join(
            ObservedComponent,
            ComponentLink.source_component_id == ObservedComponent.id,
        )
        .filter(ComponentLink.observation_run_id == run_id)
        .all()
    )

    result = {}
    for link_row, source_path in rows:
        metadata = _stable_json(link_row.metadata_json)
        key = f"{source_path}|{link_row.relation_type}|{link_row.target_path or ''}"
        result[key] = {
            "link_key": key,
            "source_path": source_path,
            "relation_type": link_row.relation_type,
            "target_path": link_row.target_path,
            "metadata_json": metadata,
        }
    return result


def compare_observation_runs(project_id: int, from_run_id: int, to_run_id: int) -> dict:
    db = SessionLocal()
    try:
        from_files = _file_index(db, from_run_id)
        to_files = _file_index(db, to_run_id)

        from_components = _component_index(db, from_run_id)
        to_components = _component_index(db, to_run_id)

        from_links = _link_index(db, from_run_id)
        to_links = _link_index(db, to_run_id)

        diff = ObservationDiff(
            project_id=project_id,
            from_run_id=from_run_id,
            to_run_id=to_run_id,
            status="completed",
        )
        db.add(diff)
        db.flush()

        file_diff_count = 0
        component_diff_count = 0
        link_diff_count = 0

        file_paths = sorted(set(from_files) | set(to_files))
        for path in file_paths:
            before = from_files.get(path)
            after = to_files.get(path)

            if before and not after:
                db.add(
                    FileDiff(
                        observation_diff_id=diff.id,
                        path=path,
                        diff_type="removed",
                        from_sha256=before["sha256"],
                        to_sha256=None,
                        details_json=json.dumps(before, sort_keys=True),
                    )
                )
                file_diff_count += 1
            elif after and not before:
                db.add(
                    FileDiff(
                        observation_diff_id=diff.id,
                        path=path,
                        diff_type="added",
                        from_sha256=None,
                        to_sha256=after["sha256"],
                        details_json=json.dumps(after, sort_keys=True),
                    )
                )
                file_diff_count += 1
            elif before and after and before["sha256"] != after["sha256"]:
                db.add(
                    FileDiff(
                        observation_diff_id=diff.id,
                        path=path,
                        diff_type="changed",
                        from_sha256=before["sha256"],
                        to_sha256=after["sha256"],
                        details_json=json.dumps(
                            {"from": before, "to": after},
                            sort_keys=True,
                        ),
                    )
                )
                file_diff_count += 1

        component_keys = sorted(set(from_components) | set(to_components))
        for component_key in component_keys:
            before = from_components.get(component_key)
            after = to_components.get(component_key)

            if before and not after:
                db.add(
                    ComponentDiff(
                        observation_diff_id=diff.id,
                        component_key=component_key,
                        diff_type="removed",
                        from_component_kind=before["component_kind"],
                        to_component_kind=None,
                        details_json=json.dumps(before, sort_keys=True),
                    )
                )
                component_diff_count += 1
            elif after and not before:
                db.add(
                    ComponentDiff(
                        observation_diff_id=diff.id,
                        component_key=component_key,
                        diff_type="added",
                        from_component_kind=None,
                        to_component_kind=after["component_kind"],
                        details_json=json.dumps(after, sort_keys=True),
                    )
                )
                component_diff_count += 1
            elif before and after and before != after:
                db.add(
                    ComponentDiff(
                        observation_diff_id=diff.id,
                        component_key=component_key,
                        diff_type="changed",
                        from_component_kind=before["component_kind"],
                        to_component_kind=after["component_kind"],
                        details_json=json.dumps(
                            {"from": before, "to": after},
                            sort_keys=True,
                        ),
                    )
                )
                component_diff_count += 1

        link_keys = sorted(set(from_links) | set(to_links))
        for link_key in link_keys:
            before = from_links.get(link_key)
            after = to_links.get(link_key)

            if before and not after:
                db.add(
                    LinkDiff(
                        observation_diff_id=diff.id,
                        link_key=link_key,
                        diff_type="removed",
                        details_json=json.dumps(before, sort_keys=True),
                    )
                )
                link_diff_count += 1
            elif after and not before:
                db.add(
                    LinkDiff(
                        observation_diff_id=diff.id,
                        link_key=link_key,
                        diff_type="added",
                        details_json=json.dumps(after, sort_keys=True),
                    )
                )
                link_diff_count += 1
            elif before and after and before != after:
                db.add(
                    LinkDiff(
                        observation_diff_id=diff.id,
                        link_key=link_key,
                        diff_type="changed",
                        details_json=json.dumps(
                            {"from": before, "to": after},
                            sort_keys=True,
                        ),
                    )
                )
                link_diff_count += 1

        summary = {
            "from_run_id": from_run_id,
            "to_run_id": to_run_id,
            "file_diffs": file_diff_count,
            "component_diffs": component_diff_count,
            "link_diffs": link_diff_count,
        }

        diff.file_diff_count = file_diff_count
        diff.component_diff_count = component_diff_count
        diff.link_diff_count = link_diff_count
        diff.summary_json = json.dumps(summary, sort_keys=True)

        db.commit()

        record_project_event(
            project_id=project_id,
            event_type="comparison.created",
            related_object_type="observation_diff",
            related_object_id=diff.id,
            event_summary=f"Observation diff {diff.id} created.",
            event_payload={
                "diff_id": diff.id,
                "from_run_id": from_run_id,
                "to_run_id": to_run_id,
                "file_diff_count": file_diff_count,
                "component_diff_count": component_diff_count,
                "link_diff_count": link_diff_count,
            },
        )

        return {
            "diff_id": diff.id,
            "from_run_id": from_run_id,
            "to_run_id": to_run_id,
            "file_diff_count": file_diff_count,
            "component_diff_count": component_diff_count,
            "link_diff_count": link_diff_count,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
