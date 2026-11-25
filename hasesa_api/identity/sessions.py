"""Clients, sign-in requests, one-time codes and sessions."""

import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hasesa_api.identity import tokens
from hasesa_api.models import AuthCode, AuthRequest, AuthSession, OAuthClient

AUTH_REQUEST_TTL = timedelta(minutes=10)
AUTH_CODE_TTL = timedelta(seconds=60)
# A refresh that repeats the previous generation this soon after a rotation is
# treated as a parallel duplicate, not as a stolen token.
REFRESH_GRACE = timedelta(seconds=60)

_WILDCARD_PART = re.compile(r"[a-z0-9-]+")


class AuthError(Exception):
    """Sign-in or token request rejected. `code` is a short machine-readable reason."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


# ---------- clients ----------


def redirect_allowed(client: OAuthClient, uri: str) -> bool:
    for allowed in client.redirect_uris:
        if "*" not in allowed:
            if uri == allowed:
                return True
            continue
        prefix, _, suffix = allowed.partition("*")
        if (
            uri.startswith(prefix)
            and uri.endswith(suffix)
            and len(uri) > len(prefix) + len(suffix)
            and _WILDCARD_PART.fullmatch(uri[len(prefix) : len(uri) - len(suffix)])
        ):
            return True
    return False


async def get_client(db: AsyncSession, client_id: str) -> OAuthClient:
    client = await db.get(OAuthClient, client_id)
    if client is None:
        raise AuthError("invalid_client", "unknown client")
    return client


def check_client_secret(client: OAuthClient, secret: str | None, configured: dict[str, str]) -> None:
    if not client.confidential:
        return
    expected = configured.get(client.id)
    if not expected or not secret or not hmac.compare_digest(secret, expected):
        raise AuthError("invalid_client", "client authentication failed")


# ---------- browser sign-in requests ----------


async def start_request(
    db: AsyncSession, *, client: OAuthClient, redirect_uri: str, client_state: str | None, code_challenge: str
) -> tuple[AuthRequest, str]:
    """Record a sign-in in progress. Returns it and the PKCE verifier to use with Google."""
    await db.execute(delete(AuthRequest).where(AuthRequest.expires_at < _now()))
    google_verifier = tokens.random_id(48)
    req = AuthRequest(
        id=tokens.random_id(),
        client_id=client.id,
        redirect_uri=redirect_uri,
        client_state=client_state,
        code_challenge=code_challenge,
        google_verifier=google_verifier,
        expires_at=_now() + AUTH_REQUEST_TTL,
    )
    db.add(req)
    return req, google_verifier


async def take_request(db: AsyncSession, request_id: str) -> AuthRequest:
    """Fetch and delete a sign-in request, so its state can only be used once."""
    req = await db.scalar(delete(AuthRequest).where(AuthRequest.id == request_id).returning(AuthRequest))
    if req is None or req.expires_at < _now():
        raise AuthError("state", "sign-in request expired or unknown")
    return req


# ---------- one-time codes ----------


async def issue_code(db: AsyncSession, *, req: AuthRequest, user_id: str, is_new_user: bool) -> str:
    await db.execute(delete(AuthCode).where(AuthCode.expires_at < _now() - timedelta(days=1)))
    code = tokens.random_id()
    db.add(
        AuthCode(
            code_hash=tokens.sha256_b64(code),
            user_id=user_id,
            client_id=req.client_id,
            redirect_uri=req.redirect_uri,
            code_challenge=req.code_challenge,
            is_new_user=is_new_user,
            expires_at=_now() + AUTH_CODE_TTL,
        )
    )
    return code


async def redeem_code(
    db: AsyncSession, *, code: str, client_id: str, redirect_uri: str, code_verifier: str
) -> AuthCode:
    row = await db.scalar(select(AuthCode).where(AuthCode.code_hash == tokens.sha256_b64(code)).with_for_update())
    if (
        row is None
        or row.used_at is not None
        or row.expires_at < _now()
        or row.client_id != client_id
        or row.redirect_uri != redirect_uri
    ):
        raise AuthError("invalid_grant", "code invalid, expired or already used")
    if not tokens.pkce_matches(code_verifier, row.code_challenge):
        raise AuthError("invalid_grant", "PKCE verification failed")
    row.used_at = _now()
    return row


# ---------- sessions ----------


@dataclass(frozen=True)
class TokenSet:
    user_id: str
    session_id: str
    access_token: str
    refresh_token: str
    expires_in: int
    session_expires_at: datetime


def _token_set(session: AuthSession) -> TokenSet:
    return TokenSet(
        user_id=session.user_id,
        session_id=session.id,
        access_token=tokens.issue_access_token(
            user_id=session.user_id, session_id=session.id, client_id=session.client_id
        ),
        refresh_token=tokens.make_refresh_token(session.id, session.generation),
        expires_in=tokens.ACCESS_TOKEN_SECONDS,
        session_expires_at=session.expires_at,
    )


async def create_session(db: AsyncSession, *, user_id: str, client: OAuthClient, user_agent: str | None) -> TokenSet:
    now = _now()
    session = AuthSession(
        id=tokens.random_id(18),
        user_id=user_id,
        client_id=client.id,
        generation=0,
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=client.session_days),
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(session)
    await db.flush()
    return _token_set(session)


async def refresh_session(db: AsyncSession, *, refresh_token: str, client: OAuthClient) -> TokenSet:
    """Rotate a refresh token. The caller must commit even when this raises (reuse revokes the session)."""
    try:
        session_id, generation = tokens.parse_refresh_token(refresh_token)
    except tokens.TokenError as e:
        raise AuthError("invalid_grant", "invalid refresh token") from e

    # Lock the row so parallel refreshes of one session run one after another.
    session = await db.scalar(select(AuthSession).where(AuthSession.id == session_id).with_for_update())
    now = _now()
    if session is None or session.client_id != client.id or session.revoked_at is not None:
        raise AuthError("invalid_grant", "session ended")
    if session.expires_at <= now:
        raise AuthError("invalid_grant", "session expired")

    if generation == session.generation:
        session.generation += 1
        session.rotated_at = now
        session.last_used_at = now
        session.expires_at = now + timedelta(days=client.session_days)
    elif (
        generation == session.generation - 1
        and session.rotated_at is not None
        and now - session.rotated_at <= REFRESH_GRACE
    ):
        pass  # a parallel duplicate of the refresh that just happened: same answer again
    else:
        # An old refresh token came back: someone may have stolen it. End the session.
        session.revoked_at = now
        raise AuthError("invalid_grant", "refresh token reused; session ended")
    return _token_set(session)


async def revoke_session(db: AsyncSession, session_id: str) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def revoke_all_sessions(db: AsyncSession, user_id: str) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def session_active(db: AsyncSession, session_id: str) -> bool:
    row = await db.scalar(
        select(AuthSession.id).where(
            AuthSession.id == session_id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > _now()
        )
    )
    return row is not None
