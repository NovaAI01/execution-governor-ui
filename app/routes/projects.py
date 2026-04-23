import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import SessionLocal
from app.models import (
    ArchitectureState,
    Capability,
    ComponentDiff,
    ComponentLink,
    DiffState,
    FileDiff,
    GovernorCheck,
    GovernorState,
    LinkDiff,
    Mandate,
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
    WorkLog,
)
from app.services.comparison_core import compare_observation_runs
from app.services.judgment_core import run_judgment_for_latest_diff
from app.services.observation_spine import capture_observation_run
from app.services.read_model_core import regenerate_read_models

router = APIRouter()


def get_project_or_none(db, project_id: int):
    return db.query(Project).filter(Project.id == project_id).first()


def get_active_capability_for_project(db, project_id: int):
    return (
        db.query(Capability)
        .filter(Capability.project_id == project_id, Capability.status == "active")
        .order_by(Capability.id.desc())
        .first()
    )


def get_active_mandate_for_project(db, project_id: int):
    return (
        db.query(Mandate)
        .join(Capability, Mandate.capability_id == Capability.id)
        .filter(Capability.project_id == project_id, Mandate.status == "active")
        .order_by(Mandate.id.desc())
        .first()
    )


def parse_work_items(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass

    return [line.strip("-• ").strip() for line in text.splitlines() if line.strip()]


def parse_json_text(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


@router.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/projects", status_code=303)


@router.get("/projects", response_class=HTMLResponse)
def project_list(request: Request):
    db = SessionLocal()
    try:
        projects = db.query(Project).order_by(Project.created_at.desc(), Project.id.desc()).all()
    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "projects.html",
        {"page_title": "Projects", "projects": projects},
    )


@router.post("/projects")
def create_project(
    name: str = Form(...),
    product_idea: str = Form(...),
    excluded_scope: str = Form(...),
    completion_contract: str = Form(...),
    root_path: str = Form(""),
):
    db = SessionLocal()
    try:
        project = Project(
            name=name.strip(),
            product_idea=product_idea.strip(),
            excluded_scope=excluded_scope.strip(),
            completion_contract=completion_contract.strip(),
            root_path=root_path.strip() or None,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_overview(request: Request, project_id: int):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        active_capability = get_active_capability_for_project(db, project_id)
        active_mandate = get_active_mandate_for_project(db, project_id)
        work_items = parse_work_items(active_mandate.work_items_json) if active_mandate else []

        recent_logs = (
            db.query(WorkLog)
            .filter(WorkLog.project_id == project_id)
            .order_by(WorkLog.ts.desc(), WorkLog.id.desc())
            .limit(10)
            .all()
        )

        recent_events = [
            {
                "id": row.id,
                "event_type": row.event_type,
                "related_object_type": row.related_object_type,
                "related_object_id": row.related_object_id,
                "event_summary": row.event_summary,
                "event_payload_json": parse_json_text(row.event_payload_json),
                "created_at": row.created_at,
            }
            for row in (
                db.query(ProjectEvent)
                .filter(ProjectEvent.project_id == project_id)
                .order_by(ProjectEvent.id.desc())
                .limit(20)
                .all()
            )
        ]

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

        overview_state = (
            db.query(OverviewState)
            .filter(OverviewState.project_id == project_id)
            .order_by(OverviewState.id.desc())
            .first()
        )
        architecture_state = (
            db.query(ArchitectureState)
            .filter(ArchitectureState.project_id == project_id)
            .order_by(ArchitectureState.id.desc())
            .first()
        )
        diff_state = (
            db.query(DiffState)
            .filter(DiffState.project_id == project_id)
            .order_by(DiffState.id.desc())
            .first()
        )
        governor_state = (
            db.query(GovernorState)
            .filter(GovernorState.project_id == project_id)
            .order_by(GovernorState.id.desc())
            .first()
        )

        latest_checks = []
        scope_bindings = []
        policy_rules = []
        observed_files = []
        observed_components = []
        component_links = []
        observation_maps = []
        file_diffs = []
        component_diffs = []
        link_diffs = []

        if latest_run:
            observed_file_rows = (
                db.query(ObservedFile)
                .filter(ObservedFile.observation_run_id == latest_run.id)
                .order_by(ObservedFile.path.asc())
                .limit(40)
                .all()
            )

            observed_component_rows = (
                db.query(ObservedComponent)
                .filter(ObservedComponent.observation_run_id == latest_run.id)
                .order_by(ObservedComponent.source_path.asc())
                .limit(40)
                .all()
            )

            component_link_rows = (
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

            observation_map_rows = (
                db.query(ObservationMap)
                .filter(ObservationMap.observation_run_id == latest_run.id)
                .order_by(ObservationMap.id.asc())
                .all()
            )

            observed_files = [
                {
                    "path": row.path,
                    "file_kind": row.file_kind,
                    "size_bytes": row.size_bytes,
                    "line_count": row.line_count,
                    "sha256": row.sha256,
                }
                for row in observed_file_rows
            ]

            observed_components = [
                {
                    "component_key": row.component_key,
                    "component_kind": row.component_kind,
                    "layer": row.layer,
                    "source_path": row.source_path,
                    "metadata_json": parse_json_text(row.metadata_json),
                }
                for row in observed_component_rows
            ]

            component_links = [
                {
                    "source_path": source_path,
                    "relation_type": link_row.relation_type,
                    "target_path": link_row.target_path,
                    "metadata_json": parse_json_text(link_row.metadata_json),
                }
                for link_row, source_path in component_link_rows
            ]

            observation_maps = [
                {
                    "map_key": row.map_key,
                    "map_json": parse_json_text(row.map_json),
                }
                for row in observation_map_rows
            ]

        if latest_diff:
            file_diff_rows = (
                db.query(FileDiff)
                .filter(FileDiff.observation_diff_id == latest_diff.id)
                .order_by(FileDiff.path.asc())
                .limit(40)
                .all()
            )
            component_diff_rows = (
                db.query(ComponentDiff)
                .filter(ComponentDiff.observation_diff_id == latest_diff.id)
                .order_by(ComponentDiff.component_key.asc())
                .limit(40)
                .all()
            )
            link_diff_rows = (
                db.query(LinkDiff)
                .filter(LinkDiff.observation_diff_id == latest_diff.id)
                .order_by(LinkDiff.link_key.asc())
                .limit(40)
                .all()
            )
            latest_check_rows = (
                db.query(GovernorCheck, PolicyRule.rule_name, ScopeBinding.binding_name)
                .join(PolicyRule, GovernorCheck.policy_rule_id == PolicyRule.id)
                .join(ScopeBinding, GovernorCheck.scope_binding_id == ScopeBinding.id)
                .filter(GovernorCheck.observation_diff_id == latest_diff.id)
                .order_by(GovernorCheck.id.asc())
                .all()
            )

            file_diffs = [
                {
                    "path": row.path,
                    "diff_type": row.diff_type,
                    "from_sha256": row.from_sha256,
                    "to_sha256": row.to_sha256,
                    "details_json": parse_json_text(row.details_json),
                }
                for row in file_diff_rows
            ]
            component_diffs = [
                {
                    "component_key": row.component_key,
                    "diff_type": row.diff_type,
                    "from_component_kind": row.from_component_kind,
                    "to_component_kind": row.to_component_kind,
                    "details_json": parse_json_text(row.details_json),
                }
                for row in component_diff_rows
            ]
            link_diffs = [
                {
                    "link_key": row.link_key,
                    "diff_type": row.diff_type,
                    "details_json": parse_json_text(row.details_json),
                }
                for row in link_diff_rows
            ]
            latest_checks = [
                {
                    "id": check.id,
                    "decision": check.decision,
                    "status": check.status,
                    "rationale": check.rationale,
                    "details_json": parse_json_text(check.details_json),
                    "rule_name": rule_name,
                    "binding_name": binding_name,
                }
                for check, rule_name, binding_name in latest_check_rows
            ]

        scope_bindings = [
            {
                "id": row.id,
                "binding_name": row.binding_name,
                "included_paths_json": parse_json_text(row.included_paths_json),
                "excluded_paths_json": parse_json_text(row.excluded_paths_json),
                "notes": row.notes,
            }
            for row in db.query(ScopeBinding).filter(ScopeBinding.project_id == project_id).order_by(ScopeBinding.id.asc()).all()
        ]

        policy_rules = [
            {
                "id": row.id,
                "rule_name": row.rule_name,
                "rule_kind": row.rule_kind,
                "severity": row.severity,
                "config_json": parse_json_text(row.config_json),
            }
            for row in db.query(PolicyRule).order_by(PolicyRule.id.asc()).all()
        ]
    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "overview.html",
        {
            "page_title": f"Project Overview — {project.name}",
            "project": project,
            "active_capability": active_capability,
            "active_mandate": active_mandate,
            "work_items": work_items,
            "recent_logs": recent_logs,
            "recent_events": recent_events,
            "latest_run": latest_run,
            "latest_diff": latest_diff,
            "latest_checks": latest_checks,
            "scope_bindings": scope_bindings,
            "policy_rules": policy_rules,
            "observed_files": observed_files,
            "observed_components": observed_components,
            "component_links": component_links,
            "observation_maps": observation_maps,
            "file_diffs": file_diffs,
            "component_diffs": component_diffs,
            "link_diffs": link_diffs,
            "overview_state": parse_json_text(overview_state.state_json) if overview_state else None,
            "architecture_state": parse_json_text(architecture_state.state_json) if architecture_state else None,
            "diff_state": parse_json_text(diff_state.state_json) if diff_state else None,
            "governor_state": parse_json_text(governor_state.state_json) if governor_state else None,        },
    )


@router.post("/projects/{project_id}/observe")
def observe_project(project_id: int):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
        if not project:
            return RedirectResponse(url="/projects", status_code=303)
        if not project.root_path:
            return RedirectResponse(
                url=f"/projects/{project_id}/setup?error=no-root-path",
                status_code=303,
            )
        capture_observation_run(project.id, project.root_path)
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/compare-latest")
def compare_latest_runs(project_id: int):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        runs = (
            db.query(ObservationRun)
            .filter(ObservationRun.project_id == project_id, ObservationRun.status == "completed")
            .order_by(ObservationRun.id.desc())
            .limit(2)
            .all()
        )
    finally:
        db.close()

    if len(runs) < 2:
        return RedirectResponse(
            url=f"/projects/{project_id}?error=not-enough-runs-to-compare",
            status_code=303,
        )

    newest = runs[0]
    previous = runs[1]
    compare_observation_runs(project_id, previous.id, newest.id)

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/run-judgment")
def run_judgment(project_id: int):
    run_judgment_for_latest_diff(project_id)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/rebuild-read-models")
def rebuild_read_models(project_id: int):
    regenerate_read_models(project_id)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/work-log")
def create_work_log(project_id: int, command_text: str = Form(...), notes: str = Form("")):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        log = WorkLog(
            project_id=project.id,
            command_text=command_text.strip(),
            notes=notes.strip() or None,
            source="manual",
        )
        db.add(log)
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.get("/projects/{project_id}/setup", response_class=HTMLResponse)
def project_setup(request: Request, project_id: int):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
    finally:
        db.close()

    if not project:
        return RedirectResponse(url="/projects", status_code=303)

    return request.app.state.templates.TemplateResponse(
        request,
        "project_setup.html",
        {"page_title": "Project Setup", "project": project},
    )


@router.post("/projects/{project_id}/setup")
def save_project(
    project_id: int,
    name: str = Form(...),
    product_idea: str = Form(...),
    excluded_scope: str = Form(...),
    completion_contract: str = Form(...),
    root_path: str = Form(""),
):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        project.name = name.strip()
        project.product_idea = product_idea.strip()
        project.excluded_scope = excluded_scope.strip()
        project.completion_contract = completion_contract.strip()
        project.root_path = root_path.strip() or None
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}/setup", status_code=303)
