"""Page views, the /admin stats and the daily cleanup job, against a real Postgres (see conftest)."""

import base64
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from hasesa_api import config, db
from hasesa_api.models import Conversation, Message, PageView, User
from tests.conftest import WEB_SECRET
from tests.test_accounts import bearer
from tests.test_staff import account

pytestmark = pytest.mark.anyio

WEB = {"authorization": "Basic " + base64.b64encode(f"hasesa-web:{WEB_SECRET}".encode()).decode()}


@pytest.fixture(autouse=True)
async def _no_old_views(api):
    async with db.get_engine().begin() as conn:
        await conn.execute(text("TRUNCATE page_views"))


@pytest.fixture
async def people(api, fake_google, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "Boss@Example.com")
    config.get_settings.cache_clear()
    admin = await account(api, fake_google, "a", "boss@example.com")
    student = await account(api, fake_google, "s", "student@example.com")
    return admin, student


async def view(api, path: str, user_id: str | None = None, **extra) -> int:
    body = {"path": path, "userId": user_id, "country": "ET", "city": "Addis Ababa", **extra}
    return (await api.post("/v1/analytics/views", json=body, headers=WEB)).status_code


async def test_only_the_website_server_records_views(api) -> None:
    assert (await api.post("/v1/analytics/views", json={"path": "/"})).status_code == 401
    bad = {"authorization": "Basic " + base64.b64encode(b"hasesa-web:wrong").decode()}
    assert (await api.post("/v1/analytics/views", json={"path": "/"}, headers=bad)).status_code == 401
    assert await view(api, "/modules/radio", referrer="https://t.me/x", userAgent="Phone") == 204
    assert await view(api, "/admin") == 204  # accepted, but never counted
    async with db.get_sessionmaker()() as s:
        rows = (await s.scalars(select(PageView))).all()
    assert [(r.path, r.country, r.city, r.referrer, r.user_agent) for r in rows] == [
        ("/modules/radio", "ET", "Addis Ababa", "https://t.me/x", "Phone")
    ]


async def test_long_fields_are_cut_to_the_column_sizes(api) -> None:
    assert await view(api, "/" + "p" * 1500, country="ETHIOPIA-LONG", region="r" * 50) == 204
    async with db.get_sessionmaker()() as s:
        r = await s.scalar(select(PageView))
    assert (len(r.path), r.country, len(r.region)) == (512, "ETHIOPIA", 16)


async def test_stats_leave_out_admin_visits_unless_asked(api, people) -> None:
    admin, student = people
    await view(api, "/", admin["user_id"])
    await view(api, "/", admin["user_id"])
    await view(api, "/modules", student["user_id"])
    await view(api, "/about")  # signed out: counted, whoever it was

    assert (await api.get("/v1/analytics/stats", headers=bearer(student))).status_code == 403
    s = (await api.get("/v1/analytics/stats", headers=bearer(admin))).json()
    assert (s["pvTotal"], s["pv1d"], s["includeAdmins"]) == (2, 2, False)
    assert {r["label"] for r in s["topPaths"]} == {"/modules", "/about"}
    assert [r["path"] for r in s["recentViews"]] == ["/about", "/modules"]
    assert s["topCountries"] == [{"label": "ET", "count": 2}]
    assert s["topReferrers"] == [{"label": "Direct / none", "count": 2}]

    s = (await api.get("/v1/analytics/stats", params={"includeAdmins": "true"}, headers=bearer(admin))).json()
    assert (s["pvTotal"], s["includeAdmins"]) == (4, True)
    assert s["topPaths"][0] == {"label": "/", "count": 2}
    # Sign-ups and engagement don't depend on the filter.
    assert s["usersTotal"] == 2 and {u["email"] for u in s["users"]} == {"boss@example.com", "student@example.com"}
    assert s["engagement"] == {
        "convos": 0,
        "messages": 0,
        "modulesActive": 0,
        "stepsDone": 0,
        "unitsDone": 0,
        "signoffs": 0,
    }


async def test_cleanup_needs_the_cron_secret_and_deletes_only_old_messages(api, fake_google, monkeypatch) -> None:
    assert (await api.get("/v1/internal/cleanup")).status_code == 403  # no CRON_SECRET set: closed
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    config.get_settings.cache_clear()
    assert (await api.get("/v1/internal/cleanup", headers={"authorization": "Bearer nope"})).status_code == 403

    normal = await account(api, fake_google, "n", "normal@example.com")
    kept = await account(api, fake_google, "k", "keeper@example.com", extended_retention=True)
    now = datetime.now(UTC)
    old, ancient = now - timedelta(days=100), now - timedelta(days=400)
    async with db.get_sessionmaker()() as s:
        for cid, uid in (("c-n", normal["user_id"]), ("c-k", kept["user_id"])):
            s.add(Conversation(id=cid, user_id=uid, created_at=ancient, updated_at=old))
        await s.flush()
        s.add_all(
            [
                Message(id="n-old", conversation_id="c-n", role="user", content="x", created_at=old),
                Message(id="k-old", conversation_id="c-k", role="user", content="x", created_at=old),
                Message(id="k-ancient", conversation_id="c-k", role="user", content="x", created_at=ancient),
            ]
        )
        await s.commit()

    r = await api.get("/v1/internal/cleanup", headers={"authorization": "Bearer cron-secret"})
    assert r.json() == {"messagesDeleted": 2, "conversationsDeleted": 1}
    async with db.get_sessionmaker()() as s:
        assert (await s.scalars(select(Message.id))).all() == ["k-old"]
        assert (await s.scalars(select(Conversation.id))).all() == ["c-k"]
        assert await s.scalar(select(User.extended_retention).where(User.id == kept["user_id"])) is True
