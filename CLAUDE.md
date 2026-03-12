# mcp-lexoffice

MCP server for **Lexware Office** (formerly Lexoffice) — Python + FastMCP.

## Stack
- Python 3.11+, FastMCP, httpx
- Lexware Office REST API (`https://api.lexoffice.io/v1`)
- Auth: Bearer token via 1Password CLI (`op://` reference)

## Running
```bash
source .venv/bin/activate
LEXOFFICE_API_KEY='op://Private/ye2v5wotlaqtclt33nnbdeokde/API key' python -m mcp_lexoffice.server
```

## Account Details
- Company: Casey does IT (CDIT)
- Tax: Kleinunternehmerregelung (vatfree / small business exemption)
- Default payment terms: "Zahlbar sofort, rein netto"

## API Notes
- Rate limit: 2 requests/second (HTTP 429 on exceed)
- All mutations use optimistic locking via `version` field
- Invoice statuses: draft → open (finalized) → paidoff / voided
- Base URL migrating from lexoffice.io to lexware.io (both work currently)
