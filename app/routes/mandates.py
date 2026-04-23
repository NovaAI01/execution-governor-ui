from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import SessionLocal
from app.models import Mandate
from app.routes.projects import (
    get_active_capability_for_project,
    get_active_mandate_for_project,
    get_project_or_none,
)

router = APIRouter()


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


@router.get("/projects/{project_id}/mandates", response_class=HTMLResponse)
def mandates(request: Request, project_id: int):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        active_capability = get_active_capability_for_project(db, project_id)
        mandates = []
        if active_capability:
            mandates = (
                db.query(Mandate)
                .filter(Mandate.capability_id == active_capability.id)
                .order_by(Mandate.created_at.desc(), Mandate.id.desc())
                .all()
            )
    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "mandates.html",
        {
            "page_title": "Mandate Registry",
            "project": project,
            "mandates": mandates,
            "active_capability": active_capability,
        },
    )


@router.post("/projects/{project_id}/mandates")
def create_mandate(
    project_id: int,
    title: str = Form(...),
    objective: str = Form(...),
    work_items: str = Form(...),
    evidence_summary: str = Form(...),
):
    db = SessionLocal()
    try:
        active_capability = get_active_capability_for_project(db, project_id)
        if not active_capability:
            return RedirectResponse(
                url=f"/projects/{project_id}/mandates?error=no-active-capability",
                status_code=303,
            )

        mandate = Mandate(
            capability_id=active_capability.id,
            title=title.strip(),
            objective=objective.strip(),
            work_items_json=json.dumps(parse_work_items(work_items)),
            evidence_summary=evidence_summary.strip(),
            status="draft",
        )
        db.add(mandate)
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}/mandates", status_code=303)


@router.post("/projects/{project_id}/mandates/{mandate_id}/activate")
def activate_mandate(project_id: int, mandate_id: int):
    db = SessionLocal()
    try:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        if not mandate:
            return RedirectResponse(
                url=f"/projects/{project_id}/mandates?error=mandate-not-found",
                status_code=303,
            )
        if mandate.status != "draft":
            return RedirectResponse(
                url=f"/projects/{project_id}/mandates?error=invalid-mandate-transition",
                status_code=303,
            )

        active_capability = get_active_capability_for_project(db, project_id)
        if not active_capability:
            return RedirectResponse(
                url=f"/projects/{project_id}/mandates?error=no-active-capability",
                status_code=303,
            )
        if mandate.capability_id != active_capability.id:
            return RedirectResponse(
                url=f"/projects/{project_id}/mandates?error=mandate-outside-active-capability",
                status_code=303,
            )

        existing_active = get_active_mandate_for_project(db, project_id)
        if existing_active:
            return RedirectResponse(
                url=f"/projects/{project_id}/mandates?error=active-mandate-exists&blocking_title={existing_active.title}",
                status_code=303,
            )

        mandate.status = "active"
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}/mandates", status_code=303)


@router.post("/projects/{project_id}/mandates/{mandate_id}/complete")
def complete_mandate(project_id: int, mandate_id: int):
    db = SessionLocal()
    try:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        if not mandate:
            return RedirectResponse(
                url=f"/projects/{project_id}/mandates?error=mandate-not-found",
                status_code=303,
            )
        if mandate.status != "active":
            return RedirectResponse(
                url=f"/projects/{project_id}/mandates?error=invalid-mandate-transition",
                status_code=303,
            )

        mandate.status = "completed"
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}/mandates", status_code=303)
