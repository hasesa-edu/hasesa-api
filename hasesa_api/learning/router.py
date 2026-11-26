"""Learning: answers, test-outs, steps, enrolments, progress and certificates.

Answers are checked here, so they never reach an app before the student has
tried. Practice and test-outs on public units work signed out (the landing
page's challenge); everything else needs a signed-in student.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import Field

from hasesa_api.access import access_level, has_full_access
from hasesa_api.content.loader import get_content
from hasesa_api.content.models import Concept
from hasesa_api.db import DbDep
from hasesa_api.identity.deps import CurrentUserDep, OptionalUserDep
from hasesa_api.learning import service
from hasesa_api.learning.grade import answer_text, is_correct
from hasesa_api.models import User
from hasesa_api.schemas import ApiModel

router = APIRouter(tags=["learning"])

LOCKED = "Enrol at the Academy to unlock this."


# ---------- request and response shapes ----------


class AttemptIn(ApiModel):
    unit_id: str = Field(max_length=200)
    question_id: str = Field(max_length=200)
    # Longer than 200 characters gets "Enter an answer", as on the website.
    answer: str = Field(max_length=10_000)


class UnitStateOut(ApiModel):
    status: Literal["started", "completed", "tested_out"]
    score: int


class AttemptOut(ApiModel):
    correct: bool
    explanation: str
    answer: str
    unit: UnitStateOut | None


class TestOutIn(ApiModel):
    unit_id: str = Field(max_length=200)
    # Values that aren't strings count as unanswered, as on the website.
    answers: Annotated[dict[str, Any], Field(max_length=100)]


class TestOutResultOut(ApiModel):
    id: str
    correct: bool
    explanation: str
    answer: str


class TestOutOut(ApiModel):
    score: int
    passed: bool
    results: list[TestOutResultOut]
    unit: UnitStateOut | None


class StepIn(ApiModel):
    module_id: str = Field(max_length=200)
    step_id: str = Field(max_length=200)
    done: bool | None = None
    # Longer notes are cut to 4000 characters after trimming, as on the website.
    notes: str | None = Field(default=None, max_length=20_000)


class StepStateOut(ApiModel):
    done: bool
    notes: str | None


class StepOut(ApiModel):
    step: StepStateOut


class EnrollIn(ApiModel):
    module_id: str = Field(max_length=200)
    action: Literal["start", "drop"]


class EnrollOut(ApiModel):
    status: str


class RowModel(ApiModel):
    model_config = ApiModel.model_config | {"from_attributes": True}


class EnrollmentRow(RowModel):
    user_id: str
    module_id: str
    status: str
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    flagged: bool
    flag_note: str | None


class StepRow(RowModel):
    user_id: str
    module_id: str
    step_id: str
    done: bool
    notes: str | None
    updated_at: datetime
    completed_at: datetime | None


class UnitRow(RowModel):
    user_id: str
    unit_id: str
    status: str
    score: int
    updated_at: datetime
    completed_at: datetime | None


class SignoffRow(RowModel):
    user_id: str
    module_id: str
    checks: list[str]
    note: str | None
    guide_id: str
    signed_at: datetime
    certificate_code: str


class FeedbackRow(RowModel):
    id: str
    student_id: str
    guide_id: str
    module_id: str | None
    step_id: str | None
    body: str
    created_at: datetime
    read_at: datetime | None


class AssignmentRow(RowModel):
    id: str
    student_id: str
    unit_id: str
    note: str | None
    guide_id: str
    created_at: datetime


class AttemptRow(RowModel):
    id: str
    user_id: str
    unit_id: str
    question_id: str
    answer: str
    correct: bool
    mode: str
    created_at: datetime


class ProgressOut(ApiModel):
    enrollments: list[EnrollmentRow]
    steps: list[StepRow]
    units: list[UnitRow]
    signoffs: list[SignoffRow]
    feedback: list[FeedbackRow]
    assignments: list[AssignmentRow]


class CertificateOut(ApiModel):
    module_id: str
    signed_at: datetime
    note: str | None
    code: str
    student: str
    guide: str


# ---------- helpers ----------


def _full(user: User) -> bool:
    return has_full_access(access_level(user.role, user.paid_until))


def _unit_for(unit_id: str, user: User | None) -> Concept:
    concept = service.find_concept(unit_id)
    if concept is None:
        raise HTTPException(status_code=400, detail="Unknown unit")
    if not concept.public and (user is None or not _full(user)):
        raise HTTPException(status_code=403, detail=LOCKED)
    return concept


def _require_full(user: User) -> None:
    if not _full(user):
        raise HTTPException(status_code=403, detail=LOCKED)


def _unit_out(u: service.UnitState | None) -> UnitStateOut | None:
    return UnitStateOut(status=u.status, score=u.score) if u else None  # type: ignore[arg-type]


# ---------- answers ----------


@router.post("/attempts")
async def attempt(body: AttemptIn, user: OptionalUserDep, db: DbDep) -> AttemptOut:
    """Check one practice answer. Saved to the student's progress when signed in."""
    concept = _unit_for(body.unit_id, user)
    problem = next((p for p in concept.problems if p.id == body.question_id), None)
    if problem is None:
        raise HTTPException(status_code=400, detail="Unknown question")
    if not body.answer.strip() or len(body.answer) > service.MAX_ANSWER:
        raise HTTPException(status_code=400, detail="Enter an answer")
    correct = is_correct(problem, body.answer)
    unit = await service.record_attempt(db, user.id, concept, problem, body.answer, correct) if user else None
    return AttemptOut(
        correct=correct, explanation=problem.explanation, answer=answer_text(problem), unit=_unit_out(unit)
    )


