"""Hasesa Accounts endpoints: Google sign-in, tokens, sign-out and the current user."""

import logging
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from hasesa_api.config import get_settings
from hasesa_api.db import DbDep
from hasesa_api.identity import google, sessions, tokens
from hasesa_api.identity.deps import ClaimsDep, CurrentUserDep
from hasesa_api.identity.users import (
    EmailTakenError,
    ProfilePatch,
    UserOut,
    update_profile,
    upsert_google_user,
    user_out,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["accounts"])
well_known = APIRouter(tags=["accounts"])

REQUEST_COOKIE = "hasesa_auth_req"
COOKIE_PATH = "/v1/auth/google"


# ---------- schemas (token endpoints follow OAuth's snake_case) ----------


class TokenRequest(BaseModel):
    grant_type: Literal["authorization_code", "refresh_token"]
    client_id: str = Field(max_length=100)
    client_secret: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=200)
    redirect_uri: str | None = Field(default=None, max_length=500)
    code_verifier: str | None = Field(default=None, max_length=128)
    refresh_token: str | None = Field(default=None, max_length=300)


class IdTokenRequest(BaseModel):
    client_id: str = Field(max_length=100)
    id_token: str = Field(max_length=4096)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(max_length=300)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    refresh_token: str
    session_expires_at: datetime
    user_id: str
    session_id: str
    is_new_user: bool = False


def _token_response(t: sessions.TokenSet, *, is_new_user: bool = False) -> TokenResponse:
    return TokenResponse(
        access_token=t.access_token,
        expires_in=t.expires_in,
        refresh_token=t.refresh_token,
        session_expires_at=t.session_expires_at,
        user_id=t.user_id,
        session_id=t.session_id,
        is_new_user=is_new_user,
    )


def _auth_error(e: sessions.AuthError) -> JSONResponse:
    status = 401 if e.code == "invalid_client" else 400
    return JSONResponse({"error": e.code, "error_description": str(e)}, status_code=status)


def _with_query(url: str, params: dict[str, str | None]) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return f"{url}{'&' if '?' in url else '?'}{query}"


# ---------- browser sign-in ----------


@router.get("/auth/google/start", response_class=RedirectResponse, status_code=302)
async def google_start(
    db: DbDep,
    client_id: Annotated[str, Query(max_length=100)],
    redirect_uri: Annotated[str, Query(max_length=500)],
    code_challenge: Annotated[str, Query(min_length=43, max_length=128)],
    code_challenge_method: Annotated[Literal["S256"], Query()] = "S256",
    state: Annotated[str | None, Query(max_length=500)] = None,
) -> RedirectResponse:
    """Start "Continue with Google" for a web client. Ends with a redirect to `redirect_uri` with a one-time code."""
    try:
        client = await sessions.get_client(db, client_id)
    except sessions.AuthError as e:
        raise HTTPException(status_code=400, detail="Unknown client.") from e
    # Never redirect anywhere that isn't registered for the client.
    if client.kind != "web" or not sessions.redirect_allowed(client, redirect_uri):
        raise HTTPException(status_code=400, detail="This redirect address is not allowed.")
    req, google_verifier = await sessions.start_request(
        db, client=client, redirect_uri=redirect_uri, client_state=state, code_challenge=code_challenge
    )
    await db.commit()
    url = google.authorization_url(state=req.id, code_challenge=tokens.sha256_b64(google_verifier))
    res = RedirectResponse(url, status_code=302)
    res.set_cookie(
        REQUEST_COOKIE,
        req.id,
        max_age=int(sessions.AUTH_REQUEST_TTL.total_seconds()),
        path=COOKIE_PATH,
        httponly=True,
        secure=get_settings().is_production,
        samesite="lax",
    )
    return res


