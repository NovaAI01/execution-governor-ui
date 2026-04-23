import json

from app.db import SessionLocal
from app.models import (
    ArchitectureState,
    DiffState,
    GovernorCheck,
    GovernorState,
    ObservationDiff,
    ObservationMap,
    ObservationRun,
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
        if latest_diff:
            latest_checks = (
                db.query(GovernorCheck)
                .filter(GovernorCheck.observation_diff_id == latest_diff.id)
                .order_by(GovernorCheck.id.asc())
                .all()
            )

        architecture_maps = []
        if latest_run:
            architecture_maps = (
                db.query(ObservationMap)
                .filter(ObservationMap.observation_run_id == latest_run.id)
                .order_by(ObservationMap.id.asc())
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
                }
                if latest_run
                else None
            ),
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
            "recent_event_count": len(recent_events),
            "scope_binding_count": len(scope_bindings),
            "policy_rule_count": len(policy_rules),
            "governor_check_count": len(latest_checks),
        }

        architecture_payload = {
            "project_id": project_id,
            "latest_run_id": latest_run.id if latest_run else None,
            "maps": [
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
        }

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
