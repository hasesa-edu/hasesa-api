"""Page views: recorded for the website's server, and the site-wide stats on /admin.

Visits by the people who run Hasesa (accounts whose email is in ADMIN_EMAILS)
are left out of the stats unless asked for. Visits they make while signed out
can't be told apart from anyone else's.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import Field
from sqlalchemy import text

from hasesa_api.config import get_settings
from hasesa_api.db import DbDep
from hasesa_api.identity.deps import AdminDep, ClientDep
from hasesa_api.models import PageView
from hasesa_api.schemas import ApiModel

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _cut(value: str | None, limit: int) -> str | None:
    return value[:limit] if value else None


# ---------- recording ----------


class ViewIn(ApiModel):
    path: Annotated[str, Field(min_length=1, max_length=2_000)]
    referrer: str | None = Field(default=None, max_length=4_000)
    user_agent: str | None = Field(default=None, max_length=4_000)
    # Set by the website's server from Vercel's request headers and its own session,
    # which is why only a confidential client may record views.
    country: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=300)
    user_id: str | None = Field(default=None, max_length=100)


@router.post("/views", status_code=204)
async def record_view(body: ViewIn, client_id: ClientDep, db: DbDep) -> Response:
    """Record one page view. For the website's server (client ID and secret, HTTP Basic)."""
    path = body.path[:512]
    if not path.startswith("/admin"):  # the admin pages are never counted
        db.add(
            PageView(
                id=uuid.uuid4().hex,
                path=path,
                country=_cut(body.country, 8),
                region=_cut(body.region, 16),
                city=_cut(body.city, 128),
                referrer=_cut(body.referrer, 512),
                user_agent=_cut(body.user_agent, 512),
                user_id=body.user_id or None,
            )
        )
        await db.commit()
    return Response(status_code=204)


# ---------- stats ----------


class LabelCount(ApiModel):
    label: str | None
    count: int


class RecentView(ApiModel):
    path: str
    country: str | None
    city: str | None
    referrer: str | None
    created_at: datetime


class Engagement(ApiModel):
    convos: int
    messages: int
    modules_active: int
    steps_done: int
    units_done: int
    signoffs: int


class UserRow(ApiModel):
    id: str
    email: str
    display_name: str
    role: str
    paid_until: datetime | None
    created_at: datetime


class StatsOut(ApiModel):
    users_total: int
    users1d: int
    users7d: int
    users30d: int
    pv_total: int
    pv1d: int
    pv7d: int
    pv30d: int
    unique_visitors7d: int
    top_paths: list[LabelCount]
    top_countries: list[LabelCount]
    top_referrers: list[LabelCount]
    recent_views: list[RecentView]
    engagement: Engagement
    # The latest 200 sign-ups.
    users: list[UserRow]
    include_admins: bool


# Page views, without the admins' signed-in visits unless :include_admins.
_VIEWS = """
with views as (
  select * from page_views pv
  where :include_admins
     or pv.user_id is null
     or pv.user_id not in (select id from users where lower(email) = any(cast(:admins as text[])))
)
"""

_USER_STATS = text("""
select
  count(*)::int as total,
  count(*) filter (where created_at >= now() - interval '1 day')::int as d1,
  count(*) filter (where created_at >= now() - interval '7 days')::int as d7,
  count(*) filter (where created_at >= now() - interval '30 days')::int as d30
from users
""")

_VIEW_STATS = text(
    _VIEWS
    + """
select
  count(*)::int as total,
  count(*) filter (where created_at >= now() - interval '1 day')::int as d1,
  count(*) filter (where created_at >= now() - interval '7 days')::int as d7,
  count(*) filter (where created_at >= now() - interval '30 days')::int as d30,
  count(distinct coalesce(user_id, user_agent)) filter (where created_at >= now() - interval '7 days')::int as unique7d
from views
"""
)

_TOP_PATHS = text(
    _VIEWS + "select path as label, count(*)::int as count from views group by path order by count desc limit 10"
)
_TOP_COUNTRIES = text(
    _VIEWS
    + "select coalesce(country, 'Unknown') as label, count(*)::int as count from views"
    + " group by country order by count desc limit 10"
)
_TOP_REFERRERS = text(
    _VIEWS
    + "select coalesce(nullif(referrer, ''), 'Direct / none') as label, count(*)::int as count from views"
    + " group by label order by count desc limit 10"
)
_RECENT = text(_VIEWS + "select path, country, city, referrer, created_at from views order by created_at desc limit 25")

_ENGAGEMENT = text("""
select
  (select count(*)::int from conversations) as convos,
  (select count(*)::int from messages) as messages,
  (select count(*)::int from module_enrollments where status = 'active') as modules_active,
  (select count(*)::int from step_progress where done) as steps_done,
  (select count(*)::int from unit_progress where status <> 'started') as units_done,
  (select count(*)::int from signoffs) as signoffs
""")

_USERS = text("""
select id, email, display_name, role, paid_until, created_at
from users order by created_at desc limit 200
""")


@router.get("/stats")
async def stats(
    admin: AdminDep,
    db: DbDep,
    response: Response,
    include_admins: Annotated[bool, Query(alias="includeAdmins")] = False,
) -> StatsOut:
    """Sign-ups, traffic and engagement for /admin. Admins only."""
    response.headers["Cache-Control"] = "private, no-store"
    params = {"include_admins": include_admins, "admins": get_settings().admin_emails}

    async def one(q):
        return (await db.execute(q, params)).mappings().one()

    async def many(q):
        return [dict(r) for r in (await db.execute(q, params)).mappings()]

    u, v = await one(_USER_STATS), await one(_VIEW_STATS)
    return StatsOut(
        users_total=u["total"],
        users1d=u["d1"],
        users7d=u["d7"],
        users30d=u["d30"],
        pv_total=v["total"],
        pv1d=v["d1"],
        pv7d=v["d7"],
        pv30d=v["d30"],
        unique_visitors7d=v["unique7d"],
        top_paths=await many(_TOP_PATHS),
        top_countries=await many(_TOP_COUNTRIES),
        top_referrers=await many(_TOP_REFERRERS),
        recent_views=await many(_RECENT),
        engagement=Engagement(**await one(_ENGAGEMENT)),
        users=await many(_USERS),
        include_admins=include_admins,
    )
