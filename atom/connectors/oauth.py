"""OAuth 2.0 authorization-code flow with PKCE for desktop use: sign in in the browser, loopback redirect to this server.

The refresh token goes to the system keychain; access tokens are short-lived and only kept in memory.
"""
from __future__ import annotations

import base64
import hashlib
import secrets as pysecrets
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx

STATE_TTL = 600
REFRESH_KEY = "oauth_refresh_token"


class AuthRequired(ValueError):
    """The connector is configured for OAuth but nobody has signed in yet."""


class AuthError(RuntimeError):
    """Sign-in expired or was revoked."""


class TokenSource:
    """Callable returning a fresh access token (thread-safe; refreshes shortly before expiry)."""

    def __init__(self, spec: dict[str, Any], client_id: str, client_secret: str, refresh_token: str):
        self.spec, self.client_id, self.client_secret, self.refresh_token = spec, client_id, client_secret, refresh_token
        self._tok: str | None = None
        self._exp = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            if self._tok and time.time() < self._exp - 60:
                return self._tok
            r = httpx.post(self.spec["token_url"], timeout=20, data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "refresh_token": self.refresh_token, "grant_type": "refresh_token"})
            if r.status_code != 200:
                err = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("error", "")
                if err == "invalid_grant":
                    raise AuthError("Google sign-in expired or was revoked; sign in again from Settings.")
                raise AuthError(f"Could not refresh the Google access token (HTTP {r.status_code} {err}).")
            body = r.json()
            self._tok, self._exp = body["access_token"], time.time() + int(body.get("expires_in", 3600))
            return self._tok


class PendingAuth:
    def __init__(self, name: str, verifier: str, redirect_uri: str, spec: dict, client_id: str, client_secret: str):
        self.name, self.verifier, self.redirect_uri = name, verifier, redirect_uri
        self.spec, self.client_id, self.client_secret = spec, client_id, client_secret
        self.expires = time.time() + STATE_TTL


class OAuthFlows:
    def __init__(self) -> None:
        self.pending: dict[str, PendingAuth] = {}

    def begin(self, name: str, spec: dict, client_id: str, client_secret: str, redirect_uri: str,
              login_hint: str | None) -> str:
        now = time.time()
        self.pending = {k: v for k, v in self.pending.items() if v.expires > now}
        state = pysecrets.token_urlsafe(24)
        verifier = pysecrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.pending[state] = PendingAuth(name, verifier, redirect_uri, spec, client_id, client_secret)
        q = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
             "scope": " ".join(spec["scopes"]), "state": state, "code_challenge": challenge,
             "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"}
        if login_hint:
            q["login_hint"] = login_hint
        return f"{spec['auth_url']}?{urlencode(q)}"

    async def finish(self, state: str, code: str) -> tuple[str, str]:
        """Exchange the code; returns (connector name, refresh token)."""
        p = self.pending.pop(state, None)
        if p is None or p.expires < time.time():
            raise AuthError("This sign-in link expired or was already used. Start again from Settings.")
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(p.spec["token_url"], data={
                "code": code, "client_id": p.client_id, "client_secret": p.client_secret, "redirect_uri": p.redirect_uri,
                "grant_type": "authorization_code", "code_verifier": p.verifier})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200:
            raise AuthError(f"Google rejected the sign-in: {body.get('error_description') or body.get('error') or r.status_code}")
        if not body.get("refresh_token"):
            raise AuthError("Google returned no refresh token. Remove this app at myaccount.google.com/permissions and sign in again.")
        return p.name, body["refresh_token"]
