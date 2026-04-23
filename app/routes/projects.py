from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import SessionLocal
from app.models import Capability, FileSnapshot, FileTreeEntry, Mandate, Project, WorkLog
from app.services.file_snapshot import capture_tree_snapshot
from app.services.file_tree import read_project_file, scan_project_tree
from app.services.code_graph import build_code_graph

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
    import json

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
def project_overview(request: Request, project_id: int, file_path: str | None = None):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        active_capability = get_active_capability_for_project(db, project_id)
        active_mandate = get_active_mandate_for_project(db, project_id)
        work_items = parse_work_items(active_mandate.work_items_json) if active_mandate else []

        completed_mandates_raw = (
            db.query(Mandate)
            .join(Capability, Mandate.capability_id == Capability.id)
            .filter(Capability.project_id == project_id, Mandate.status == "completed")
            .order_by(Mandate.created_at.desc(), Mandate.id.desc())
            .all()
        )

        recent_logs = (
            db.query(WorkLog)
            .filter(WorkLog.project_id == project_id)
            .order_by(WorkLog.ts.desc(), WorkLog.id.desc())
            .limit(10)
            .all()
        )

        tree_data = scan_project_tree(project.root_path)
        file_preview = read_project_file(project.root_path, file_path) if file_path else None

        draft_capability_count = db.query(Capability).filter(
            Capability.project_id == project_id,
            Capability.status == "draft",
        ).count()

        active_capability_count = db.query(Capability).filter(
            Capability.project_id == project_id,
            Capability.status == "active",
        ).count()

        active_mandate_count = (
            db.query(Mandate)
            .join(Capability, Mandate.capability_id == Capability.id)
            .filter(Capability.project_id == project_id, Mandate.status == "active")
            .count()
        )

        completed_mandates = []
        for mandate in completed_mandates_raw:
            completed_mandates.append(
                {
                    "id": mandate.id,
                    "title": mandate.title,
                    "objective": mandate.objective,
                    "evidence_summary": mandate.evidence_summary,
                    "status": mandate.status,
                    "work_items": parse_work_items(mandate.work_items_json),
                }
            )
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
            "completed_mandates": completed_mandates,
            "draft_capability_count": draft_capability_count,
            "active_capability_count": active_capability_count,
            "active_mandate_count": active_mandate_count,
            "recent_logs": recent_logs,
            "tree_data": tree_data,
            "file_preview": file_preview,
            "selected_file_path": file_path,
        },
    )


@router.post("/projects/{project_id}/capture-tree")
def capture_tree(project_id: int):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
    finally:
        db.close()

    if not project or not project.root_path:
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)

    count = capture_tree_snapshot(project_id, project.root_path)
    return RedirectResponse(url=f"/projects/{project_id}?captured_tree={count}", status_code=303)



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

@router.post("/projects/{project_id}/ingest-terminal")
def ingest_terminal(project_id: int):
    from app.services.terminal_ingest import ingest_latest_session

    count = ingest_latest_session(project_id)
    return RedirectResponse(url=f"/projects/{project_id}?ingested={count}", status_code=303)


@router.get("/projects/{project_id}/code-graph", response_class=HTMLResponse)
def code_graph_view(request: Request, project_id: int, scope: str = "all", focus: str | None = None):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
    finally:
        db.close()

    if not project:
        return RedirectResponse(url="/projects", status_code=303)

    graph_data = build_code_graph(project.root_path, scope=scope, focus=focus)

    return request.app.state.templates.TemplateResponse(
        request,
        "code_graph.html",
        {
            "page_title": f"Code Graph — {project.name}",
            "project": project,
            "graph_data": graph_data,
        },
    )


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


@router.get("/projects/{project_id}/file-preview", response_class=HTMLResponse)
def file_preview_partial(request: Request, project_id: int, file_path: str):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
    finally:
        db.close()

    if not project:
        return HTMLResponse("<div class='empty-state'>Project not found.</div>", status_code=404)

    preview = read_project_file(project.root_path, file_path)

    return request.app.state.templates.TemplateResponse(
        request,
        "partials/file_preview.html",
        {
            "project": project,
            "file_preview": preview,
        },
    )


@router.get("/projects/{project_id}/snapshots", response_class=HTMLResponse)
def snapshot_list(request: Request, project_id: int):
    db = SessionLocal()
    try:
        rows = db.execute(
            "SELECT id, captured_at, item_count FROM tree_snapshots WHERE project_id = ? ORDER BY id DESC",
            (project_id,),
        ).fetchall()
    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "snapshots.html",
        {
            "project_id": project_id,
            "snapshots": rows,
        },
    )


@router.get("/projects/{project_id}/snapshots/{snapshot_id}", response_class=HTMLResponse)
def snapshot_detail(request: Request, project_id: int, snapshot_id: int):
    db = SessionLocal()
    try:
        entries = db.execute(
            "SELECT path, entry_type FROM file_tree_entries WHERE snapshot_id = ? ORDER BY path",
            (snapshot_id,),
        ).fetchall()
    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "snapshot_detail.html",
        {
            "snapshot_id": snapshot_id,
            "entries": entries,
        },
    )
