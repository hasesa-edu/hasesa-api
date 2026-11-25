# Hasesa Accounts

One Hasesa account works in every Hasesa app. People sign in with Google; the
API then issues its own tokens.

## Tokens

| Token | Lifetime | What it is |
|---|---|---|
| Access token | 15 minutes | RS256 JWT. Send as `Authorization: Bearer <token>`. Claims: `iss` (this API), `sub` (user ID), `aud` (client ID), `sid` (session ID). Verify with the keys at `/.well-known/jwks.json`. |
| Refresh token | the session | Opaque. Swap it at `POST /v1/auth/token` for a new access token and a new refresh token. Store only the newest one. |

Sessions last **30 days on the web and 90 days on mobile**, and each refresh
extends them. Replaying an old refresh token (more than 60 seconds after it
was replaced) ends the whole session, because it suggests the token was
stolen. Two refreshes with the same token within 60 seconds (two page loads
at once) both get the same answer.

## Clients

Registered in the `oauth_clients` table (seeded by migration `0002`).

| Client | Kind | Flow |
|---|---|---|
| `hasesa-web` | web, confidential | Browser redirect flow; redeeming a code needs `client_secret` (env `CLIENT_SECRETS`) |
| `hasesa-mobile` | native, public | Native Google Sign-In, then `POST /v1/auth/google/id-token` |

A new product gets its own row: an ID, its kind, its redirect URIs and its
session length.

## Web flow (server-side app)

1. Make a PKCE verifier (43–128 chars) and `state`. Keep both in a short-lived httpOnly cookie.
2. Redirect the browser to
   `GET /v1/auth/google/start?client_id=…&redirect_uri=…&state=…&code_challenge=BASE64URL(SHA256(verifier))&code_challenge_method=S256`.
   `redirect_uri` must be registered for the client.
3. The browser comes back to `redirect_uri?code=…&state=…`, or `?error=…&state=…`
   with `error` one of `cancelled`, `state`, `email`, `google`, `taken`.
4. Check `state`, then from your server:
   `POST /v1/auth/token` with
   `{"grant_type":"authorization_code","client_id","client_secret","code","redirect_uri","code_verifier"}`.
   The code is single-use and expires after 60 seconds.

## Mobile flow

1. Sign in with Google natively (Android/iOS client IDs must be listed in `GOOGLE_NATIVE_CLIENT_IDS`).
2. `POST /v1/auth/google/id-token` with `{"client_id":"hasesa-mobile","id_token":"<Google ID token>"}`.
3. Store the refresh token in the platform's secure storage (Keychain / Keystore).

## Token response

```json
{
  "access_token": "…", "token_type": "Bearer", "expires_in": 900,
  "refresh_token": "…", "session_expires_at": "2026-12-25T10:00:00Z",
  "user_id": "…", "session_id": "…", "is_new_user": true
}
```

Errors: `400`/`401` with `{"error": "...", "error_description": "..."}`.

## Other endpoints

- `POST /v1/auth/token` with `{"grant_type":"refresh_token","client_id","client_secret"?, "refresh_token"}`: refresh.
- `POST /v1/auth/logout` with `{"refresh_token"}`: end this session (always `204`).
- `POST /v1/auth/logout-all` (Bearer): end every session of the user.
- `GET /v1/me`, `PATCH /v1/me` (Bearer): the account; `PATCH` takes `language`, `region`, `school`, `extendedRetention`.

Signing out takes effect immediately: endpoints that need a signed-in user
check the session, not just the token.
