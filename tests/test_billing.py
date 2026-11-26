"""Chapa checkout, return-page checks and the webhook. Chapa itself is faked."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from hasesa_api import config, db
from hasesa_api.billing import chapa
from hasesa_api.models import Payment, User
from tests.test_accounts import bearer, profile, sign_in

RETURN = "https://www.hasesa.com/billing/return"


# ---------- signatures (no database) ----------


def _sig(key: str, data: bytes) -> str:
    return hmac.new(key.encode(), data, hashlib.sha256).hexdigest()


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("CHAPA_SECRET_KEY", "CHASECK_TEST-abc")
    monkeypatch.setenv("CHAPA_WEBHOOK_SECRET", "hook-secret")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_webhook_signature_of_the_payload_or_the_secret(keys) -> None:
    raw = b'{"tx_ref":"hl-1"}'
    assert chapa.is_valid_webhook_signature(raw, _sig("hook-secret", raw), None)
    assert chapa.is_valid_webhook_signature(raw, _sig("CHASECK_TEST-abc", raw), None)
    assert chapa.is_valid_webhook_signature(raw, None, _sig("hook-secret", b"hook-secret"))
    assert not chapa.is_valid_webhook_signature(raw, _sig("wrong", raw), None)
    assert not chapa.is_valid_webhook_signature(raw, None, None)
    assert not chapa.is_valid_webhook_signature(raw, "é", None)


# ---------- end to end (database) ----------


@pytest.fixture
def fake_chapa(monkeypatch, keys):
    """Chapa's answers by tx_ref; initialize records what it was sent."""
    txs: dict[str, chapa.VerifiedTx] = {}
    started: list[dict] = []

    async def initialize_checkout(**kw) -> str:
        started.append(kw)
        return f"https://checkout.chapa.co/{kw['tx_ref']}"

    async def verify_transaction(tx_ref: str):
        return txs.get(tx_ref)

    monkeypatch.setattr(chapa, "initialize_checkout", initialize_checkout)
    monkeypatch.setattr(chapa, "verify_transaction", verify_transaction)
    return txs, started


async def student(api, fake_google, sub="s", email="student@example.com", **values) -> dict:
    fake_google[sub] = profile(sub, email)
    t = await sign_in(api, sub)
    if values:
        async with db.get_sessionmaker()() as s:
            await s.execute(update(User).where(User.id == t["user_id"]).values(**values))
            await s.commit()
    return t


async def start(api, t) -> dict:
    r = await api.post("/v1/billing/checkout", json={"returnUrl": RETURN}, headers=bearer(t))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.anyio
async def test_checkout_then_return_page_activates_the_pass(api, fake_google, fake_chapa) -> None:
    txs, started = fake_chapa
    t = await student(api, fake_google, paid_until=None)
    out = await start(api, t)
    tx = out["txRef"]
    assert tx.startswith("hl-") and out["checkoutUrl"].endswith(tx)
    assert started[0]["return_url"] == f"{RETURN}?tx_ref={tx}"
    assert started[0]["callback_url"] == "http://test/v1/billing/chapa/webhook"
    assert (started[0]["amount_etb"], started[0]["first_name"], started[0]["last_name"]) == (300, "Student", "One")

    r = await api.get(f"/v1/billing/payments/{tx}", headers=bearer(t))
    assert r.json() == {"state": "pending", "paidUntil": None}

    txs[tx] = chapa.VerifiedTx("success", 300, "ETB", "CH-1")
    r = await api.get(f"/v1/billing/payments/{tx}", headers=bearer(t))
    body = r.json()
    assert body["state"] == "paid"
    until = datetime.fromisoformat(body["paidUntil"])
    assert abs(until - (datetime.now(UTC) + timedelta(days=30))) < timedelta(minutes=1)

    # Applying again changes nothing.
    again = (await api.get(f"/v1/billing/payments/{tx}", headers=bearer(t))).json()
    assert again == body


