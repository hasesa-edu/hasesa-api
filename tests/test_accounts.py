"""Sign-in, tokens and sessions end to end, against a real Postgres (see conftest)."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select, text, update

from hasesa_api import db
from hasesa_api.identity import google, sessions, tokens
from hasesa_api.models import AuthSession, User

WEB_SECRET = "test-web-secret"  # matches conftest

pytestmark = pytest.mark.anyio

WEB = "hasesa-web"
CALLBACK = "https://www.hasesa.com/api/auth/callback"
VERIFIER = "v" * 50


def profile(sub: str = "g-1", email: str = "student@example.com") -> google.GoogleProfile:
    return google.GoogleProfile(sub=sub, email=email, name="Student One", picture="https://img/1")


async def sign_in(api: httpx.AsyncClient, google_token: str, *, redirect_uri: str = CALLBACK) -> dict:
    """Run the whole browser flow and redeem the code. Returns the token response."""
    start = await api.get(
        "/v1/auth/google/start",
        params={
            "client_id": WEB,
            "redirect_uri": redirect_uri,
            "state": "client-state",
            "code_challenge": tokens.sha256_b64(VERIFIER),
        },
    )
    assert start.status_code == 302, start.text
    google_state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]

    back = await api.get("/v1/auth/google/callback", params={"state": google_state, "code": google_token})
    assert back.status_code == 302
    query = parse_qs(urlsplit(back.headers["location"]).query)
    assert query["state"] == ["client-state"]
    assert "code" in query, query

    res = await api.post(
        "/v1/auth/token",
        json={
            "grant_type": "authorization_code",
            "client_id": WEB,
            "client_secret": WEB_SECRET,
            "code": query["code"][0],
            "redirect_uri": redirect_uri,
            "code_verifier": VERIFIER,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


async def refresh(api: httpx.AsyncClient, refresh_token: str) -> httpx.Response:
    return await api.post(
        "/v1/auth/token",
        json={
            "grant_type": "refresh_token",
            "client_id": WEB,
            "client_secret": WEB_SECRET,
            "refresh_token": refresh_token,
        },
    )


def bearer(t: dict) -> dict:
    return {"Authorization": f"Bearer {t['access_token']}"}


# ---------- browser sign-in ----------


async def test_new_student_signs_in_and_sees_their_account(api, fake_google) -> None:
    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    assert t["is_new_user"] is True

    me = await api.get("/v1/me", headers=bearer(t))
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "student@example.com"
    assert body["displayName"] == "Student One"
    assert body["access"] == "enrolled"  # pilot enrolment for new accounts
    assert body["role"] == "student"


async def test_second_sign_in_reuses_the_account(api, fake_google) -> None:
    fake_google["tok"] = profile()
    first = await sign_in(api, "tok")
    second = await sign_in(api, "tok")
    assert second["is_new_user"] is False
    assert second["user_id"] == first["user_id"]
    assert second["session_id"] != first["session_id"]


async def test_preview_deploy_can_sign_in(api, fake_google) -> None:
    fake_google["tok"] = profile()
    preview = "https://ai-edu-git-feature-w-yidnes-projects.vercel.app/api/auth/callback"
    assert (await sign_in(api, "tok", redirect_uri=preview))["user_id"]


async def test_unregistered_redirect_is_refused(api) -> None:
    res = await api.get(
        "/v1/auth/google/start",
        params={"client_id": WEB, "redirect_uri": "https://evil.example/cb", "code_challenge": "c" * 43},
    )
    assert res.status_code == 400


async def test_callback_from_another_browser_is_refused(api, fake_google) -> None:
    fake_google["tok"] = profile()
    start = await api.get(
        "/v1/auth/google/start",
        params={"client_id": WEB, "redirect_uri": CALLBACK, "code_challenge": tokens.sha256_b64(VERIFIER)},
    )
    google_state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    api.cookies.clear()  # a different browser has no sign-in cookie
    back = await api.get("/v1/auth/google/callback", params={"state": google_state, "code": "tok"})
    assert parse_qs(urlsplit(back.headers["location"]).query)["error"] == ["state"]


@pytest.mark.parametrize(("token", "error"), [("unverified", "email"), ("garbage", "google")])
async def test_google_failures_send_the_user_back_with_a_reason(api, fake_google, token, error) -> None:
    start = await api.get(
        "/v1/auth/google/start",
        params={"client_id": WEB, "redirect_uri": CALLBACK, "code_challenge": tokens.sha256_b64(VERIFIER)},
    )
    google_state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    back = await api.get("/v1/auth/google/callback", params={"state": google_state, "code": token})
    assert parse_qs(urlsplit(back.headers["location"]).query)["error"] == [error]


async def test_code_needs_the_client_secret_and_the_pkce_verifier(api, fake_google) -> None:
    fake_google["tok"] = profile()
    start = await api.get(
        "/v1/auth/google/start",
        params={"client_id": WEB, "redirect_uri": CALLBACK, "code_challenge": tokens.sha256_b64(VERIFIER)},
    )
    google_state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    back = await api.get("/v1/auth/google/callback", params={"state": google_state, "code": "tok"})
    code = parse_qs(urlsplit(back.headers["location"]).query)["code"][0]
    base = {"grant_type": "authorization_code", "client_id": WEB, "code": code, "redirect_uri": CALLBACK}

    no_secret = await api.post("/v1/auth/token", json={**base, "code_verifier": VERIFIER})
    assert no_secret.status_code == 401
    wrong_verifier = await api.post(
        "/v1/auth/token", json={**base, "client_secret": WEB_SECRET, "code_verifier": "w" * 50}
    )
    assert wrong_verifier.status_code == 400
    # A failed attempt with the wrong verifier doesn't burn the code for the real client...
    ok = await api.post("/v1/auth/token", json={**base, "client_secret": WEB_SECRET, "code_verifier": VERIFIER})
    assert ok.status_code == 200
    # ...but a code works only once.
    again = await api.post("/v1/auth/token", json={**base, "client_secret": WEB_SECRET, "code_verifier": VERIFIER})
    assert again.status_code == 400


# ---------- account linking (same rules as the web app) ----------


async def _add_user(**values) -> None:
    async with db.get_sessionmaker()() as s:
        s.add(User(display_name="Old", **values))
        await s.commit()


async def test_old_account_without_google_id_is_linked_by_email(api, fake_google) -> None:
    await _add_user(id="old-1", email="student@example.com", google_sub=None)
    fake_google["tok"] = profile(email="Student@Example.com")
    t = await sign_in(api, "tok")
    assert t["user_id"] == "old-1" and t["is_new_user"] is False


async def test_email_linked_to_another_google_account_is_refused(api, fake_google) -> None:
    await _add_user(id="old-1", email="student@example.com", google_sub="someone-else")
    fake_google["tok"] = profile(sub="g-new")
    start = await api.get(
        "/v1/auth/google/start",
        params={"client_id": WEB, "redirect_uri": CALLBACK, "code_challenge": tokens.sha256_b64(VERIFIER)},
    )
    google_state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    back = await api.get("/v1/auth/google/callback", params={"state": google_state, "code": "tok"})
    assert parse_qs(urlsplit(back.headers["location"]).query)["error"] == ["taken"]


# ---------- refresh and sign-out ----------


async def test_refresh_rotates_and_extends_the_session(api, fake_google) -> None:
    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    r1 = await refresh(api, t["refresh_token"])
    assert r1.status_code == 200
    assert r1.json()["refresh_token"] != t["refresh_token"]
    r2 = await refresh(api, r1.json()["refresh_token"])
    assert r2.status_code == 200


async def test_parallel_duplicate_refresh_gets_the_same_answer(api, fake_google) -> None:
    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    first = await refresh(api, t["refresh_token"])
    duplicate = await refresh(api, t["refresh_token"])  # e.g. two page loads at once
    assert duplicate.status_code == 200
    assert duplicate.json()["refresh_token"] == first.json()["refresh_token"]


async def test_reused_old_refresh_token_ends_the_session(api, fake_google) -> None:
    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    r1 = (await refresh(api, t["refresh_token"])).json()
    # Pretend the grace period has passed, then replay the old token.
    async with db.get_sessionmaker()() as s:
        await s.execute(
            update(AuthSession)
            .where(AuthSession.id == t["session_id"])
            .values(rotated_at=datetime.now(UTC) - sessions.REFRESH_GRACE - timedelta(seconds=1))
        )
        await s.commit()
    stolen = await refresh(api, t["refresh_token"])
    assert stolen.status_code == 400
    # The legitimate holder is signed out too: the whole session ended.
    assert (await refresh(api, r1["refresh_token"])).status_code == 400
    assert (await api.get("/v1/me", headers=bearer(r1))).status_code == 401


async def test_logout_ends_the_session_immediately(api, fake_google) -> None:
    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    assert (await api.post("/v1/auth/logout", json={"refresh_token": t["refresh_token"]})).status_code == 204
    assert (await api.get("/v1/me", headers=bearer(t))).status_code == 401
    assert (await refresh(api, t["refresh_token"])).status_code == 400


async def test_logout_all_ends_every_session(api, fake_google) -> None:
    fake_google["tok"] = profile()
    a = await sign_in(api, "tok")
    b = await sign_in(api, "tok")
    assert (await api.post("/v1/auth/logout-all", headers=bearer(a))).status_code == 204
    assert (await api.get("/v1/me", headers=bearer(b))).status_code == 401


async def test_expired_session_cannot_refresh(api, fake_google) -> None:
    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    async with db.get_sessionmaker()() as s:
        await s.execute(
            update(AuthSession).where(AuthSession.id == t["session_id"]).values(expires_at=datetime.now(UTC))
        )
        await s.commit()
    assert (await refresh(api, t["refresh_token"])).status_code == 400


async def test_web_session_lasts_30_days(api, fake_google) -> None:
    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    expires = datetime.fromisoformat(t["session_expires_at"])
    assert timedelta(days=29, hours=23) < expires - datetime.now(UTC) <= timedelta(days=30)


# ---------- mobile (native) sign-in ----------


async def test_mobile_app_signs_in_with_a_google_id_token(api, fake_google) -> None:
    fake_google["id-tok"] = profile()
    res = await api.post("/v1/auth/google/id-token", json={"client_id": "hasesa-mobile", "id_token": "id-tok"})
    assert res.status_code == 200, res.text
    t = res.json()
    expires = datetime.fromisoformat(t["session_expires_at"])
    assert expires - datetime.now(UTC) > timedelta(days=89)  # 90-day mobile sessions
    # Mobile refreshes need no client secret (a public client).
    r = await api.post(
        "/v1/auth/token",
        json={"grant_type": "refresh_token", "client_id": "hasesa-mobile", "refresh_token": t["refresh_token"]},
    )
    assert r.status_code == 200


async def test_web_client_cannot_use_the_id_token_flow(api, fake_google) -> None:
    fake_google["id-tok"] = profile()
    res = await api.post("/v1/auth/google/id-token", json={"client_id": WEB, "id_token": "id-tok"})
    assert res.status_code == 400


async def test_refresh_token_only_works_for_its_own_client(api, fake_google) -> None:
    fake_google["id-tok"] = profile()
    t = (await api.post("/v1/auth/google/id-token", json={"client_id": "hasesa-mobile", "id_token": "id-tok"})).json()
    assert (await refresh(api, t["refresh_token"])).status_code == 400  # presented as the web client


# ---------- profile ----------


async def test_profile_update(api, fake_google) -> None:
    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    res = await api.patch(
        "/v1/me", headers=bearer(t), json={"school": "  Bole High  ", "language": "xx", "extendedRetention": True}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["school"] == "Bole High"
    assert body["language"] == "en"  # unsupported languages are ignored
    assert body["extendedRetention"] is True


async def test_me_needs_a_token(api) -> None:
    assert (await api.get("/v1/me")).status_code == 401
    assert (await api.get("/v1/me", headers={"Authorization": "Bearer nope"})).status_code == 401


async def test_tables_exist(api) -> None:
    async with db.get_sessionmaker()() as s:
        clients = (await s.execute(text("SELECT id FROM oauth_clients ORDER BY id"))).scalars().all()
        assert clients == ["hasesa-mobile", "hasesa-web"]
        assert (await s.scalar(select(AuthSession.id).limit(1))) is None


# ---------- content access (phase 2) ----------


async def _set_user(**values) -> None:
    async with db.get_sessionmaker()() as s:
        await s.execute(update(User).values(**values))
        await s.commit()


async def test_enrolled_student_opens_steps_and_locked_units_but_not_the_guide(api, fake_google) -> None:
    from hasesa_api.content.loader import get_content

    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    c = get_content()
    m = c.modules[0]
    locked = next(x for x in c.concepts.values() if not x.public)

    step = await api.get(f"/v1/modules/{m.id}/steps/{m.steps[1].id}", headers=bearer(t))
    assert step.status_code == 200, step.text
    assert step.json()["index"] == 1 and step.json()["body"]
    assert step.headers["cache-control"] == "private, no-store"
    unit = await api.get(f"/v1/concepts/{locked.id}", headers=bearer(t))
    assert unit.status_code == 200
    assert all(k not in unit.text for k in ('"answer":', '"answerIndex":', '"explanation":'))
    assert (await api.get(f"/v1/modules/{m.id}/guide", headers=bearer(t))).status_code == 403

    # Access ended: steps lock again.
    await _set_user(paid_until=datetime(2020, 1, 1, tzinfo=UTC))
    assert (await api.get(f"/v1/modules/{m.id}/steps/{m.steps[1].id}", headers=bearer(t))).status_code == 403
    assert (await api.get(f"/v1/concepts/{locked.id}", headers=bearer(t))).status_code == 403


async def test_guide_sees_the_guide_version(api, fake_google) -> None:
    from hasesa_api.content.loader import get_content

    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    await _set_user(role="guide", paid_until=None)
    m = get_content().modules[0]
    r = await api.get(f"/v1/modules/{m.id}/guide", headers=bearer(t))
    assert r.status_code == 200
    assert r.json()["guide"] == m.guide
    assert (await api.get(f"/v1/modules/{m.id}/steps/{m.steps[0].id}", headers=bearer(t))).status_code == 200


async def test_signed_out_session_cannot_open_steps(api, fake_google) -> None:
    from hasesa_api.content.loader import get_content

    fake_google["tok"] = profile()
    t = await sign_in(api, "tok")
    await api.post("/v1/auth/logout", json={"refresh_token": t["refresh_token"]})
    m = get_content().modules[0]
    assert (await api.get(f"/v1/modules/{m.id}/steps/{m.steps[0].id}", headers=bearer(t))).status_code == 401
