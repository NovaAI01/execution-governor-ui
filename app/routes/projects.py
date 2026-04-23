import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import SessionLocal
from app.models import (
    ArchitectureState,
    Capability,
    DiffState,
    GovernorState,
    Mandate,
    ObservationRun,
    OverviewState,
    Project,
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


def require_active_mandate(project_id: int) -> str | None:
    db = SessionLocal()
    try:
        mandate = get_active_mandate_for_project(db, project_id)
        if mandate:
            return None
        return "no-active-mandate"
    finally:
        db.close()


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

        overview_state_row = (
            db.query(OverviewState)
            .filter(OverviewState.project_id == project_id)
            .order_by(OverviewState.id.desc())
            .first()
        )
        architecture_state_row = (
            db.query(ArchitectureState)
            .filter(ArchitectureState.project_id == project_id)
            .order_by(ArchitectureState.id.desc())
            .first()
        )
        diff_state_row = (
            db.query(DiffState)
            .filter(DiffState.project_id == project_id)
            .order_by(DiffState.id.desc())
            .first()
        )
        governor_state_row = (
            db.query(GovernorState)
            .filter(GovernorState.project_id == project_id)
            .order_by(GovernorState.id.desc())
            .first()
        )
    finally:
        db.close()

    overview_state = parse_json_text(overview_state_row.state_json) if overview_state_row else {}
    architecture_state = parse_json_text(architecture_state_row.state_json) if architecture_state_row else {}
    diff_state = parse_json_text(diff_state_row.state_json) if diff_state_row else {}
    governor_state = parse_json_text(governor_state_row.state_json) if governor_state_row else {}

    latest_run = (overview_state or {}).get("latest_run")
    latest_diff = (diff_state or {}).get("latest_diff")
    recent_events = (overview_state or {}).get("recent_events", [])
    scope_bindings = (overview_state or {}).get("scope_bindings", [])
    policy_rules = (overview_state or {}).get("policy_rules", [])
    latest_checks = (governor_state or {}).get("checks", [])

    observed_files = (architecture_state or {}).get("observed_files", [])
    observed_components = (architecture_state or {}).get("observed_components", [])
    component_links = (architecture_state or {}).get("component_links", [])
    observation_maps = (architecture_state or {}).get("observation_maps", [])

    file_diffs = (diff_state or {}).get("file_diffs", [])
    component_diffs = (diff_state or {}).get("component_diffs", [])
    link_diffs = (diff_state or {}).get("link_diffs", [])

    enforcement_error = request.query_params.get("error")

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
            "overview_state": overview_state,
            "architecture_state": architecture_state,
            "diff_state": diff_state,
            "governor_state": governor_state,
            "enforcement_error": enforcement_error,
        },
    )


@router.post("/projects/{project_id}/observe")
def observe_project(project_id: int):
    error = require_active_mandate(project_id)
    if error:
        return RedirectResponse(url=f"/projects/{project_id}?error={error}", status_code=303)

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

    regenerate_read_models(project_id)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/compare-latest")
def compare_latest_runs(project_id: int):
    error = require_active_mandate(project_id)
    if error:
        return RedirectResponse(url=f"/projects/{project_id}?error={error}", status_code=303)

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
    regenerate_read_models(project_id)

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/run-judgment")
def run_judgment(project_id: int):
    error = require_active_mandate(project_id)
    if error:
        return RedirectResponse(url=f"/projects/{project_id}?error={error}", status_code=303)

    run_judgment_for_latest_diff(project_id)
    regenerate_read_models(project_id)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/rebuild-read-models")
def rebuild_read_models(project_id: int):
    regenerate_read_models(project_id)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/work-log")
def create_work_log(project_id: int, command_text: str = Form(...), notes: str = Form("")):
    error = require_active_mandate(project_id)
    if error:
        return RedirectResponse(url=f"/projects/{project_id}?error={error}", status_code=303)

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
