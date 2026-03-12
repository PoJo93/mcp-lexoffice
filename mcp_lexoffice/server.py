"""MCP server for Lexware Office (formerly Lexoffice)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.context import Context

from .client import LexofficeClient


@asynccontextmanager
async def lifespan(mcp: FastMCP):
    """Initialize the Lexoffice API client for the server's lifetime."""
    client = LexofficeClient()
    yield {"lexoffice": client}


mcp = FastMCP(
    "Lexware Office",
    instructions="MCP server for Lexware Office — invoices, contacts, quotations, and accounting",
    lifespan=lifespan,
)


def _fmt(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def _client(ctx: Context) -> LexofficeClient:
    return ctx.lifespan_context["lexoffice"]


# ── Profile ──────────────────────────────────────────────────────────


@mcp.tool
async def get_profile(ctx: Context) -> str:
    """Get the Lexware Office organization profile — company name, tax settings, currency."""
    result = await _client(ctx).get_profile()
    return _fmt(result)


# ── Contacts ─────────────────────────────────────────────────────────


@mcp.tool
async def search_contacts(
    ctx: Context,
    name: Annotated[str | None, "Filter by name (min 3 chars)"] = None,
    email: Annotated[str | None, "Filter by email (min 3 chars)"] = None,
    customer: Annotated[bool | None, "Only customers"] = None,
    vendor: Annotated[bool | None, "Only vendors"] = None,
    page: Annotated[int, "Page number (0-indexed)"] = 0,
) -> str:
    """Search and filter contacts in Lexware Office."""
    result = await _client(ctx).filter_contacts(
        name=name, email=email, customer=customer, vendor=vendor, page=page
    )
    return _fmt(result)


@mcp.tool
async def get_contact(
    ctx: Context,
    contact_id: Annotated[str, "UUID of the contact"],
) -> str:
    """Get full details for a specific contact."""
    result = await _client(ctx).get_contact(contact_id)
    return _fmt(result)


@mcp.tool
async def create_contact(
    ctx: Context,
    contact_json: Annotated[
        str,
        "JSON object for the contact. Must include 'version': 0, 'roles' (customer/vendor), "
        "and either 'company' or 'person'. See Lexware Office API docs for full schema.",
    ],
) -> str:
    """Create a new contact (person or company) in Lexware Office.

    Example company contact:
    {
      "version": 0,
      "roles": {"customer": {}},
      "company": {"name": "Acme GmbH"},
      "addresses": {"billing": [{"street": "Musterstr. 1", "zip": "10115", "city": "Berlin", "countryCode": "DE"}]}
    }
    """
    data = json.loads(contact_json)
    result = await _client(ctx).create_contact(data)
    return _fmt(result)


@mcp.tool
async def update_contact(
    ctx: Context,
    contact_id: Annotated[str, "UUID of the contact"],
    contact_json: Annotated[str, "Full updated contact JSON (must include current 'version')"],
) -> str:
    """Update an existing contact. Requires the current version number for optimistic locking."""
    data = json.loads(contact_json)
    result = await _client(ctx).update_contact(contact_id, data)
    return _fmt(result)


# ── Invoices ─────────────────────────────────────────────────────────


@mcp.tool
async def create_invoice(
    ctx: Context,
    invoice_json: Annotated[
        str,
        "JSON object for the invoice. Key fields: voucherDate, address, lineItems, "
        "totalPrice, taxConditions, paymentConditions. See Lexware Office API docs.",
    ],
    finalize: Annotated[
        bool, "If true, invoice is finalized (assigned a number, becomes non-editable)"
    ] = False,
) -> str:
    """Create a new invoice in Lexware Office.

    Example:
    {
      "voucherDate": "2026-03-12T00:00:00.000+01:00",
      "address": {"name": "Client GmbH", "street": "Str. 1", "zip": "10115", "city": "Berlin", "countryCode": "DE"},
      "lineItems": [
        {"type": "custom", "name": "IT Consulting", "quantity": 1, "unitName": "Stück",
         "unitPrice": {"currency": "EUR", "netAmount": 3000, "taxRatePercentage": 0}}
      ],
      "totalPrice": {"currency": "EUR"},
      "taxConditions": {"taxType": "vatfree"},
      "title": "Rechnung",
      "introduction": "Wir stellen Ihnen hiermit folgende Leistungen in Rechnung:",
      "remark": "Zahlbar innerhalb von 14 Tagen.",
      "paymentConditions": {"paymentTermLabel": "14 Tage", "paymentTermDuration": 14}
    }
    """
    data = json.loads(invoice_json)
    result = await _client(ctx).create_invoice(data, finalize=finalize)
    return _fmt(result)


@mcp.tool
async def get_invoice(
    ctx: Context,
    invoice_id: Annotated[str, "UUID of the invoice"],
) -> str:
    """Get full details for a specific invoice."""
    result = await _client(ctx).get_invoice(invoice_id)
    return _fmt(result)


@mcp.tool
async def list_invoices(
    ctx: Context,
    status: Annotated[
        str | None,
        "Filter by status: draft, open, paidoff, voided (comma-separated for multiple)",
    ] = None,
    page: Annotated[int, "Page number (0-indexed)"] = 0,
) -> str:
    """List invoices, optionally filtered by status."""
    result = await _client(ctx).filter_vouchers(
        "invoice", voucher_status=status, page=page
    )
    return _fmt(result)


@mcp.tool
async def get_invoice_pdf_link(
    ctx: Context,
    invoice_id: Annotated[str, "UUID of the invoice"],
) -> str:
    """Render and get the document file ID for an invoice PDF.

    Returns a documentFileId that can be used to download the PDF.
    The invoice must be finalized (status: open) to render a PDF.
    """
    result = await _client(ctx).render_invoice_document(invoice_id)
    return _fmt(result)


# ── Quotations ───────────────────────────────────────────────────────


@mcp.tool
async def create_quotation(
    ctx: Context,
    quotation_json: Annotated[str, "JSON object for the quotation"],
    finalize: Annotated[bool, "Finalize the quotation on creation"] = False,
) -> str:
    """Create a new quotation (Angebot) in Lexware Office."""
    data = json.loads(quotation_json)
    result = await _client(ctx).create_quotation(data, finalize=finalize)
    return _fmt(result)


@mcp.tool
async def get_quotation(
    ctx: Context,
    quotation_id: Annotated[str, "UUID of the quotation"],
) -> str:
    """Get full details for a specific quotation."""
    result = await _client(ctx).get_quotation(quotation_id)
    return _fmt(result)


# ── Credit Notes ─────────────────────────────────────────────────────


@mcp.tool
async def create_credit_note(
    ctx: Context,
    credit_note_json: Annotated[str, "JSON object for the credit note"],
    finalize: Annotated[bool, "Finalize on creation"] = False,
    preceding_invoice_id: Annotated[
        str | None, "UUID of the preceding invoice to link this credit note to"
    ] = None,
) -> str:
    """Create a credit note (Gutschrift), optionally linked to a preceding invoice."""
    data = json.loads(credit_note_json)
    result = await _client(ctx).create_credit_note(
        data, finalize=finalize, preceding_id=preceding_invoice_id
    )
    return _fmt(result)


# ── Voucher List ─────────────────────────────────────────────────────


@mcp.tool
async def list_vouchers(
    ctx: Context,
    voucher_type: Annotated[
        str,
        "Type: invoice, creditnote, orderconfirmation, quotation, deliverynote, "
        "downpaymentinvoice, purchaseinvoice, purchasecreditnote",
    ],
    status: Annotated[str | None, "Filter by status (comma-separated)"] = None,
    page: Annotated[int, "Page number (0-indexed)"] = 0,
) -> str:
    """List vouchers of a given type with optional status filter."""
    result = await _client(ctx).filter_vouchers(
        voucher_type, voucher_status=status, page=page
    )
    return _fmt(result)


# ── Payment Conditions ───────────────────────────────────────────────


@mcp.tool
async def list_payment_conditions(ctx: Context) -> str:
    """List all configured payment conditions (Zahlungsbedingungen)."""
    result = await _client(ctx).list_payment_conditions()
    return _fmt(result)


# ── Utilities ────────────────────────────────────────────────────────


@mcp.tool
async def list_countries(ctx: Context) -> str:
    """List all countries with their tax classification (DE, intraCommunity, thirdPartyCountry)."""
    result = await _client(ctx).list_countries()
    return _fmt(result)


def main():
    import os

    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8000"))

    if transport in ("streamable-http", "sse"):
        mcp.run(transport=transport, host=host, port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
