import time

import pytest

from hasesa_api.access import access_level, has_full_access
from hasesa_api.config import Settings
from hasesa_api.identity import google, tokens
from hasesa_api.identity.sessions import redirect_allowed
from hasesa_api.models import OAuthClient

# ---------- access tokens ----------


def test_access_token_round_trip() -> None:
    token = tokens.issue_access_token(user_id="u1", session_id="s1", client_id="hasesa-web")
    claims = tokens.verify_access_token(token)
    assert (claims.user_id, claims.session_id, claims.client_id) == ("u1", "s1", "hasesa-web")


def test_expired_access_token_is_rejected() -> None:
    old = int(time.time()) - tokens.ACCESS_TOKEN_SECONDS - 60
    token = tokens.issue_access_token(user_id="u1", session_id="s1", client_id="c", now=old)
    with pytest.raises(tokens.TokenError):
        tokens.verify_access_token(token)


def test_tampered_access_token_is_rejected() -> None:
    token = tokens.issue_access_token(user_id="u1", session_id="s1", client_id="c")
    header, payload, sig = token.split(".")
    with pytest.raises(tokens.TokenError):
        tokens.verify_access_token(f"{header}.{payload}.{sig[:-4]}AAAA")


def test_jwks_publishes_only_the_public_key() -> None:
    (key,) = tokens.jwks()["keys"]
    assert key["kty"] == "RSA" and key["alg"] == "RS256" and key["use"] == "sig"
    assert "d" not in key and "p" not in key  # no private parts


# ---------- refresh tokens ----------


def test_refresh_token_round_trip() -> None:
    assert tokens.parse_refresh_token(tokens.make_refresh_token("abc", 7)) == ("abc", 7)


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "abc.1", "abc.x.mac", "abc.1.forged", "abc.1234567890.mac"],
)
def test_malformed_or_forged_refresh_tokens_are_rejected(bad: str) -> None:
    with pytest.raises(tokens.TokenError):
        tokens.parse_refresh_token(bad)


def test_refresh_token_for_other_generation_does_not_verify() -> None:
    sid, _, mac = tokens.make_refresh_token("abc", 1).split(".")
    with pytest.raises(tokens.TokenError):
        tokens.parse_refresh_token(f"{sid}.2.{mac}")


# ---------- PKCE ----------


def test_pkce_s256() -> None:
    verifier = "a" * 43
    assert tokens.pkce_matches(verifier, tokens.sha256_b64(verifier))
    assert not tokens.pkce_matches("b" * 43, tokens.sha256_b64(verifier))
    assert not tokens.pkce_matches("short", tokens.sha256_b64("short"))


# ---------- redirect allowlist ----------


def _client(*uris: str) -> OAuthClient:
    return OAuthClient(id="c", name="c", kind="web", confidential=True, redirect_uris=list(uris), session_days=30)


def test_exact_redirect_match() -> None:
    c = _client("https://www.hasesa.com/api/auth/callback")
    assert redirect_allowed(c, "https://www.hasesa.com/api/auth/callback")
    assert not redirect_allowed(c, "https://www.hasesa.com/api/auth/callback?x=1")
    assert not redirect_allowed(c, "https://www.hasesa.com.evil.com/api/auth/callback")


def test_wildcard_redirect_covers_previews_only() -> None:
    c = _client("https://ai-edu-*-w-yidnes-projects.vercel.app/api/auth/callback")
    assert redirect_allowed(c, "https://ai-edu-git-main-w-yidnes-projects.vercel.app/api/auth/callback")
    # The wildcard must stand for at least one character.
    assert not redirect_allowed(c, "https://ai-edu-w-yidnes-projects.vercel.app/api/auth/callback")
    assert not redirect_allowed(c, "https://ai-edu-x.evil.com/-w-yidnes-projects.vercel.app/api/auth/callback")
    assert not redirect_allowed(c, "https://ai-edu-a/b-w-yidnes-projects.vercel.app/api/auth/callback")
    assert not redirect_allowed(c, "https://ai-edu-x-w-yidnes-projects.vercel.app/other")


# ---------- Google claims ----------


def test_google_profile_requires_verified_email() -> None:
    claims = {"sub": "g1", "email": "a@b.c", "email_verified": True, "name": "A", "picture": "https://p"}
    assert google.profile_from_claims(claims).sub == "g1"
    with pytest.raises(google.UnverifiedEmail):
        google.profile_from_claims({**claims, "email_verified": False})
    with pytest.raises(google.UnverifiedEmail):
        google.profile_from_claims({**claims, "email": ""})


# ---------- settings and access ----------


def test_client_secrets_parse() -> None:
    s = Settings(client_secrets="hasesa-web:abc, other:def")
    assert s.client_secrets == {"hasesa-web": "abc", "other": "def"}
    with pytest.raises(ValueError):
        Settings(client_secrets="no-colon")


def test_access_levels() -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    assert access_level("guide", None) == "guide"
    assert access_level("student", now + timedelta(days=1)) == "enrolled"
    assert access_level("student", now - timedelta(days=1)) == "signed-in"
    assert access_level("student", None) == "signed-in"
    assert has_full_access("enrolled") and has_full_access("guide") and not has_full_access("signed-in")
