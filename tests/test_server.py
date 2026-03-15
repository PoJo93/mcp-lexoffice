"""Unit tests for the MCP server tools."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from mcp_lexoffice.server import _fmt, mcp


# ── Helper: build a fake Context ─────────────────────────────────────


class FakeContext:
    """Minimal stand-in for fastmcp Context with lifespan_context."""

    def __init__(self, lexoffice_client):
        self.lifespan_context = {"lexoffice": lexoffice_client}


def make_ctx(method_responses: dict[str, object]) -> FakeContext:
    """Create a FakeContext with a mock LexofficeClient."""
    client = AsyncMock()
    for method, response in method_responses.items():
        getattr(client, method).return_value = response
    return FakeContext(client)


# ── _fmt ─────────────────────────────────────────────────────────────


def test_fmt_pretty_json():
    result = _fmt({"key": "wert", "nested": [1, 2]})
    parsed = json.loads(result)
    assert parsed["key"] == "wert"
    assert "\n" in result


def test_fmt_unicode():
    result = _fmt({"name": "Müller & Söhne"})
    assert "Müller" in result


# ── Tool registration ────────────────────────────────────────────────


async def test_all_tools_registered():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "get_profile",
        "search_contacts", "get_contact", "create_contact", "update_contact",
        "create_draft_invoice", "finalize_invoice", "send_invoice",
        "get_invoice", "get_invoice_pdf", "list_invoices",
        "upload_voucher",
        "list_expenses", "get_financial_overview", "get_payment_status",
        "create_draft_quotation", "finalize_quotation", "pursue_quotation_to_invoice",
        "create_dunning", "render_dunning_pdf",
        "list_articles", "create_article", "get_article", "update_article",
        "list_vouchers", "list_payment_conditions", "list_countries",
    }
    assert expected == names


# ── Profile tool ─────────────────────────────────────────────────────


async def test_get_profile_tool():
    from mcp_lexoffice.server import get_profile

    ctx = make_ctx({"get_profile": {"companyName": "CDIT", "taxType": "vatfree"}})
    result = await get_profile(ctx)
    parsed = json.loads(result)
    assert parsed["companyName"] == "CDIT"


# ── Invoice tools ────────────────────────────────────────────────────


async def test_create_draft_invoice_tool():
    from mcp_lexoffice.server import create_draft_invoice

    ctx = make_ctx({"create_invoice": {"id": "inv-1", "version": 0}})
    result = await create_draft_invoice(
        ctx,
        recipient_name="Acme GmbH",
        line_items='[{"name": "Consulting", "unit_price": 3000, "quantity": 1}]',
    )
    parsed = json.loads(result)
    assert parsed["id"] == "inv-1"
    assert "deepLink" in parsed
    call_args = ctx.lifespan_context["lexoffice"].create_invoice.call_args
    invoice_data = call_args[0][0]
    assert invoice_data["taxConditions"]["taxType"] == "vatfree"
    assert invoice_data["address"]["name"] == "Acme GmbH"
    assert invoice_data["lineItems"][0]["unitPrice"]["taxRatePercentage"] == 0


async def test_finalize_invoice_tool():
    from mcp_lexoffice.server import finalize_invoice

    ctx = make_ctx({"finalize_invoice": {"id": "inv-1", "voucherNumber": "RE-2026-001"}})
    result = await finalize_invoice(ctx, invoice_id="inv-1")
    parsed = json.loads(result)
    assert parsed["voucherNumber"] == "RE-2026-001"
    assert "deepLink" in parsed


async def test_send_invoice_blocks_draft():
    from mcp_lexoffice.server import send_invoice

    ctx = make_ctx({"get_invoice": {"id": "inv-1", "voucherStatus": "draft"}})
    result = await send_invoice(ctx, invoice_id="inv-1", recipient_email="test@test.de")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "draft" in parsed["error"].lower()


async def test_send_invoice_finalized():
    from mcp_lexoffice.server import send_invoice

    ctx = make_ctx({
        "get_invoice": {"id": "inv-1", "voucherStatus": "open"},
        "send_invoice": None,
    })
    result = await send_invoice(ctx, invoice_id="inv-1", recipient_email="test@test.de")
    parsed = json.loads(result)
    assert parsed["status"] == "sent"


async def test_get_invoice_tool_deep_link():
    from mcp_lexoffice.server import get_invoice

    ctx = make_ctx({"get_invoice": {"id": "inv-1", "voucherStatus": "draft"}})
    result = await get_invoice(ctx, invoice_id="inv-1")
    parsed = json.loads(result)
    assert "edit" in parsed["deepLink"]

    ctx2 = make_ctx({"get_invoice": {"id": "inv-2", "voucherStatus": "open"}})
    result2 = await get_invoice(ctx2, invoice_id="inv-2")
    parsed2 = json.loads(result2)
    assert "view" in parsed2["deepLink"]


async def test_list_invoices_with_overdue():
    from mcp_lexoffice.server import list_invoices

    ctx = make_ctx({
        "filter_vouchers": {
            "content": [
                {"voucherId": "v1", "voucherStatus": "open", "dueDate": "2020-01-01"},
            ]
        }
    })
    result = await list_invoices(ctx, status="open")
    parsed = json.loads(result)
    assert parsed["content"][0]["daysOverdue"] > 0
    assert "deepLink" in parsed["content"][0]


# ── Voucher upload ───────────────────────────────────────────────────


async def test_upload_voucher_valid():
    import base64
    from mcp_lexoffice.server import upload_voucher

    ctx = make_ctx({"upload_file": {"id": "file-1"}})
    content = base64.b64encode(b"fake-pdf-content").decode()
    result = await upload_voucher(ctx, file_content=content, file_name="bill.pdf")
    parsed = json.loads(result)
    assert parsed["id"] == "file-1"


async def test_upload_voucher_bad_type():
    from mcp_lexoffice.server import upload_voucher

    ctx = make_ctx({})
    result = await upload_voucher(ctx, file_content="abc", file_name="file.docx")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Unsupported" in parsed["error"]


async def test_upload_voucher_too_large():
    import base64
    from mcp_lexoffice.server import upload_voucher

    ctx = make_ctx({})
    big = base64.b64encode(b"x" * (6 * 1024 * 1024)).decode()
    result = await upload_voucher(ctx, file_content=big, file_name="huge.pdf")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "5MB" in parsed["error"]


# ── Contact tools ────────────────────────────────────────────────────


async def test_create_contact_company():
    from mcp_lexoffice.server import create_contact

    ctx = make_ctx({"create_contact": {"id": "c-1"}})
    result = await create_contact(ctx, company_name="Acme GmbH", role="customer")
    parsed = json.loads(result)
    assert parsed["id"] == "c-1"
    assert "deepLink" in parsed
    call_data = ctx.lifespan_context["lexoffice"].create_contact.call_args[0][0]
    assert call_data["company"]["name"] == "Acme GmbH"
    assert "customer" in call_data["roles"]


async def test_create_contact_person():
    from mcp_lexoffice.server import create_contact

    ctx = make_ctx({"create_contact": {"id": "c-2"}})
    result = await create_contact(ctx, first_name="Max", last_name="Müller")
    parsed = json.loads(result)
    assert parsed["id"] == "c-2"


async def test_create_contact_no_name():
    from mcp_lexoffice.server import create_contact

    ctx = make_ctx({})
    result = await create_contact(ctx)
    parsed = json.loads(result)
    assert "error" in parsed


async def test_search_contacts_role_filter():
    from mcp_lexoffice.server import search_contacts

    ctx = make_ctx({"filter_contacts": {"content": [], "totalElements": 0}})
    await search_contacts(ctx, role="vendor")
    call_kwargs = ctx.lifespan_context["lexoffice"].filter_contacts.call_args[1]
    assert call_kwargs["customer"] is None
    assert call_kwargs["vendor"] is True


# ── Quotation tools ──────────────────────────────────────────────────


async def test_create_draft_quotation_tool():
    from mcp_lexoffice.server import create_draft_quotation

    ctx = make_ctx({"create_quotation": {"id": "q-1"}})
    result = await create_draft_quotation(
        ctx,
        recipient_name="Test Client",
        line_items='[{"name": "Service", "unit_price": 500}]',
    )
    parsed = json.loads(result)
    assert parsed["id"] == "q-1"
    assert "deepLink" in parsed


async def test_pursue_quotation_blocks_draft():
    from mcp_lexoffice.server import pursue_quotation_to_invoice

    ctx = make_ctx({"get_quotation": {"id": "q-1", "voucherStatus": "draft"}})
    result = await pursue_quotation_to_invoice(ctx, quotation_id="q-1")
    parsed = json.loads(result)
    assert "error" in parsed


# ── Dunning tools ────────────────────────────────────────────────────


async def test_create_dunning_tool():
    from mcp_lexoffice.server import create_dunning

    ctx = make_ctx({"create_dunning": {"id": "d-1"}})
    result = await create_dunning(ctx, invoice_id="inv-1", note="Bitte zahlen")
    parsed = json.loads(result)
    assert parsed["id"] == "d-1"


# ── Article tools ────────────────────────────────────────────────────


async def test_create_article_tool():
    from mcp_lexoffice.server import create_article

    ctx = make_ctx({"create_article": {"id": "a-1"}})
    result = await create_article(ctx, name="Sprechstunde", net_price=995.0, unit_name="Pauschal")
    parsed = json.loads(result)
    assert parsed["id"] == "a-1"
    call_data = ctx.lifespan_context["lexoffice"].create_article.call_args[0][0]
    assert call_data["price"]["taxRatePercentage"] == 0


# ── Payment status ───────────────────────────────────────────────────


async def test_get_payment_status_by_id():
    from mcp_lexoffice.server import get_payment_status

    ctx = make_ctx({"get_payments": {"openAmount": 500}})
    result = await get_payment_status(ctx, invoice_id="inv-1")
    parsed = json.loads(result)
    assert parsed["openAmount"] == 500


async def test_get_payment_status_no_params():
    from mcp_lexoffice.server import get_payment_status

    ctx = make_ctx({})
    result = await get_payment_status(ctx)
    parsed = json.loads(result)
    assert "error" in parsed


# ── main() transport ─────────────────────────────────────────────────


def test_main_defaults_to_streamable_http():
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("mcp_lexoffice.server.mcp") as mock_mcp,
    ):
        os.environ.pop("MCP_TRANSPORT", None)
        from mcp_lexoffice.server import main

        main()
        mock_mcp.run.assert_called_once_with(
            transport="streamable-http", host="0.0.0.0", port=8000, json_response=True
        )