@router.get("/auth/google/callback", response_class=RedirectResponse, status_code=302)
async def google_callback(
    db: DbDep,
    state: Annotated[str, Query(max_length=200)],
    code: Annotated[str | None, Query(max_length=2000)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
    request_cookie: Annotated[str | None, Cookie(alias=REQUEST_COOKIE)] = None,
) -> RedirectResponse:
    """Google sends the browser back here."""
    try:
        req = await sessions.take_request(db, state)
    except sessions.AuthError as e:
        await db.commit()
        raise HTTPException(status_code=400, detail="This sign-in link expired. Please try again.") from e
    # Copy what the redirect needs now: a rollback below would expire `req`.
    redirect_uri, client_state = req.redirect_uri, req.client_state
    await db.commit()  # the request is single-use, whatever happens next

    def back(**params: str | None) -> RedirectResponse:
        res = RedirectResponse(_with_query(redirect_uri, {**params, "state": client_state}), status_code=302)
        res.delete_cookie(REQUEST_COOKIE, path=COOKIE_PATH)
        return res

    # The cookie ties the callback to the browser that started the sign-in.
    if request_cookie != req.id:
        return back(error="state")
    if error or not code:
        return back(error="cancelled")
    try:
        id_token = await google.exchange_code(code, req.google_verifier)
        profile = await google.verify_id_token(id_token)
    except google.UnverifiedEmail:
        return back(error="email")
    except (google.GoogleError, OSError) as e:
        log.warning("google sign-in failed: %s", e)
        return back(error="google")
    try:
        user_id, is_new = await upsert_google_user(db, profile)
    except EmailTakenError:
        await db.rollback()
        return back(error="taken")
    one_time_code = await sessions.issue_code(db, req=req, user_id=user_id, is_new_user=is_new)
    await db.commit()
    return back(code=one_time_code)


# ---------- tokens ----------


@router.post("/auth/token", responses={400: {}, 401: {}})
async def token(body: TokenRequest, db: DbDep, user_agent: Annotated[str | None, Header()] = None) -> TokenResponse:
    """Redeem a one-time code, or refresh a session."""
    try:
        client = await sessions.get_client(db, body.client_id)
        sessions.check_client_secret(client, body.client_secret, get_settings().client_secrets)
        if body.grant_type == "authorization_code":
            if not body.code or not body.redirect_uri or not body.code_verifier:
                raise sessions.AuthError("invalid_request", "code, redirect_uri and code_verifier are required")
            grant = await sessions.redeem_code(
                db,
                code=body.code,
                client_id=client.id,
                redirect_uri=body.redirect_uri,
                code_verifier=body.code_verifier,
            )
            tokens_ = await sessions.create_session(db, user_id=grant.user_id, client=client, user_agent=user_agent)
            await db.commit()
            return _token_response(tokens_, is_new_user=grant.is_new_user)
        if not body.refresh_token:
            raise sessions.AuthError("invalid_request", "refresh_token is required")
        tokens_ = await sessions.refresh_session(db, refresh_token=body.refresh_token, client=client)
        await db.commit()
        return _token_response(tokens_)
    except sessions.AuthError as e:
        await db.commit()  # keep a revocation made while detecting token reuse
        return _auth_error(e)  # type: ignore[return-value]


@router.post("/auth/google/id-token", responses={400: {}, 401: {}})
async def google_id_token(
    body: IdTokenRequest, db: DbDep, user_agent: Annotated[str | None, Header()] = None
) -> TokenResponse:
    """Sign in from a mobile app with a Google ID token from native Google Sign-In."""
    try:
        client = await sessions.get_client(db, body.client_id)
        if client.kind != "native":
            raise sessions.AuthError("unauthorized_client", "this client must use the browser sign-in flow")
        try:
            profile = await google.verify_id_token(body.id_token)
        except google.UnverifiedEmail as e:
            raise sessions.AuthError("email", "Google did not confirm this account's email") from e
        except (google.GoogleError, OSError) as e:
            raise sessions.AuthError("invalid_grant", "invalid Google ID token") from e
        try:
            user_id, is_new = await upsert_google_user(db, profile)
        except EmailTakenError as e:
            await db.rollback()
            raise sessions.AuthError("taken", "this email belongs to another Google account") from e
        tokens_ = await sessions.create_session(db, user_id=user_id, client=client, user_agent=user_agent)
        await db.commit()
        return _token_response(tokens_, is_new_user=is_new)
    except sessions.AuthError as e:
        return _auth_error(e)  # type: ignore[return-value]


# ---------- sign out ----------


@router.post("/auth/logout", status_code=204)
async def logout(body: LogoutRequest, db: DbDep) -> Response:
    """End the session a refresh token belongs to. Always succeeds, so it reveals nothing."""
    try:
        session_id, _ = tokens.parse_refresh_token(body.refresh_token)
    except tokens.TokenError:
        return Response(status_code=204)
    await sessions.revoke_session(db, session_id)
    await db.commit()
    return Response(status_code=204)


@router.post("/auth/logout-all", status_code=204)
async def logout_all(claims: ClaimsDep, db: DbDep) -> Response:
    """Sign out on every device."""
    await sessions.revoke_all_sessions(db, claims.user_id)
    await db.commit()
    return Response(status_code=204)


# ---------- the signed-in user ----------


@router.get("/me")
async def me(user: CurrentUserDep) -> UserOut:
    return user_out(user)


@router.patch("/me")
async def update_me(patch: ProfilePatch, user: CurrentUserDep, db: DbDep) -> UserOut:
    await update_profile(db, user.id, patch)
    await db.commit()
    await db.refresh(user)
    return user_out(user)


# ---------- public keys ----------


@well_known.get("/.well-known/jwks.json")
async def jwks(response: Response) -> dict:
    """Public keys for verifying Hasesa access tokens."""
    response.headers["Cache-Control"] = "public, max-age=3600"
    return tokens.jwks()