@pytest.mark.anyio
async def test_days_stack_on_top_of_days_left(api, fake_google, fake_chapa) -> None:
    txs, _ = fake_chapa
    left = datetime.now(UTC) + timedelta(days=5)
    t = await student(api, fake_google, paid_until=left)
    tx = (await start(api, t))["txRef"]
    txs[tx] = chapa.VerifiedTx("success", 300, "ETB", None)
    until = datetime.fromisoformat((await api.get(f"/v1/billing/payments/{tx}", headers=bearer(t))).json()["paidUntil"])
    assert abs(until - (left + timedelta(days=30))) < timedelta(seconds=5)


@pytest.mark.anyio
async def test_wrong_amount_goes_to_review_and_failed_stays_failed(api, fake_google, fake_chapa) -> None:
    txs, _ = fake_chapa
    t = await student(api, fake_google, paid_until=None)
    short, failed = (await start(api, t))["txRef"], (await start(api, t))["txRef"]
    txs[short] = chapa.VerifiedTx("success", 30, "ETB", "CH-2")
    txs[failed] = chapa.VerifiedTx("failed", 300, "ETB", None)
    assert (await api.get(f"/v1/billing/payments/{short}", headers=bearer(t))).json() == {
        "state": "review",
        "paidUntil": None,
    }
    assert (await api.get(f"/v1/billing/payments/{failed}", headers=bearer(t))).json()["state"] == "failed"
    async with db.get_sessionmaker()() as s:
        p = await s.get(Payment, short)
        assert (p.status, p.note, p.chapa_ref) == ("review", "Chapa reported 30 ETB", "CH-2")


@pytest.mark.anyio
async def test_someone_elses_payment_looks_unknown(api, fake_google, fake_chapa) -> None:
    txs, _ = fake_chapa
    owner = await student(api, fake_google)
    other = await student(api, fake_google, "o", "other@example.com")
    tx = (await start(api, owner))["txRef"]
    txs[tx] = chapa.VerifiedTx("success", 300, "ETB", None)
    assert (await api.get(f"/v1/billing/payments/{tx}", headers=bearer(other))).json()["state"] == "unknown"
    async with db.get_sessionmaker()() as s:
        assert (await s.get(Payment, tx)).status == "pending"


@pytest.mark.anyio
async def test_return_url_must_be_an_allowed_site(api, fake_google, fake_chapa) -> None:
    t = await student(api, fake_google)
    for bad in ("https://evil.example/billing/return", f"{RETURN}?x=1", "https://www.hasesa.com/elsewhere"):
        r = await api.post("/v1/billing/checkout", json={"returnUrl": bad}, headers=bearer(t))
        assert r.status_code == 400, bad
    assert (await api.post("/v1/billing/checkout", json={"returnUrl": RETURN})).status_code == 401
    async with db.get_sessionmaker()() as s:
        assert (await s.scalars(select(Payment))).all() == []


@pytest.mark.anyio
async def test_signed_webhook_and_callback_apply_the_payment_once(api, fake_google, fake_chapa) -> None:
    txs, _ = fake_chapa
    t = await student(api, fake_google, paid_until=None)
    tx = (await start(api, t))["txRef"]
    raw = json.dumps({"tx_ref": tx, "status": "success"}).encode()

    unsigned = await api.post("/v1/billing/chapa/webhook", content=raw)
    assert unsigned.status_code == 401
    signed = await api.post(
        "/v1/billing/chapa/webhook", content=raw, headers={"x-chapa-signature": _sig("hook-secret", raw)}
    )
    assert signed.json() == {"ok": True, "ignored": None, "state": "pending"}

    txs[tx] = chapa.VerifiedTx("success", 300, "ETB", None)
    r = await api.get("/v1/billing/chapa/webhook", params={"trx_ref": tx})
    assert r.json()["state"] == "paid"
    signed = await api.post(
        "/v1/billing/chapa/webhook", content=raw, headers={"x-chapa-signature": _sig("hook-secret", raw)}
    )
    assert signed.json()["state"] == "paid"
    async with db.get_sessionmaker()() as s:
        u = await s.get(User, t["user_id"])
        assert abs(u.paid_until - (datetime.now(UTC) + timedelta(days=30))) < timedelta(minutes=1)

    other = json.dumps({"tx_ref": "transfer-1"}).encode()
    r = await api.post(
        "/v1/billing/chapa/webhook", content=other, headers={"x-chapa-signature": _sig("hook-secret", other)}
    )
    assert r.json()["ignored"] is True
