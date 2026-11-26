"""Answers, test-outs, steps, enrolments, progress and certificates, against a real Postgres (see conftest)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from hasesa_api import db
from hasesa_api.content.loader import get_content
from hasesa_api.content.models import Concept, McqProblem
from hasesa_api.learning.grade import js_round
from hasesa_api.models import ModuleEnrollment, Signoff, User
from tests.test_accounts import bearer, profile, sign_in

pytestmark = pytest.mark.anyio


def right(p) -> str:
    return str(p.answerIndex) if isinstance(p, McqProblem) else repr(p.answer)


def wrong(p) -> str:
    return str((p.answerIndex + 1) % len(p.choices)) if isinstance(p, McqProblem) else repr(p.answer * 10 + 1)


def public_unit() -> Concept:
    return next(c for c in get_content().concepts.values() if c.public)


def locked_unit() -> Concept:
    return next(c for c in get_content().concepts.values() if not c.public and len(c.problems) >= 2)


async def student(api, fake_google, sub: str = "g-1", email: str = "student@example.com") -> dict:
    fake_google[sub] = profile(sub, email)
    return await sign_in(api, sub)


async def set_user(**values) -> None:
    async with db.get_sessionmaker()() as s:
        await s.execute(update(User).values(**values))
        await s.commit()


# ---------- answers ----------


async def test_signed_out_visitor_can_answer_a_public_unit_but_nothing_is_saved(api) -> None:
    c = public_unit()
    p = c.problems[0]
    r = await api.post("/v1/attempts", json={"unitId": c.id, "questionId": p.id, "answer": right(p)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["correct"] is True and body["unit"] is None
    assert body["explanation"] == p.explanation


async def test_signed_out_visitor_cannot_answer_a_locked_unit(api) -> None:
    c = locked_unit()
    r = await api.post("/v1/attempts", json={"unitId": c.id, "questionId": c.problems[0].id, "answer": "1"})
    assert r.status_code == 403
    assert r.json()["detail"] == "Enrol at the Academy to unlock this."


async def test_bad_attempts_get_the_websites_messages(api) -> None:
    c = public_unit()
    q = c.problems[0].id
    cases = [
        ({"unitId": "nope", "questionId": q, "answer": "1"}, "Unknown unit"),
        ({"unitId": c.id, "questionId": "nope", "answer": "1"}, "Unknown question"),
        ({"unitId": c.id, "questionId": q, "answer": "   "}, "Enter an answer"),
    ]
    for payload, message in cases:
        r = await api.post("/v1/attempts", json=payload)
        assert (r.status_code, r.json()["detail"]) == (400, message)
    long = await api.post("/v1/attempts", json={"unitId": c.id, "questionId": q, "answer": "1" * 201})
    assert (long.status_code, long.json()["detail"]) == (400, "Enter an answer")


async def test_practice_scores_first_tries_and_completes_the_unit(api, fake_google) -> None:
    t = await student(api, fake_google)
    c = locked_unit()
    first, *rest = c.problems

    r = await api.post(
        "/v1/attempts", json={"unitId": c.id, "questionId": first.id, "answer": wrong(first)}, headers=bearer(t)
    )
    assert r.json()["correct"] is False
    assert r.json()["unit"] == {"status": "started", "score": 0}

    await api.post(
        "/v1/attempts", json={"unitId": c.id, "questionId": first.id, "answer": right(first)}, headers=bearer(t)
    )
    for p in rest:
        r = await api.post(
            "/v1/attempts", json={"unitId": c.id, "questionId": p.id, "answer": right(p)}, headers=bearer(t)
        )
    expected = js_round(len(rest) / len(c.problems) * 100)
    assert r.json()["unit"] == {"status": "completed", "score": expected}

    attempts = (await api.get("/v1/me/attempts", params={"unitId": c.id}, headers=bearer(t))).json()
    assert [a["questionId"] for a in attempts] == [first.id, first.id, *[p.id for p in rest]]
    assert attempts[0]["mode"] == "practice"


async def test_student_without_access_cannot_answer_locked_units(api, fake_google) -> None:
    t = await student(api, fake_google)
    await set_user(paid_until=datetime(2020, 1, 1, tzinfo=UTC))
    c = locked_unit()
    r = await api.post(
        "/v1/attempts", json={"unitId": c.id, "questionId": c.problems[0].id, "answer": "1"}, headers=bearer(t)
    )
    assert r.status_code == 403


# ---------- test-outs ----------


async def test_passing_a_test_out_marks_the_unit_tested_out_and_keeps_that_score(api, fake_google) -> None:
    t = await student(api, fake_google)
    c = locked_unit()
    answers = {p.id: right(p) for p in c.problems}
    answers[c.problems[0].id] = 7  # not a string: counts as unanswered
    r = await api.post("/v1/attempts/testout", json={"unitId": c.id, "answers": answers}, headers=bearer(t))
    assert r.status_code == 200, r.text
    body = r.json()
    score = js_round((len(c.problems) - 1) / len(c.problems) * 100)
    assert body["score"] == score
    assert body["passed"] is (score >= 80)
    assert [x["id"] for x in body["results"]] == [p.id for p in c.problems]
    assert body["results"][0]["correct"] is False

    if body["passed"]:
        assert body["unit"] == {"status": "tested_out", "score": score}
        # More practice never lowers a tested-out score.
        p = c.problems[0]
        r = await api.post(
            "/v1/attempts", json={"unitId": c.id, "questionId": p.id, "answer": wrong(p)}, headers=bearer(t)
        )
        assert r.json()["unit"] == {"status": "tested_out", "score": score}

    modes = {a["mode"] for a in (await api.get("/v1/me/attempts", headers=bearer(t))).json()}
    assert "testout" in modes


async def test_failed_test_out_leaves_the_unit_started(api, fake_google) -> None:
    t = await student(api, fake_google)
    c = locked_unit()
    r = await api.post("/v1/attempts/testout", json={"unitId": c.id, "answers": {}}, headers=bearer(t))
    assert r.json()["score"] == 0 and r.json()["passed"] is False
    assert r.json()["unit"] == {"status": "started", "score": 0}


async def test_signed_out_test_out_on_a_public_unit_is_graded_but_not_saved(api) -> None:
    c = public_unit()
    r = await api.post("/v1/attempts/testout", json={"unitId": c.id, "answers": {p.id: right(p) for p in c.problems}})
    assert r.status_code == 200
    assert r.json()["score"] == 100 and r.json()["unit"] is None


# ---------- steps and enrolments ----------


async def test_saving_a_step_enrols_the_student_and_keeps_notes(api, fake_google) -> None:
    t = await student(api, fake_google)
    m = get_content().modules[0]
    s = m.steps[0]

    r = await api.post("/v1/me/steps", json={"moduleId": m.id, "stepId": s.id, "notes": "  hello  "}, headers=bearer(t))
    assert r.status_code == 200, r.text
    assert r.json() == {"step": {"done": False, "notes": "hello"}}
    r = await api.post("/v1/me/steps", json={"moduleId": m.id, "stepId": s.id, "done": True}, headers=bearer(t))
    assert r.json() == {"step": {"done": True, "notes": "hello"}}
    r = await api.post("/v1/me/steps", json={"moduleId": m.id, "stepId": s.id, "notes": " "}, headers=bearer(t))
    assert r.json() == {"step": {"done": True, "notes": None}}

    progress = (await api.get("/v1/me/progress", headers=bearer(t))).json()
    assert [(e["moduleId"], e["status"]) for e in progress["enrollments"]] == [(m.id, "active")]
    [step] = progress["steps"]
    assert step["done"] is True and step["completedAt"]


async def test_long_notes_are_cut_to_4000_characters(api, fake_google) -> None:
    t = await student(api, fake_google)
    m = get_content().modules[0]
    r = await api.post(
        "/v1/me/steps", json={"moduleId": m.id, "stepId": m.steps[0].id, "notes": "x" * 5000}, headers=bearer(t)
    )
    assert len(r.json()["step"]["notes"]) == 4000


async def test_unknown_step_and_module_are_refused(api, fake_google) -> None:
    t = await student(api, fake_google)
    m = get_content().modules[0]
    r = await api.post("/v1/me/steps", json={"moduleId": m.id, "stepId": "nope"}, headers=bearer(t))
    assert (r.status_code, r.json()["detail"]) == (400, "Unknown step")
    r = await api.post("/v1/me/enrollments", json={"moduleId": "nope", "action": "start"}, headers=bearer(t))
    assert (r.status_code, r.json()["detail"]) == (400, "Unknown module")


async def test_steps_and_enrolment_need_access(api, fake_google) -> None:
    m = get_content().modules[0]
    assert (await api.post("/v1/me/steps", json={"moduleId": m.id, "stepId": m.steps[0].id})).status_code == 401
    t = await student(api, fake_google)
    await set_user(paid_until=None)
    r = await api.post("/v1/me/enrollments", json={"moduleId": m.id, "action": "start"}, headers=bearer(t))
    assert r.status_code == 403


async def test_start_drop_and_completed_modules_stay_completed(api, fake_google) -> None:
    t = await student(api, fake_google)
    m = get_content().modules[0]
    r = await api.post("/v1/me/enrollments", json={"moduleId": m.id, "action": "start"}, headers=bearer(t))
    assert r.json() == {"status": "active"}
    r = await api.post("/v1/me/enrollments", json={"moduleId": m.id, "action": "drop"}, headers=bearer(t))
    assert r.json() == {"status": "dropped"}

    async with db.get_sessionmaker()() as s:
        await s.execute(update(ModuleEnrollment).values(status="completed"))
        await s.commit()
    r = await api.post("/v1/me/enrollments", json={"moduleId": m.id, "action": "drop"}, headers=bearer(t))
    assert r.json() == {"status": "completed"}


# ---------- progress, feedback and certificates ----------


async def test_progress_needs_a_signed_in_student(api) -> None:
    assert (await api.get("/v1/me/progress")).status_code == 401
    assert (await api.get("/v1/me/attempts")).status_code == 401


async def test_certificate_is_public_and_names_student_and_guide(api, fake_google) -> None:
    t = await student(api, fake_google)
    g = await student(api, fake_google, "g-2", "guide@example.com")
    m = get_content().modules[0]
    async with db.get_sessionmaker()() as s:
        s.add(
            Signoff(
                user_id=t["user_id"],
                module_id=m.id,
                checks=["built"],
                note="Great work",
                guide_id=g["user_id"],
                certificate_code="AB12-CD34EF",
            )
        )
        await s.commit()

    r = await api.get("/v1/certificates/AB12-CD34EF")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["moduleId"] == m.id and body["code"] == "AB12-CD34EF" and body["note"] == "Great work"
    assert body["student"] == "Student One" and body["guide"] == "Student One"
    assert "guideId" not in body

    progress = (await api.get("/v1/me/progress", headers=bearer(t))).json()
    assert progress["signoffs"][0]["certificateCode"] == "AB12-CD34EF"

    assert (await api.get("/v1/certificates/AB12-XXXXXX")).status_code == 404
    assert (await api.get("/v1/certificates/not-a-code")).status_code == 404


async def test_feedback_read_only_touches_the_students_own_notes(api, fake_google) -> None:
    from hasesa_api.models import GuideFeedback

    t = await student(api, fake_google)
    other = await student(api, fake_google, "g-2", "other@example.com")
    async with db.get_sessionmaker()() as s:
        s.add_all(
            [
                GuideFeedback(id="mine", student_id=t["user_id"], guide_id=other["user_id"], body="hi"),
                GuideFeedback(id="theirs", student_id=other["user_id"], guide_id=t["user_id"], body="yo"),
            ]
        )
        await s.commit()
    for fid in ("mine", "theirs"):
        assert (await api.post(f"/v1/me/feedback/{fid}/read", headers=bearer(t))).status_code == 204
    mine = (await api.get("/v1/me/progress", headers=bearer(t))).json()["feedback"]
    theirs = (await api.get("/v1/me/progress", headers=bearer(other))).json()["feedback"]
    assert mine[0]["readAt"] is not None
    assert theirs[0]["readAt"] is None
