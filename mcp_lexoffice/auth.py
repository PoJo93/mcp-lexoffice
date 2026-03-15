"""Single-user OAuth provider for mcp-lexoffice.

Minimal OAuth 2.1 implementation for Claude.ai connector auth.
One user (configured via env), in-memory token storage.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from fastmcp.server.auth import AccessToken, OAuthProvider


TOKEN_TTL = 3600 * 24  # 24 hours
REFRESH_TTL = 3600 * 24 * 30  # 30 days
AUTH_CODE_TTL = 300  # 5 minutes


class SingleUserOAuthProvider(OAuthProvider):
    """OAuth provider for a single operator.

    Stores clients, tokens, and auth codes in memory.
    Authenticates the one configured user automatically.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(base_url=base_url)

        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}

    # ── Client management ────────────────────────────────────────────

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info

    # ── Authorization flow ───────────────────────────────────────────

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Issue an auth code immediately (single user, auto-approve)."""
        code = secrets.token_urlsafe(32)

        self._auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_TTL,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )

        query = urlencode({"code": code, **({"state": params.state} if params.state else {})})
        return f"{params.redirect_uri}?{query}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        auth_code = self._auth_codes.get(authorization_code)
        if auth_code is None:
            return None
        if auth_code.client_id != client.client_id:
            return None
        if time.time() > auth_code.expires_at:
            self._auth_codes.pop(authorization_code, None)
            return None
        return auth_code

    # ── Token exchange ───────────────────────────────────────────────

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        # Consume the auth code
        self._auth_codes.pop(authorization_code.code, None)

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        now = int(time.time())

        self._access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=now + TOKEN_TTL,
            resource=authorization_code.resource,
        )

        self._refresh_tokens[refresh_token] = RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=now + REFRESH_TTL,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=TOKEN_TTL,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Revoke old refresh token
        self._refresh_tokens.pop(refresh_token.token, None)

        access_tok = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        now = int(time.time())

        self._access_tokens[access_tok] = AccessToken(
            token=access_tok,
            client_id=client.client_id,
            scopes=scopes or refresh_token.scopes,
            expires_at=now + TOKEN_TTL,
        )

        self._refresh_tokens[new_refresh] = RefreshToken(
            token=new_refresh,
            client_id=client.client_id,
            scopes=scopes or refresh_token.scopes,
            expires_at=now + REFRESH_TTL,
        )

        return OAuthToken(
            access_token=access_tok,
            token_type="Bearer",
            expires_in=TOKEN_TTL,
            refresh_token=new_refresh,
            scope=" ".join(scopes) if scopes else None,
        )

    # ── Token lookup ─────────────────────────────────────────────────

    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = self._access_tokens.get(token)
        if access_token is None:
            return None
        if access_token.expires_at and time.time() > access_token.expires_at:
            self._access_tokens.pop(token, None)
            return None
        return access_token

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        rt = self._refresh_tokens.get(refresh_token)
        if rt is None:
            return None
        if rt.client_id != client.client_id:
            return None
        if rt.expires_at and time.time() > rt.expires_at:
            self._refresh_tokens.pop(refresh_token, None)
            return None
        return rt

    # ── Revocation ───────────────────────────────────────────────────

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self._access_tokens.pop(token.token, None)
        elif isinstance(token, RefreshToken):
            self._refresh_tokens.pop(token.token, None)
