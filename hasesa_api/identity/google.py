"""Google sign-in: the browser redirect flow and ID token verification."""

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

import anyio
import httpx
import jwt

from hasesa_api.config import get_settings

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class GoogleError(Exception):
    """Google refused the sign-in, or returned something we can't trust."""


@dataclass(frozen=True)
class GoogleProfile:
    sub: str
    email: str
    name: str | None
    picture: str | None


def redirect_uri() -> str:
    return f"{get_settings().api_base_url}/v1/auth/google/callback"


def authorization_url(*, state: str, code_challenge: str) -> str:
    settings = get_settings()
    if not settings.google_client_id:
        raise GoogleError("GOOGLE_CLIENT_ID is not set")
    query = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


async def exchange_code(code: str, verifier: str) -> str:
    """Swap Google's authorization code for an ID token."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
    if res.status_code != 200:
        raise GoogleError(f"token exchange failed ({res.status_code})")
    id_token = res.json().get("id_token")
    if not isinstance(id_token, str):
        raise GoogleError("no id_token in Google's response")
    return id_token


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    # Caches Google's public keys; they rotate every few weeks.
    return jwt.PyJWKClient(CERTS_URL, cache_keys=True, lifespan=3600)


def _decode(id_token: str, audiences: list[str]) -> dict:
    key = _jwks_client().get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token,
        key.key,
        algorithms=["RS256"],
        audience=audiences,
        options={"require": ["exp", "iat", "iss", "sub", "aud"]},
    )


def allowed_audiences() -> list[str]:
    settings = get_settings()
    return [a for a in [settings.google_client_id, *settings.google_native_client_ids] if a]


async def verify_id_token(id_token: str) -> GoogleProfile:
    """Check a Google ID token's signature, issuer, audience and expiry."""
    audiences = allowed_audiences()
    if not audiences:
        raise GoogleError("no Google client IDs configured")
    try:
        # PyJWKClient fetches keys with blocking I/O, so keep it off the event loop.
        claims = await anyio.to_thread.run_sync(_decode, id_token, audiences)
    except (jwt.PyJWTError, OSError) as e:
        raise GoogleError(f"invalid ID token: {e}") from e
    if claims.get("iss") not in ISSUERS:
        raise GoogleError("ID token from an unexpected issuer")
    return profile_from_claims(claims)


class UnverifiedEmail(GoogleError):
    """Google didn't confirm the account's email address."""


def profile_from_claims(claims: dict) -> GoogleProfile:
    sub, email = claims.get("sub"), claims.get("email")
    if not isinstance(sub, str) or not sub or not isinstance(email, str) or not email:
        raise UnverifiedEmail("ID token has no subject or email")
    if claims.get("email_verified") is not True:
        raise UnverifiedEmail("email not verified by Google")
    name, picture = claims.get("name"), claims.get("picture")
    return GoogleProfile(
        sub=sub,
        email=email,
        name=name if isinstance(name, str) else None,
        picture=picture if isinstance(picture, str) else None,
    )