@router.post("/attempts/testout")
async def test_out(body: TestOutIn, user: OptionalUserDep, db: DbDep) -> TestOutOut:
    """Grade a whole unit at once. Passing (80%) marks the unit tested out."""
    concept = _unit_for(body.unit_id, user)
    r = await service.grade_test_out(db, user.id if user else None, concept, body.answers)
    return TestOutOut(
        score=r.score,
        passed=r.passed,
        results=[
            TestOutResultOut(
                id=x.problem.id, correct=x.correct, explanation=x.problem.explanation, answer=answer_text(x.problem)
            )
            for x in r.results
        ],
        unit=_unit_out(r.unit),
    )


# ---------- the signed-in student's progress ----------


@router.get("/me/progress")
async def my_progress(user: CurrentUserDep, db: DbDep, response: Response) -> ProgressOut:
    """Enrolments, steps, units, sign-offs, the latest 50 guide notes and assigned units."""
    response.headers["Cache-Control"] = "private, no-store"
    s = await service.get_student_state(db, user.id)
    return ProgressOut.model_validate(s, from_attributes=True)


@router.get("/me/attempts")
async def my_attempts(
    user: CurrentUserDep,
    db: DbDep,
    response: Response,
    unit_id: Annotated[list[str] | None, Query(alias="unitId", max_length=50)] = None,
) -> list[AttemptRow]:
    """Every answer the student has given, oldest first. Filter with ?unitId=a&unitId=b."""
    response.headers["Cache-Control"] = "private, no-store"
    rows = await service.get_attempts(db, user.id, unit_id)
    return [AttemptRow.model_validate(r) for r in rows]


@router.post("/me/steps")
async def save_step(body: StepIn, user: CurrentUserDep, db: DbDep) -> StepOut:
    """Tick a step done (or not) and save its notebook notes."""
    _require_full(user)
    m = get_content().module(body.module_id)
    if m is None or not any(s.id == body.step_id for s in m.steps):
        raise HTTPException(status_code=400, detail="Unknown step")
    row = await service.save_step(db, user.id, m.id, body.step_id, done=body.done, notes=body.notes)
    return StepOut(step=StepStateOut(done=row.done, notes=row.notes))


@router.post("/me/enrollments")
async def enroll(body: EnrollIn, user: CurrentUserDep, db: DbDep) -> EnrollOut:
    """Start or drop a module. A signed-off module stays completed."""
    _require_full(user)
    if get_content().module(body.module_id) is None:
        raise HTTPException(status_code=400, detail="Unknown module")
    status = await service.set_enrollment(
        db, user.id, body.module_id, "active" if body.action == "start" else "dropped"
    )
    return EnrollOut(status=status)


@router.post("/me/feedback/{feedback_id}/read", status_code=204)
async def feedback_read(feedback_id: str, user: CurrentUserDep, db: DbDep) -> Response:
    """Mark a guide's note as read. Notes for other students are silently ignored."""
    await service.mark_feedback_read(db, user.id, feedback_id)
    return Response(status_code=204)


# ---------- certificates ----------


@router.get("/certificates/{code}")
async def certificate(code: str, db: DbDep, response: Response) -> CertificateOut:
    """A public certificate: anyone with the code can check it's genuine."""
    c = await service.get_certificate(db, code)
    if c is None:
        raise HTTPException(status_code=404, detail="Certificate not found.")
    response.headers["Cache-Control"] = "public, max-age=300"
    return CertificateOut.model_validate(c, from_attributes=True)
