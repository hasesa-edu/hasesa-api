"""The guide's tools and the admin tools, against a real Postgres (see conftest)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from hasesa_api import config, db
from hasesa_api.content.loader import get_content
from hasesa_api.models import ModuleEnrollment, Payment, User
from tests.test_accounts import bearer, profile, sign_in

pytestmark = pytest.mark.anyio


async def account(api, fake_google, sub: str, email: str, **values) -> dict:
    fake_google[sub] = profile(sub, email)
    t = await sign_in(api, sub)
    if values:
        async with db.get_sessionmaker()() as s:
            await s.execute(update(User).where(User.id == t["user_id"]).values(**values))
            await s.commit()
    return t


@pytest.fixture
async def people(api, fake_google):
    student = await account(api, fake_google, "s", "student@example.com")
    guide = await account(api, fake_google, "g", "guide@example.com", role="guide", paid_until=None)
    return student, guide


# ---------- who can use what ----------


async def test_students_cannot_use_the_guides_tools(api, people) -> None:
    student, _ = people
    for method, path in [
        ("GET", "/v1/guide/roster"),
        ("GET", f"/v1/guide/students/{student['user_id']}"),
        ("POST", f"/v1/guide/students/{student['user_id']}/feedback"),
    ]:
        r = await api.request(method, path, json={"body": "x"}, headers=bearer(student))
        assert (r.status_code, r.json()["detail"]) == (403, "Only the guide can do this."), path
    assert (await api.get("/v1/guide/roster")).status_code == 401


async def test_admin_tools_need_an_email_in_admin_emails(api, people, monkeypatch) -> None:
    student, guide = people
    assert (await api.get("/v1/admin/subscribers", headers=bearer(guide))).status_code == 403
    assert (await api.get("/v1/me", headers=bearer(guide))).json()["admin"] is False

    monkeypatch.setenv("ADMIN_EMAILS", "someone@example.com, Guide@Example.com")
    config.get_settings.cache_clear()
    assert (await api.get("/v1/admin/subscribers", headers=bearer(guide))).status_code == 200
    assert (await api.get("/v1/me", headers=bearer(guide))).json()["admin"] is True
    assert (await api.get("/v1/admin/subscribers", headers=bearer(student))).status_code == 403


# ---------- the tracker ----------


async def test_roster_lists_enrolled_and_started_students_but_not_guides(api, fake_google, people) -> None:
    student, guide = people
    lapsed = await account(api, fake_google, "l", "lapsed@example.com", paid_until=datetime(2020, 1, 1, tzinfo=UTC))
    await account(api, fake_google, "n", "never@example.com", paid_until=None)
    m = get_content().modules[0]
    async with db.get_sessionmaker()() as s:
        s.add(ModuleEnrollment(user_id=lapsed["user_id"], module_id=m.id, status="active"))
        await s.commit()
    c = next(x for x in get_content().concepts.values() if x.public)
    await api.post(
        "/v1/attempts", json={"unitId": c.id, "questionId": c.problems[0].id, "answer": "1"}, headers=bearer(student)
    )

    r = await api.get("/v1/guide/roster", headers=bearer(guide))
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(s["email"] for s in body["students"]) == ["lapsed@example.com", "student@example.com"]
    assert [e["userId"] for e in body["enrollments"]] == [lapsed["user_id"]]
    assert [a["userId"] for a in body["attempts"]] == [student["user_id"]]
    assert set(body["attempts"][0]) == {"userId", "unitId", "questionId", "correct", "createdAt"}


async def test_student_page_has_account_progress_and_newest_answers_first(api, people) -> None:
    student, guide = people
    c = next(x for x in get_content().concepts.values() if x.public)
    for answer in ("1", "2"):
        await api.post(
            "/v1/attempts",
            json={"unitId": c.id, "questionId": c.problems[0].id, "answer": answer},
            headers=bearer(student),
        )
    r = await api.get(f"/v1/guide/students/{student['user_id']}", headers=bearer(guide))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "student@example.com"
    assert [a["answer"] for a in body["attempts"]] == ["2", "1"]
    assert body["progress"]["units"][0]["unitId"] == c.id
    assert (await api.get("/v1/guide/students/nope", headers=bearer(guide))).status_code == 404


# ---------- feedback, assignments, flags ----------


async def test_feedback_reaches_the_students_dashboard(api, people) -> None:
    student, guide = people
    sid = student["user_id"]
    m = get_content().modules[0]
    url = f"/v1/guide/students/{sid}/feedback"

    r = await api.post(url, json={"body": "   "}, headers=bearer(guide))
    assert (r.status_code, r.json()["detail"]) == (400, "Write some feedback first.")
    r = await api.post("/v1/guide/students/nope/feedback", json={"body": "hi"}, headers=bearer(guide))
    assert (r.status_code, r.json()["detail"]) == (404, "Student not found.")

    r = await api.post(
        url, json={"body": " Nice work ", "moduleId": m.id, "stepId": m.steps[0].id}, headers=bearer(guide)
    )
    assert r.status_code == 201
    await api.post(url, json={"body": "x" * 3000, "moduleId": "gone", "stepId": "gone"}, headers=bearer(guide))

    newest, first = (await api.get("/v1/me/progress", headers=bearer(student))).json()["feedback"]
    assert (first["body"], first["moduleId"], first["stepId"]) == ("Nice work", m.id, m.steps[0].id)
    assert len(newest["body"]) == 2000 and newest["moduleId"] is None and newest["stepId"] is None


async def test_assign_and_remove_a_unit(api, people) -> None:
    student, guide = people
    sid = student["user_id"]
    unit = next(iter(get_content().concepts))
    r = await api.post(f"/v1/guide/students/{sid}/assignments", json={"unitId": "nope"}, headers=bearer(guide))
    assert (r.status_code, r.json()["detail"]) == (400, "Pick a concept unit.")

    r = await api.post(
        f"/v1/guide/students/{sid}/assignments", json={"unitId": unit, "note": " "}, headers=bearer(guide)
    )
    aid = r.json()["id"]
    [a] = (await api.get("/v1/me/progress", headers=bearer(student))).json()["assignments"]
    assert (a["id"], a["unitId"], a["note"]) == (aid, unit, None)

    r = await api.delete(f"/v1/guide/students/{sid}/assignments/{aid}", headers=bearer(guide))
    assert r.status_code == 204
    assert (await api.get("/v1/me/progress", headers=bearer(student))).json()["assignments"] == []


async def test_flags_need_a_started_module(api, people) -> None:
    student, guide = people
    sid = student["user_id"]
    m = get_content().modules[0]
    url = f"/v1/guide/students/{sid}/modules/{m.id}/flag"
    r = await api.put(url, json={"flagged": True, "note": "stuck"}, headers=bearer(guide))
    assert (r.status_code, r.json()["detail"]) == (409, "The student hasn't started this module.")

    await api.post("/v1/me/enrollments", json={"moduleId": m.id, "action": "start"}, headers=bearer(student))
    assert (await api.put(url, json={"flagged": True, "note": "stuck"}, headers=bearer(guide))).status_code == 204
    [e] = (await api.get("/v1/me/progress", headers=bearer(student))).json()["enrollments"]
    assert (e["flagged"], e["flagNote"]) == (True, "stuck")
    await api.put(url, json={"flagged": False, "note": "ignored"}, headers=bearer(guide))
    [e] = (await api.get("/v1/me/progress", headers=bearer(student))).json()["enrollments"]
    assert (e["flagged"], e["flagNote"]) == (False, None)


# ---------- sign-offs ----------


async def test_sign_off_needs_every_item_then_issues_a_certificate(api, people) -> None:
    student, guide = people
    sid = student["user_id"]
    m = next(x for x in get_content().modules if len(x.signoff) >= 2)
    url = f"/v1/guide/students/{sid}/signoffs"
    every = [s.id for s in m.signoff]

    r = await api.post(url, json={"moduleId": m.id, "checks": every[:1]}, headers=bearer(guide))
    assert (r.status_code, r.json()["detail"]) == (400, f"Tick every item before signing off ({len(every) - 1} left).")

    await api.post("/v1/me/enrollments", json={"moduleId": m.id, "action": "start"}, headers=bearer(student))
    await api.put(f"/v1/guide/students/{sid}/modules/{m.id}/flag", json={"flagged": True}, headers=bearer(guide))
    r = await api.post(url, json={"moduleId": m.id, "checks": every, "note": " Well done "}, headers=bearer(guide))
    assert r.status_code == 200, r.text
    code = r.json()["certificateCode"]
    assert len(code) == 11 and code[4] == "-"

    cert = (await api.get(f"/v1/certificates/{code}")).json()
    assert (cert["moduleId"], cert["note"], cert["guide"]) == (m.id, "Well done", "Student One")
    [e] = (await api.get("/v1/me/progress", headers=bearer(student))).json()["enrollments"]
    assert (e["status"], e["flagged"]) == ("completed", False)

    # Signing off again keeps the first certificate.
    again = await api.post(url, json={"moduleId": m.id, "checks": every}, headers=bearer(guide))
    assert again.json()["certificateCode"] == code

    assert (await api.delete(f"{url}/{m.id}", headers=bearer(guide))).status_code == 204
    assert (await api.get(f"/v1/certificates/{code}")).status_code == 404
    [e] = (await api.get("/v1/me/progress", headers=bearer(student))).json()["enrollments"]
    assert (e["status"], e["completedAt"]) == ("active", None)


# ---------- admin ----------


@pytest.fixture
async def admin(api, people, monkeypatch) -> dict:
    _, guide = people
    monkeypatch.setenv("ADMIN_EMAILS", "guide@example.com")
    config.get_settings.cache_clear()
    return guide


async def test_admin_enrols_a_student_on_top_of_days_left(api, people, admin) -> None:
    student, _ = people
    until = datetime.now(UTC) + timedelta(days=10)
    async with db.get_sessionmaker()() as s:
        await s.execute(update(User).where(User.id == student["user_id"]).values(paid_until=until))
        await s.commit()

    r = await api.post(
        "/v1/admin/enrolments",
        json={"email": " Student@Example.com ", "days": 30, "note": "paid cash"},
        headers=bearer(admin),
    )
    assert r.status_code == 200, r.text
    new_until = datetime.fromisoformat(r.json()["paidUntil"])
    assert abs((new_until - until) - timedelta(days=30)) < timedelta(seconds=5)

    async with db.get_sessionmaker()() as s:
        p = await s.scalar(select(Payment).where(Payment.user_id == student["user_id"]))
    assert (p.source, p.status, p.amount_etb, p.days, p.note) == ("admin", "success", 0, 30, "paid cash")

    subs = (await api.get("/v1/admin/subscribers", headers=bearer(admin))).json()
    assert subs["stats"]["guides"] == 1 and subs["stats"]["active"] == 1
    assert subs["payments"][0]["email"] == "student@example.com"


async def test_admin_errors(api, admin) -> None:
    r = await api.post("/v1/admin/enrolments", json={"email": "who@example.com", "days": 5}, headers=bearer(admin))
    assert r.status_code == 404
    assert r.json()["detail"] == "No one has signed up with who@example.com yet. Ask them to sign up first."
    r = await api.post("/v1/admin/enrolments", json={"email": "who@example.com", "days": 400}, headers=bearer(admin))
    assert r.status_code == 422


async def test_admin_sets_roles(api, people, admin) -> None:
    student, _ = people
    r = await api.put("/v1/admin/roles", json={"email": "student@example.com", "role": "guide"}, headers=bearer(admin))
    assert r.json() == {"email": "student@example.com", "role": "guide"}
    assert (await api.get("/v1/me", headers=bearer(student))).json()["role"] == "guide"
    r = await api.put("/v1/admin/roles", json={"email": "who@example.com", "role": "guide"}, headers=bearer(admin))
    assert r.status_code == 404
