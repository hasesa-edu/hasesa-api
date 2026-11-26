"""The guide's tools: the student tracker, one student's work, feedback,
assigned units, flags and sign-offs. Guides only (users.role = 'guide')."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field

from hasesa_api.content.loader import get_content
from hasesa_api.db import DbDep
from hasesa_api.guide import service
from hasesa_api.identity.deps import GuideDep
from hasesa_api.identity.users import UserOut, user_out
from hasesa_api.learning import service as learning
from hasesa_api.learning.router import (
    AttemptRow,
    EnrollmentRow,
    ProgressOut,
    RowModel,
    SignoffRow,
    StepRow,
    UnitRow,
)
from hasesa_api.models import User
from hasesa_api.schemas import ApiModel

router = APIRouter(prefix="/guide", tags=["guide"])

NOT_FOUND = "Student not found."


# ---------- shapes ----------


class RosterStudent(RowModel):
    id: str
    display_name: str
    email: str
    paid_until: datetime | None


class RosterAttempt(RowModel):
    user_id: str
    unit_id: str
    question_id: str
    correct: bool
    created_at: datetime


class RosterOut(ApiModel):
    """Raw progress for every student on the tracker. The website summarises it
    (lib/summary.ts) until that logic moves here with analytics in phase 7."""

    students: list[RosterStudent]
    enrollments: list[EnrollmentRow]
    steps: list[StepRow]
    units: list[UnitRow]
    signoffs: list[SignoffRow]
    attempts: list[RosterAttempt]


class StudentOut(ApiModel):
    user: UserOut
    progress: ProgressOut
    # Newest first.
    attempts: list[AttemptRow]


class FeedbackIn(ApiModel):
    body: str = Field(max_length=20_000)
    module_id: str | None = Field(default=None, max_length=200)
    step_id: str | None = Field(default=None, max_length=200)


class AssignIn(ApiModel):
    unit_id: str = Field(max_length=200)
    note: str | None = Field(default=None, max_length=5_000)


class FlagIn(ApiModel):
    flagged: bool
    note: str | None = Field(default=None, max_length=5_000)


class SignoffIn(ApiModel):
    module_id: str = Field(max_length=200)
    checks: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=100)]
    note: str | None = Field(default=None, max_length=10_000)


class CreatedOut(ApiModel):
    id: str


class SignoffOut(ApiModel):
    certificate_code: str


def _trim(value: str | None, limit: int) -> str | None:
    """Trim and cut to length; empty becomes None (as the website's forms did)."""
    return (value or "").strip()[:limit] or None


async def _require_student(db: DbDep, student_id: str) -> None:
    if not await service.student_exists(db, student_id):
        raise HTTPException(status_code=404, detail=NOT_FOUND)


# ---------- reading ----------


@router.get("/roster")
async def roster(guide: GuideDep, db: DbDep, response: Response) -> RosterOut:
    """Everyone enrolled now, plus anyone who has started a module."""
    response.headers["Cache-Control"] = "private, no-store"
    r = await service.roster_data(db)
    return RosterOut.model_validate(r, from_attributes=True)


@router.get("/students/{student_id}")
async def student(student_id: str, guide: GuideDep, db: DbDep, response: Response) -> StudentOut:
    """One student's account, progress and every answer they've given."""
    response.headers["Cache-Control"] = "private, no-store"
    u = await db.get(User, student_id)
    if u is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    state = await learning.get_student_state(db, student_id)
    attempts = await service.student_attempts(db, student_id)
    return StudentOut(
        user=user_out(u),
        progress=ProgressOut.model_validate(state, from_attributes=True),
        attempts=[AttemptRow.model_validate(a) for a in attempts],
    )


# ---------- feedback and assigned units ----------


@router.post("/students/{student_id}/feedback", status_code=201)
async def give_feedback(student_id: str, body: FeedbackIn, guide: GuideDep, db: DbDep) -> CreatedOut:
    """A note the student sees on their dashboard, optionally about a module or one of its steps."""
    text = _trim(body.body, service.MAX_FEEDBACK)
    if not text:
        raise HTTPException(status_code=400, detail="Write some feedback first.")
    await _require_student(db, student_id)
    m = get_content().module(body.module_id) if body.module_id else None
    step = next((s for s in m.steps if s.id == body.step_id), None) if m and body.step_id else None
    fid = await service.give_feedback(db, guide.id, student_id, text, m.id if m else None, step.id if step else None)
    return CreatedOut(id=fid)


@router.post("/students/{student_id}/assignments", status_code=201)
async def assign_unit(student_id: str, body: AssignIn, guide: GuideDep, db: DbDep) -> CreatedOut:
    if body.unit_id not in get_content().concepts:
        raise HTTPException(status_code=400, detail="Pick a concept unit.")
    await _require_student(db, student_id)
    aid = await service.assign_unit(
        db, guide.id, student_id, body.unit_id, _trim(body.note, service.MAX_ASSIGNMENT_NOTE)
    )
    return CreatedOut(id=aid)


@router.delete("/students/{student_id}/assignments/{assignment_id}", status_code=204)
async def remove_assignment(student_id: str, assignment_id: str, guide: GuideDep, db: DbDep) -> Response:
    await service.remove_assignment(db, student_id, assignment_id)
    return Response(status_code=204)


# ---------- flags and sign-offs ----------


@router.put("/students/{student_id}/modules/{module_id}/flag", status_code=204)
async def set_flag(student_id: str, module_id: str, body: FlagIn, guide: GuideDep, db: DbDep) -> Response:
    """Flag a student's module for attention (or clear the flag)."""
    if get_content().module(module_id) is None:
        raise HTTPException(status_code=400, detail="Unknown module.")
    note = _trim(body.note, service.MAX_FLAG_NOTE)
    if not await service.set_flag(db, student_id, module_id, body.flagged, note):
        raise HTTPException(status_code=409, detail="The student hasn't started this module.")
    return Response(status_code=204)


@router.post("/students/{student_id}/signoffs")
async def sign_off(student_id: str, body: SignoffIn, guide: GuideDep, db: DbDep) -> SignoffOut:
    """Sign off a module once every checklist item is ticked. The certificate is ready at once."""
    m = get_content().module(body.module_id)
    if m is None:
        raise HTTPException(status_code=400, detail="Unknown module.")
    await _require_student(db, student_id)
    missing = [s for s in m.signoff if s.id not in body.checks]
    if missing:
        raise HTTPException(status_code=400, detail=f"Tick every item before signing off ({len(missing)} left).")
    code = await service.sign_off(db, guide.id, student_id, m, _trim(body.note, service.MAX_SIGNOFF_NOTE))
    return SignoffOut(certificate_code=code)


@router.delete("/students/{student_id}/signoffs/{module_id}", status_code=204)
async def undo_sign_off(student_id: str, module_id: str, guide: GuideDep, db: DbDep) -> Response:
    """Withdraw a sign-off: the certificate stops working and the module is active again."""
    await service.undo_sign_off(db, student_id, module_id)
    return Response(status_code=204)
