"""Authentication for the MCP server.

Supports two authentication modes simultaneously via MultiAuth:

1. **Keycloak JWT** (for Claude.ai connectors and other OAuth clients):
   Tokens are issued by Keycloak and validated locally via JWKS.
   The server advertises Keycloak as its authorization server via
   RFC 9728 Protected Resource Metadata so MCP clients can discover
   the OAuth flow automatically.

2. **Bearer token** (for Claude Code, n8n, and other direct clients):
   Simple static API key validation via Authorization: Bearer <key>.

The API key is configured via the LEXOFFICE_MCP_API_KEY environment variable
or .env file. If not set, the server generates one on first startup and
saves it to .env automatically.
"""

import hmac
import logging
import secrets

from fastmcp.server.auth import (
    AccessToken,
    MultiAuth,
    RemoteAuthProvider,
    TokenVerifier,
)
from fastmcp.server.auth.providers.jwt import JWTVerifier

logger = logging.getLogger(__name__)


class BearerTokenVerifier(TokenVerifier):
    """Validates incoming requests against a static API key.

    Uses constant-time comparison to prevent timing attacks.
    """

    def __init__(self, api_key: str):
        super().__init__()
        self._api_key = api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self._api_key):
            logger.warning("Rejected request with invalid API key")
            return None

        return AccessToken(
            token=token,
            client_id="lexoffice-mcp-client",
            scopes=["all"],
        )


def create_auth(
    api_key: str | None,
    keycloak_issuer: str,
    keycloak_audience: str,
    base_url: str,
    **_kwargs,
) -> MultiAuth:
    """Create the authentication provider.

    Returns a MultiAuth that accepts both:
    - Keycloak JWT clients (Claude.ai) via OIDC / JWT validation
    - Bearer token clients (Claude Code, n8n) via static API key

    Args:
        api_key: Static API key for bearer token auth (None to skip).
        keycloak_issuer: Keycloak realm issuer URL
            (e.g. https://auth.cdit-works.de/realms/cdit-mcp).
        keycloak_audience: Expected JWT audience claim
            (e.g. mcp-lexoffice).
        base_url: Public URL of this server
            (e.g. https://mcp-lexoffice.cdit-dev.de).
    """
    jwks_uri = f"{keycloak_issuer}/protocol/openid-connect/certs"

    jwt_verifier = JWTVerifier(
        jwks_uri=jwks_uri,
        issuer=keycloak_issuer,
        audience=keycloak_audience,
    )

    jwt_auth = RemoteAuthProvider(
        token_verifier=jwt_verifier,
        authorization_servers=[keycloak_issuer],
        base_url=base_url,
        scopes_supported=["openid"],
        resource_name="Lexoffice MCP Server",
    )

    if api_key:
        bearer = BearerTokenVerifier(api_key)
        return MultiAuth(server=jwt_auth, verifiers=[bearer])

    return MultiAuth(server=jwt_auth)


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return f"lmcp_{secrets.token_urlsafe(32)}"
