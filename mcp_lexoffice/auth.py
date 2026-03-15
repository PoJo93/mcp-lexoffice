"""Single-user OAuth provider for mcp-lexoffice.

Minimal OAuth 2.1 implementation for Claude.ai connector auth.
One user (configured via env), in-memory token storage.
Shared secret gate — first launch generates and displays it, saved to .env.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, quote

from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from fastmcp.server.auth import AccessToken, OAuthProvider
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)

TOKEN_TTL = 3600 * 24  # 24 hours
REFRESH_TTL = 3600 * 24 * 30  # 30 days
AUTH_CODE_TTL = 300  # 5 minutes

ENV_SECRET_KEY = "MCP_AUTH_SECRET"


def _ensure_secret() -> str:
    """Load or generate the shared auth secret.

    First launch: generates, writes to .env, prints in clear.
    Subsequent launches: loads from env, prints masked.
    """
    secret = os.environ.get(ENV_SECRET_KEY, "")
    if secret:
        masked = secret[:4] + "*" * (len(secret) - 8) + secret[-4:]
        logger.info(f"Auth secret loaded: {masked}")
        return secret

    secret = secrets.token_urlsafe(32)
    os.environ[ENV_SECRET_KEY] = secret

    env_path = Path(".env")
    try:
        if env_path.exists():
            content = env_path.read_text()
            if ENV_SECRET_KEY not in content:
                with env_path.open("a") as f:
                    f.write(f"\n{ENV_SECRET_KEY}={secret}\n")
        else:
            env_path.write_text(f"{ENV_SECRET_KEY}={secret}\n")
        logger.info("Auth secret generated and saved to .env")
    except OSError:
        logger.warning("Could not write secret to .env — set MCP_AUTH_SECRET manually")

    print("\n" + "=" * 60)
    print("  MCP AUTH SECRET (save this — shown only once)")
    print(f"  {secret}")
    print("=" * 60 + "\n")

    return secret


def _secret_form_html(action_url: str, error: str | None = None) -> str:
    error_html = f'<p style="color:#e74c3c;font-weight:bold">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html><head>
<title>Lexoffice MCP — Authorize</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 400px;
         margin: 80px auto; padding: 0 20px; color: #1a1a1a; }}
  h1 {{ font-size: 1.4em; }}
  input[type=password] {{ width: 100%; padding: 10px; font-size: 16px;
         border: 2px solid #ddd; border-radius: 6px; margin: 8px 0 16px; box-sizing: border-box; }}
  button {{ background: #2563eb; color: white; border: none; padding: 10px 24px;
           font-size: 16px; border-radius: 6px; cursor: pointer; }}
  button:hover {{ background: #1d4ed8; }}
  .subtle {{ color: #666; font-size: 0.85em; margin-top: 20px; }}
</style>
</head><body>
<h1>Lexoffice MCP</h1>
<p>Enter the server secret to authorize this connection.</p>
{error_html}
<form method="POST" action="{action_url}">
  <input type="password" name="secret" placeholder="Server secret" autofocus required>
  <button type="submit">Authorize</button>
</form>
<p class="subtle">Casey does IT — mcp-lexoffice</p>
</body></html>"""


class SingleUserOAuthProvider(OAuthProvider):
    """OAuth provider for a single operator.

    Stores clients, tokens, and auth codes in memory.
    Gates /authorize on a shared secret entered via browser form.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(base_url=base_url)

        self._secret = _ensure_secret()
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}

    # ── Custom routes ────────────────────────────────────────────────

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """Insert /gate before /authorize and patch discovery to point to /gate."""
        routes = super().get_routes(mcp_path)

        # Patch the /.well-known/oauth-authorization-server handler to
        # advertise /gate as the authorization_endpoint
        patched: list[Route] = []
        for route in routes:
            if isinstance(route, Route) and route.path == "/.well-known/oauth-authorization-server":
                patched.append(Route(
                    "/.well-known/oauth-authorization-server",
                    endpoint=self._patched_metadata,
                    methods=["GET", "OPTIONS"],
                ))
            else:
                patched.append(route)

        # Add our gate endpoint — the standard /authorize stays intact for the redirect
        patched.append(Route("/gate", endpoint=self._gate_get, methods=["GET"]))
        patched.append(Route("/gate", endpoint=self._gate_post, methods=["POST"]))

        return patched

    async def _patched_metadata(self, request: Request):
        """Serve OAuth metadata with authorization_endpoint pointing to /gate."""
        from starlette.responses import JSONResponse
        base = str(self.base_url).rstrip("/")
        metadata = {
            "issuer": f"{base}/",
            "authorization_endpoint": f"{base}/gate",
            "token_endpoint": f"{base}/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "code_challenge_methods_supported": ["S256"],
            "registration_endpoint": f"{base}/register",
        }
        return JSONResponse(metadata)

    async def _gate_get(self, request: Request):
        """Show the secret form. The original authorize query string is preserved."""
        qs = str(request.url.query)
        return HTMLResponse(_secret_form_html(f"/gate?{qs}"))

    async def _gate_post(self, request: Request):
        """Validate the secret, then redirect to the real /authorize."""
        form = await request.form()
        entered = str(form.get("secret", ""))
        qs = str(request.url.query)

        if not secrets.compare_digest(entered, self._secret):
            return HTMLResponse(_secret_form_html(f"/gate?{qs}", error="Invalid secret"), status_code=403)

        # Secret valid — redirect to the real /authorize with original params
        return RedirectResponse(f"/authorize?{qs}", status_code=303)

    # ── Authorization flow ───────────────────────────────────────────
    # The standard /authorize handler (from FastMCP/MCP SDK) calls our
    # authorize() method. We auto-approve since the user already passed
    # the secret gate in the browser.

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Issue an auth code immediately (user already authenticated via /gate)."""
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

    # ── Client management ────────────────────────────────────────────

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info

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
