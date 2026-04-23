from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import SessionLocal
from app.models import Capability, Mandate
from app.routes.projects import get_project_or_none

router = APIRouter()


@router.get("/projects/{project_id}/capabilities", response_class=HTMLResponse)
def capabilities(request: Request, project_id: int):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        capabilities = (
            db.query(Capability)
            .filter(Capability.project_id == project_id)
            .order_by(Capability.created_at.desc(), Capability.id.desc())
            .all()
        )
    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "capabilities.html",
        {
            "page_title": "Capability Registry",
            "project": project,
            "capabilities": capabilities,
        },
    )


@router.post("/projects/{project_id}/capabilities")
def create_capability(
    project_id: int,
    title: str = Form(...),
    outcome: str = Form(...),
    acceptance_criteria: str = Form(...),
):
    db = SessionLocal()
    try:
        project = get_project_or_none(db, project_id)
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        capability = Capability(
            project_id=project.id,
            title=title.strip(),
            outcome=outcome.strip(),
            acceptance_criteria=acceptance_criteria.strip(),
            status="draft",
        )
        db.add(capability)
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}/capabilities", status_code=303)


@router.post("/projects/{project_id}/capabilities/{capability_id}/activate")
def activate_capability(project_id: int, capability_id: int):
    db = SessionLocal()
    try:
        capability = (
            db.query(Capability)
            .filter(Capability.id == capability_id, Capability.project_id == project_id)
            .first()
        )
        if not capability:
            return RedirectResponse(
                url=f"/projects/{project_id}/capabilities?error=capability-not-found",
                status_code=303,
            )
        if capability.status != "draft":
            return RedirectResponse(
                url=f"/projects/{project_id}/capabilities?error=invalid-capability-transition",
                status_code=303,
            )

        existing_active = (
            db.query(Capability)
            .filter(Capability.project_id == project_id, Capability.status == "active")
            .first()
        )
        if existing_active:
            return RedirectResponse(
                url=f"/projects/{project_id}/capabilities?error=active-capability-exists",
                status_code=303,
            )

        capability.status = "active"
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}/capabilities", status_code=303)


@router.post("/projects/{project_id}/capabilities/{capability_id}/complete")
def complete_capability(project_id: int, capability_id: int):
    db = SessionLocal()
    try:
        capability = (
            db.query(Capability)
            .filter(Capability.id == capability_id, Capability.project_id == project_id)
            .first()
        )
        if not capability:
            return RedirectResponse(
                url=f"/projects/{project_id}/capabilities?error=capability-not-found",
                status_code=303,
            )
        if capability.status != "active":
            return RedirectResponse(
                url=f"/projects/{project_id}/capabilities?error=invalid-capability-transition",
                status_code=303,
            )

        active_mandate = (
            db.query(Mandate)
            .filter(Mandate.capability_id == capability.id, Mandate.status == "active")
            .first()
        )
        if active_mandate:
            return RedirectResponse(
                url=f"/projects/{project_id}/capabilities?error=capability-has-active-mandate&mandate_title={active_mandate.title}",
                status_code=303,
            )

        capability.status = "completed"
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}/capabilities", status_code=303)


@router.post("/projects/{project_id}/capabilities/{capability_id}/delete")
def delete_capability(project_id: int, capability_id: int):
    db = SessionLocal()
    try:
        capability = (
            db.query(Capability)
            .filter(Capability.id == capability_id, Capability.project_id == project_id)
            .first()
        )
        if not capability:
            return RedirectResponse(
                url=f"/projects/{project_id}/capabilities?error=capability-not-found",
                status_code=303,
            )
        if capability.status != "draft":
            return RedirectResponse(
                url=f"/projects/{project_id}/capabilities?error=only-draft-can-delete",
                status_code=303,
            )

        db.delete(capability)
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/projects/{project_id}/capabilities", status_code=303)
