"""Admin tools for the people who run Hasesa (emails in ADMIN_EMAILS):
enrol a student by hand, make someone a guide, and see enrolments and payments.
The site-wide stats move here with analytics in phase 7."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field
from sqlalchemy import select, text, update

from hasesa_api.billing.payments import grant_days
from hasesa_api.db import DbDep
from hasesa_api.identity.deps import AdminDep
from hasesa_api.models import User
from hasesa_api.schemas import ApiModel

router = APIRouter(prefix="/admin", tags=["admin"])


class GrantIn(ApiModel):
    email: Annotated[str, Field(max_length=254)]
    days: Annotated[int, Field(ge=1, le=366)]
    note: str = Field(default="", max_length=1_000)


class GrantOut(ApiModel):
    email: str
    # When the student's enrolment now ends (None if the grant could not be applied).
    paid_until: datetime | None


class RoleIn(ApiModel):
    email: Annotated[str, Field(max_length=254)]
    role: Literal["student", "guide"]


class RoleOut(ApiModel):
    email: str
    role: Literal["student", "guide"]


class SubscriberStats(ApiModel):
    active: int
    ending_soon: int
    ever_paid: int
    guides: int


class PaymentOut(ApiModel):
    tx_ref: str
    email: str
    amount_etb: int
    days: int
    status: str
    source: str
    note: str | None
    created_at: datetime
    paid_until: datetime | None


class SubscribersOut(ApiModel):
    stats: SubscriberStats
    # The latest 20.
    payments: list[PaymentOut]


@router.post("/enrolments")
async def enrol(body: GrantIn, admin: AdminDep, db: DbDep) -> GrantOut:
    """Enrol a student at the Academy (or extend), after they've paid. Days add to any left."""
    email = body.email.strip().lower()
    user_id = await db.scalar(select(User.id).where(User.email == email).limit(1))
    if user_id is None:
        raise HTTPException(
            status_code=404, detail=f"No one has signed up with {email} yet. Ask them to sign up first."
        )
    until = await grant_days(db, user_id, body.days, body.note.strip() or "admin enrolment")
    return GrantOut(email=email, paid_until=until)


@router.put("/roles")
async def set_role(body: RoleIn, admin: AdminDep, db: DbDep) -> RoleOut:
    """Make an account the Academy's guide, or back into a student."""
    email = body.email.strip().lower()
    res = await db.execute(update(User).where(User.email == email).values(role=body.role).returning(User.id))
    if res.first() is None:
        raise HTTPException(
            status_code=404, detail=f"No one has signed up with {email} yet. Ask them to sign in with Google first."
        )
    await db.commit()
    return RoleOut(email=email, role=body.role)


_STATS = text(
    """
    select
      count(*) filter (where paid_until > now() and role <> 'guide')::int as active,
      count(*) filter (where paid_until > now() and paid_until < now() + interval '7 days' and role <> 'guide')::int
        as ending_soon,
      count(*) filter (where paid_until is not null and role <> 'guide')::int as ever_paid,
      count(*) filter (where role = 'guide')::int as guides
    from users
    """
)

_PAYMENTS = text(
    """
    select p.tx_ref, u.email, p.amount_etb, p.days, p.status, p.source, p.note, p.created_at, u.paid_until
    from payments p join users u on u.id = p.user_id
    order by p.created_at desc
    limit 20
    """
)


@router.get("/subscribers")
async def subscribers(admin: AdminDep, db: DbDep, response: Response) -> SubscribersOut:
    """Enrolment counts and the latest 20 payments."""
    response.headers["Cache-Control"] = "private, no-store"
    stats = (await db.execute(_STATS)).mappings().one()
    payments = (await db.execute(_PAYMENTS)).mappings().all()
    return SubscribersOut(stats=SubscriberStats(**stats), payments=[PaymentOut(**p) for p in payments])
