# mcp-lexoffice

MCP server for **Lexware Office** (formerly Lexoffice) — Python + FastMCP 3.

## Stack
- Python 3.11+, FastMCP 3.x, httpx, python-dotenv
- Lexware Office REST API (`https://api.lexoffice.io/v1`)
- Transport: streamable-http with `json_response=True` (port 8000)
- Auth: Bearer token from env/.env (with `op://` 1Password fallback)

## Running
```bash
source .venv/bin/activate
python -m mcp_lexoffice.server
# or with 1Password:
LEXOFFICE_API_KEY='op://Private/ye2v5wotlaqtclt33nnbdeokde/API key' python -m mcp_lexoffice.server
```

## Deployment
- **Server**: ubuntu-smurf (Komodo git-deploy stack `git-mcp-lexoffice`)
- **Proxy**: Caddy on nebula-1 → `mcp-lexoffice-tmp.cdit-dev.de` → ubuntu-smurf:8001
- **Docker**: `HOST_PORT=8001` (epaper-backend uses 8000 on ubuntu-smurf)

## Account Details
- Company: Casey does IT (CDIT)
- Tax: Kleinunternehmerregelung (vatfree / small business exemption)
- Default payment terms: "Zahlbar sofort, rein netto"
- Service catalog: Sprechstunde (€995), Consulting (€150/h), Platform Dev (€1200/d)

## Tools (27 total)
- **Invoices**: create_draft_invoice, finalize_invoice, send_invoice, get_invoice, get_invoice_pdf, list_invoices
- **Financial**: list_expenses, get_financial_overview, get_payment_status
- **Contacts**: search_contacts, get_contact, create_contact, update_contact
- **Quotations**: create_draft_quotation, finalize_quotation, pursue_quotation_to_invoice
- **Dunnings**: create_dunning, render_dunning_pdf
- **Articles**: list_articles, create_article, get_article, update_article
- **Other**: upload_voucher, get_profile, list_vouchers, list_payment_conditions, list_countries

## API Notes
- Rate limit: 2 requests/second (HTTP 429 on exceed, auto-retry with Retry-After)
- All mutations use optimistic locking via `version` field
- Invoice statuses: draft → open (finalized) → paidoff / voided
- All tools return deep links to Lexoffice UI
- Base URL migrating from lexoffice.io to lexware.io (both work currently)

## Testing
```bash
source .venv/bin/activate
pip install -e ".[test]"
python -m pytest tests/ -v  # 204 tests
```
