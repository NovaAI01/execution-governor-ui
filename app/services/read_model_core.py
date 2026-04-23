import json

from app.db import SessionLocal
from app.models import (
    ArchitectureState,
    ComponentDiff,
    ComponentLink,
    DiffState,
    FileDiff,
    GovernorCheck,
    GovernorState,
    LinkDiff,
    ObservationDiff,
    ObservationMap,
    ObservationRun,
    ObservedComponent,
    ObservedFile,
    OverviewState,
    PolicyRule,
    Project,
    ProjectEvent,
    ScopeBinding,
)


def _parse_json(raw: str | None, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def regenerate_read_models(project_id: int) -> dict:
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError("Project not found.")

        latest_run = (
            db.query(ObservationRun)
            .filter(ObservationRun.project_id == project_id)
            .order_by(ObservationRun.id.desc())
            .first()
        )

        latest_diff = (
            db.query(ObservationDiff)
            .filter(ObservationDiff.project_id == project_id)
            .order_by(ObservationDiff.id.desc())
            .first()
        )

        recent_events = (
            db.query(ProjectEvent)
            .filter(ProjectEvent.project_id == project_id)
            .order_by(ProjectEvent.id.desc())
            .limit(20)
            .all()
        )

        scope_bindings = (
            db.query(ScopeBinding)
            .filter(ScopeBinding.project_id == project_id)
            .order_by(ScopeBinding.id.asc())
            .all()
        )

        policy_rules = db.query(PolicyRule).order_by(PolicyRule.id.asc()).all()

        latest_checks = []
        file_diffs = []
        component_diffs = []
        link_diffs = []

        if latest_diff:
            latest_checks = (
                db.query(GovernorCheck)
                .filter(GovernorCheck.observation_diff_id == latest_diff.id)
                .order_by(GovernorCheck.id.asc())
                .all()
            )
            file_diffs = (
                db.query(FileDiff)
                .filter(FileDiff.observation_diff_id == latest_diff.id)
                .order_by(FileDiff.path.asc())
                .limit(40)
                .all()
            )
            component_diffs = (
                db.query(ComponentDiff)
                .filter(ComponentDiff.observation_diff_id == latest_diff.id)
                .order_by(ComponentDiff.component_key.asc())
                .limit(40)
                .all()
            )
            link_diffs = (
                db.query(LinkDiff)
                .filter(LinkDiff.observation_diff_id == latest_diff.id)
                .order_by(LinkDiff.link_key.asc())
                .limit(40)
                .all()
            )

        architecture_maps = []
        observed_files = []
        observed_components = []
        component_links = []

        if latest_run:
            architecture_maps = (
                db.query(ObservationMap)
                .filter(ObservationMap.observation_run_id == latest_run.id)
                .order_by(ObservationMap.id.asc())
                .all()
            )
            observed_files = (
                db.query(ObservedFile)
                .filter(ObservedFile.observation_run_id == latest_run.id)
                .order_by(ObservedFile.path.asc())
                .limit(40)
                .all()
            )
            observed_components = (
                db.query(ObservedComponent)
                .filter(ObservedComponent.observation_run_id == latest_run.id)
                .order_by(ObservedComponent.source_path.asc())
                .limit(40)
                .all()
            )
            component_links = (
                db.query(ComponentLink, ObservedComponent.source_path)
                .join(
                    ObservedComponent,
                    ComponentLink.source_component_id == ObservedComponent.id,
                )
                .filter(ComponentLink.observation_run_id == latest_run.id)
                .order_by(ComponentLink.id.asc())
                .limit(60)
                .all()
            )

        overview_payload = {
            "project": {
                "id": project.id,
                "name": project.name,
                "root_path": project.root_path,
                "product_idea": project.product_idea,
                "excluded_scope": project.excluded_scope,
                "completion_contract": project.completion_contract,
            },
            "latest_run": (
                {
                    "id": latest_run.id,
                    "status": latest_run.status,
                    "file_count": latest_run.file_count,
                    "component_count": latest_run.component_count,
                    "link_count": latest_run.link_count,
                    "unresolved_link_count": latest_run.unresolved_link_count,
                    "included_file_count": latest_run.included_file_count,
                    "excluded_file_count": latest_run.excluded_file_count,
                    "max_files_limit": latest_run.max_files_limit,
                    "failure_reason": latest_run.failure_reason,
                    "root_path": latest_run.root_path,
                }
                if latest_run
                else None
            ),
            "recent_events": [
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "related_object_type": row.related_object_type,
                    "related_object_id": row.related_object_id,
                    "event_summary": row.event_summary,
                    "event_payload_json": _parse_json(row.event_payload_json, {}),
                    "created_at": str(row.created_at),
                }
                for row in recent_events
            ],
            "scope_bindings": [
                {
                    "id": row.id,
                    "binding_name": row.binding_name,
                    "included_paths_json": _parse_json(row.included_paths_json, []),
                    "excluded_paths_json": _parse_json(row.excluded_paths_json, []),
                    "notes": row.notes,
                }
                for row in scope_bindings
            ],
            "policy_rules": [
                {
                    "id": row.id,
                    "rule_name": row.rule_name,
                    "rule_kind": row.rule_kind,
                    "severity": row.severity,
                    "config_json": _parse_json(row.config_json, {}),
                }
                for row in policy_rules
            ],
        }

        architecture_payload = {
            "project_id": project_id,
            "latest_run_id": latest_run.id if latest_run else None,
            "observed_files": [
                {
                    "path": row.path,
                    "file_kind": row.file_kind,
                    "size_bytes": row.size_bytes,
                    "line_count": row.line_count,
                    "sha256": row.sha256,
                }
                for row in observed_files
            ],
            "observed_components": [
                {
                    "component_key": row.component_key,
                    "component_kind": row.component_kind,
                    "layer": row.layer,
                    "source_path": row.source_path,
                    "metadata_json": _parse_json(row.metadata_json, {}),
                }
                for row in observed_components
            ],
            "component_links": [
                {
                    "source_path": source_path,
                    "relation_type": link_row.relation_type,
                    "target_path": link_row.target_path,
                    "metadata_json": _parse_json(link_row.metadata_json, {}),
                }
                for link_row, source_path in component_links
            ],
            "observation_maps": [
                {
                    "map_key": row.map_key,
                    "map_json": _parse_json(row.map_json, row.map_json),
                }
                for row in architecture_maps
            ],
        }

        diff_payload = {
            "project_id": project_id,
            "latest_diff": (
                {
                    "id": latest_diff.id,
                    "from_run_id": latest_diff.from_run_id,
                    "to_run_id": latest_diff.to_run_id,
                    "status": latest_diff.status,
                    "file_diff_count": latest_diff.file_diff_count,
                    "component_diff_count": latest_diff.component_diff_count,
                    "link_diff_count": latest_diff.link_diff_count,
                    "summary_json": _parse_json(latest_diff.summary_json, {}),
                }
                if latest_diff
                else None
            ),
            "file_diffs": [
                {
                    "path": row.path,
                    "diff_type": row.diff_type,
                    "from_sha256": row.from_sha256,
                    "to_sha256": row.to_sha256,
                    "details_json": _parse_json(row.details_json, {}),
                }
                for row in file_diffs
            ],
            "component_diffs": [
                {
                    "component_key": row.component_key,
                    "diff_type": row.diff_type,
                    "from_component_kind": row.from_component_kind,
                    "to_component_kind": row.to_component_kind,
                    "details_json": _parse_json(row.details_json, {}),
                }
                for row in component_diffs
            ],
            "link_diffs": [
                {
                    "link_key": row.link_key,
                    "diff_type": row.diff_type,
                    "details_json": _parse_json(row.details_json, {}),
                }
                for row in link_diffs
            ],
        }

        policy_rule_name_by_id = {row.id: row.rule_name for row in policy_rules}
        scope_binding_name_by_id = {row.id: row.binding_name for row in scope_bindings}

        governor_payload = {
            "project_id": project_id,
            "latest_diff_id": latest_diff.id if latest_diff else None,
            "checks": [
                {
                    "id": row.id,
                    "decision": row.decision,
                    "status": row.status,
                    "rationale": row.rationale,
                    "policy_rule_id": row.policy_rule_id,
                    "scope_binding_id": row.scope_binding_id,
                    "rule_name": policy_rule_name_by_id.get(row.policy_rule_id),
                    "binding_name": scope_binding_name_by_id.get(row.scope_binding_id),
                    "details_json": _parse_json(row.details_json, {}),
                }
                for row in latest_checks
            ],
        }

        db.query(OverviewState).filter(OverviewState.project_id == project_id).delete()
        db.query(ArchitectureState).filter(ArchitectureState.project_id == project_id).delete()
        db.query(DiffState).filter(DiffState.project_id == project_id).delete()
        db.query(GovernorState).filter(GovernorState.project_id == project_id).delete()

        db.add(
            OverviewState(
                project_id=project_id,
                state_json=json.dumps(overview_payload, sort_keys=True),
            )
        )
        db.add(
            ArchitectureState(
                project_id=project_id,
                state_json=json.dumps(architecture_payload, sort_keys=True),
            )
        )
        db.add(
            DiffState(
                project_id=project_id,
                state_json=json.dumps(diff_payload, sort_keys=True),
            )
        )
        db.add(
            GovernorState(
                project_id=project_id,
                state_json=json.dumps(governor_payload, sort_keys=True),
            )
        )

        db.commit()

        return {
            "project_id": project_id,
            "overview_state": True,
            "architecture_state": True,
            "diff_state": True,
            "governor_state": True,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
