import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import SessionLocal
from app.models import (
    Capability,
    ComponentLink,
    Mandate,
    ObservationMap,
    ObservationRun,
    ObservedComponent,
    ObservedFile,
    Project,
    WorkLog,
)
from app.services.observation_spine import capture_observation_run

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

        latest_run = (
            db.query(ObservationRun)
            .filter(ObservationRun.project_id == project_id)
            .order_by(ObservationRun.id.desc())
            .first()
        )

        observed_files = []
        observed_components = []
        component_links = []
        observation_maps = []

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
                }
                for row in observed_component_rows
            ]

            component_links = [
                {
                    "source_path": source_path,
                    "relation_type": link_row.relation_type,
                    "target_path": link_row.target_path,
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
            "latest_run": latest_run,
            "observed_files": observed_files,
            "observed_components": observed_components,
            "component_links": component_links,
            "observation_maps": observation_maps,
        },
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
