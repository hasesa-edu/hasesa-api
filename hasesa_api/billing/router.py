"""Paying for the Academy with Chapa.

Neither the webhook nor the return page is trusted on its own: each one only
triggers a fresh verify call to Chapa, and claiming a payment is idempotent on
tx_ref. The website's old webhook can run alongside this one while the Chapa
dashboard is switched over.
"""

import json
from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import Field

from hasesa_api.billing import chapa, payments
from hasesa_api.config import get_settings
from hasesa_api.db import DbDep
from hasesa_api.identity import sessions
from hasesa_api.identity.deps import ClaimsDep, CurrentUserDep
from hasesa_api.schemas import ApiModel

router = APIRouter(prefix="/billing", tags=["billing"])

RETURN_PATH = "/billing/return"
MAX_WEBHOOK_BYTES = 64 * 1024


class CheckoutIn(ApiModel):
    # Where Chapa sends the student afterwards: <site origin>/billing/return.
    # The origin must be one the app is allowed to sign in from; ?tx_ref= is added here.
    return_url: str = Field(max_length=500)


class CheckoutOut(ApiModel):
    checkout_url: str
    tx_ref: str


class PaymentStateOut(ApiModel):
    state: payments.State
    # The student's enrolment end after this check (None if never enrolled).
    paid_until: datetime | None


class WebhookOut(ApiModel):
    ok: bool = True
    ignored: bool | None = None
    state: payments.State | None = None


async def _check_return_url(db: DbDep, client_id: str, url: str) -> None:
    """Same allowlist as sign-in: the origin must be one the client may sign in from."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    client = await sessions.get_client(db, client_id)
    if (
        parts.path != RETURN_PATH
        or parts.query
        or parts.fragment
        or not sessions.redirect_allowed(client, f"{origin}/api/auth/callback")
    ):
        raise HTTPException(status_code=400, detail="This return address isn't allowed.")


@router.post("/checkout")
async def checkout(body: CheckoutIn, user: CurrentUserDep, claims: ClaimsDep, db: DbDep) -> CheckoutOut:
    """Start a Chapa checkout for one 30-day pass. Send the student to checkoutUrl."""
    await _check_return_url(db, claims.client_id, body.return_url)
    tx_ref = await payments.create_pending_payment(db, user.id)
    first, _, rest = user.display_name.strip().partition(" ")
    try:
        url = await chapa.initialize_checkout(
            tx_ref=tx_ref,
            amount_etb=payments.PRICE_ETB,
            email=user.email,
            first_name=first or None,
            last_name=rest.strip() or None,
            return_url=f"{body.return_url}?{urlencode({'tx_ref': tx_ref})}",
            callback_url=f"{get_settings().api_base_url.rstrip('/')}/v1/billing/chapa/webhook",
        )
    except chapa.ChapaError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return CheckoutOut(checkout_url=url, tx_ref=tx_ref)


@router.get("/payments/{tx_ref}")
async def payment_state(tx_ref: str, user: CurrentUserDep, db: DbDep) -> PaymentStateOut:
    """Check a payment after Chapa sends the student back. Verifies with Chapa first.
    Someone else's payment looks the same as an unknown one."""
    state: payments.State = "unknown"
    if await payments.payment_owner(db, tx_ref) == user.id:
        state = (await payments.verify_and_apply(db, tx_ref)).state
    await db.refresh(user)
    return PaymentStateOut(state=state, paid_until=user.paid_until)


async def _apply_from_chapa(db: DbDep, tx_ref: object) -> WebhookOut:
    # Only our own transaction references; ignore transfers and other events.
    if not isinstance(tx_ref, str) or not tx_ref.startswith(payments.TX_PREFIX) or len(tx_ref) > 100:
        return WebhookOut(ignored=True)
    return WebhookOut(state=(await payments.verify_and_apply(db, tx_ref)).state)


@router.post("/chapa/webhook", responses={401: {}, 413: {}})
async def chapa_webhook(
    request: Request,
    db: DbDep,
    x_chapa_signature: Annotated[str | None, Header()] = None,
    chapa_signature: Annotated[str | None, Header()] = None,
) -> WebhookOut:
    """Chapa's signed webhook."""
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    if not chapa.is_valid_webhook_signature(raw, x_chapa_signature, chapa_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        body = json.loads(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Bad JSON") from e
    return await _apply_from_chapa(db, body.get("tx_ref") if isinstance(body, dict) else None)


@router.get("/chapa/webhook")
async def chapa_callback(db: DbDep, trx_ref: str | None = None, tx_ref: str | None = None) -> WebhookOut:
    """Chapa's callback_url (GET with ?trx_ref=). Unsigned, so it only triggers a verify."""
    return await _apply_from_chapa(db, trx_ref or tx_ref)
