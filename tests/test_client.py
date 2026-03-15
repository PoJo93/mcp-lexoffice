"""Unit tests for the Lexoffice API client."""

from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest
import respx

from mcp_lexoffice.client import LexofficeClient, _resolve_api_key


# ── API key resolution ───────────────────────────────────────────────


class TestResolveApiKey:
    def test_raw_key(self):
        with patch.dict(os.environ, {"LEXOFFICE_API_KEY": "raw-key-123"}):
            assert _resolve_api_key() == "raw-key-123"

    def test_empty_key(self):
        with patch.dict(os.environ, {"LEXOFFICE_API_KEY": ""}):
            assert _resolve_api_key() == ""

    def test_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _resolve_api_key() == ""

    def test_op_reference_success(self):
        with (
            patch.dict(os.environ, {"LEXOFFICE_API_KEY": "op://vault/item/field"}),
            patch("mcp_lexoffice.client.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "  resolved-key  \n"
            assert _resolve_api_key() == "resolved-key"
            mock_run.assert_called_once_with(
                ["op", "read", "op://vault/item/field"],
                capture_output=True,
                text=True,
                timeout=10,
            )

    def test_op_reference_failure(self):
        with (
            patch.dict(os.environ, {"LEXOFFICE_API_KEY": "op://vault/item/field"}),
            patch("mcp_lexoffice.client.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "not signed in"
            with pytest.raises(RuntimeError, match="1Password CLI failed"):
                _resolve_api_key()


class TestClientInit:
    def test_missing_key_raises(self):
        with patch.dict(os.environ, {"LEXOFFICE_API_KEY": ""}):
            with pytest.raises(RuntimeError, match="LEXOFFICE_API_KEY must be set"):
                LexofficeClient()

    def test_auth_header_set(self):
        with patch.dict(os.environ, {"LEXOFFICE_API_KEY": "my-key"}):
            c = LexofficeClient()
            assert c._client.headers["Authorization"] == "Bearer my-key"


# ── Profile ──────────────────────────────────────────────────────────


async def test_get_profile(client, mock_api):
    mock_api.get("/profile").respond(
        200, json={"companyName": "Test GmbH", "taxType": "vatfree"}
    )
    result = await client.get_profile()
    assert result["companyName"] == "Test GmbH"
    assert result["taxType"] == "vatfree"


# ── Contacts ─────────────────────────────────────────────────────────


async def test_create_contact(client, mock_api):
    mock_api.post("/contacts").respond(
        200, json={"id": "abc-123", "resourceUri": "https://api.lexoffice.io/v1/contacts/abc-123"}
    )
    result = await client.create_contact({"version": 0, "roles": {"customer": {}}})
    assert result["id"] == "abc-123"


async def test_get_contact(client, mock_api):
    mock_api.get("/contacts/abc-123").respond(
        200, json={"id": "abc-123", "company": {"name": "Acme"}}
    )
    result = await client.get_contact("abc-123")
    assert result["company"]["name"] == "Acme"


async def test_update_contact(client, mock_api):
    mock_api.put("/contacts/abc-123").respond(
        200, json={"id": "abc-123", "version": 2}
    )
    result = await client.update_contact("abc-123", {"version": 1, "company": {"name": "Acme v2"}})
    assert result["version"] == 2


async def test_filter_contacts_all_params(client, mock_api):
    route = mock_api.get("/contacts").respond(
        200, json={"content": [], "totalElements": 0}
    )
    result = await client.filter_contacts(
        name="Test", email="test@example.com", number=10001, customer=True, vendor=False, page=2, size=10
    )
    assert result["totalElements"] == 0
    request = route.calls[0].request
    assert "name=Test" in str(request.url)
    assert "email=test" in str(request.url)
    assert "customer=true" in str(request.url).lower()
    assert "page=2" in str(request.url)


async def test_filter_contacts_minimal(client, mock_api):
    route = mock_api.get("/contacts").respond(
        200, json={"content": [{"id": "x"}], "totalElements": 1}
    )
    result = await client.filter_contacts()
    assert len(result["content"]) == 1
    request = route.calls[0].request
    assert "page=0" in str(request.url)
    assert "size=25" in str(request.url)


# ── Invoices ─────────────────────────────────────────────────────────


async def test_create_invoice_draft(client, mock_api):
    mock_api.post("/invoices").respond(
        200, json={"id": "inv-001", "version": 0}
    )
    result = await client.create_invoice({"lineItems": []})
    assert result["id"] == "inv-001"


async def test_create_invoice_finalized(client, mock_api):
    route = mock_api.post("/invoices").respond(
        200, json={"id": "inv-002", "version": 1}
    )
    result = await client.create_invoice({"lineItems": []}, finalize=True)
    assert result["id"] == "inv-002"
    request = route.calls[0].request
    assert "finalize=true" in str(request.url)


async def test_get_invoice(client, mock_api):
    mock_api.get("/invoices/inv-001").respond(
        200, json={"id": "inv-001", "voucherStatus": "draft"}
    )
    result = await client.get_invoice("inv-001")
    assert result["voucherStatus"] == "draft"


async def test_render_invoice_document(client, mock_api):
    mock_api.get("/invoices/inv-001/document").respond(
        200, json={"documentFileId": "file-999"}
    )
    result = await client.render_invoice_document("inv-001")
    assert result["documentFileId"] == "file-999"


async def test_download_invoice_pdf(client, mock_api):
    mock_api.get("/invoices/inv-001/file").respond(200, content=b"%PDF-1.4 fake")
    result = await client.download_invoice_pdf("inv-001")
    assert result.startswith(b"%PDF")


# ── Quotations ───────────────────────────────────────────────────────


async def test_create_quotation(client, mock_api):
    route = mock_api.post("/quotations").respond(200, json={"id": "q-001"})
    result = await client.create_quotation({"lineItems": []}, finalize=True)
    assert result["id"] == "q-001"
    assert "finalize=true" in str(route.calls[0].request.url)


async def test_get_quotation(client, mock_api):
    mock_api.get("/quotations/q-001").respond(200, json={"id": "q-001"})
    result = await client.get_quotation("q-001")
    assert result["id"] == "q-001"


# ── Credit Notes ─────────────────────────────────────────────────────


async def test_create_credit_note_standalone(client, mock_api):
    mock_api.post("/credit-notes").respond(200, json={"id": "cn-001"})
    result = await client.create_credit_note({"lineItems": []})
    assert result["id"] == "cn-001"


async def test_create_credit_note_linked(client, mock_api):
    route = mock_api.post("/credit-notes").respond(200, json={"id": "cn-002"})
    result = await client.create_credit_note(
        {"lineItems": []}, finalize=True, preceding_id="inv-001"
    )
    assert result["id"] == "cn-002"
    url = str(route.calls[0].request.url)
    assert "precedingSalesVoucherId=inv-001" in url
    assert "finalize=true" in url


# ── Vouchers ─────────────────────────────────────────────────────────


async def test_filter_vouchers(client, mock_api):
    route = mock_api.get("/voucherlist").respond(
        200, json={"content": [], "totalElements": 0}
    )
    result = await client.filter_vouchers("invoice", voucher_status="open", page=1, size=10)
    assert result["totalElements"] == 0
    url = str(route.calls[0].request.url)
    assert "voucherType=invoice" in url
    assert "voucherStatus=open" in url


async def test_filter_vouchers_default_status(client, mock_api):
    route = mock_api.get("/voucherlist").respond(
        200, json={"content": [], "totalElements": 0}
    )
    await client.filter_vouchers("invoice")
    url = str(route.calls[0].request.url)
    assert "voucherStatus=any" in url


# ── Files ────────────────────────────────────────────────────────────


async def test_download_file(client, mock_api):
    mock_api.get("/files/file-999").respond(200, content=b"binary-data")
    result = await client.download_file("file-999")
    assert result == b"binary-data"


# ── Payment Conditions ───────────────────────────────────────────────


async def test_list_payment_conditions(client, mock_api):
    mock_api.get("/payment-conditions").respond(
        200, json=[{"id": "pc-1", "paymentTermDuration": 14}]
    )
    result = await client.list_payment_conditions()
    assert len(result) == 1
    assert result[0]["paymentTermDuration"] == 14


# ── Countries ────────────────────────────────────────────────────────


async def test_list_countries(client, mock_api):
    mock_api.get("/countries").respond(
        200, json=[{"countryCode": "DE", "taxClassification": "de"}]
    )
    result = await client.list_countries()
    assert result[0]["countryCode"] == "DE"


# ── Event Subscriptions ──────────────────────────────────────────────


async def test_create_event_subscription(client, mock_api):
    mock_api.post("/event-subscriptions").respond(200, json={"id": "es-001"})
    result = await client.create_event_subscription({"eventType": "invoice.created"})
    assert result["id"] == "es-001"


async def test_list_event_subscriptions(client, mock_api):
    mock_api.get("/event-subscriptions").respond(200, json=[{"id": "es-001"}])
    result = await client.list_event_subscriptions()
    assert len(result) == 1


async def test_delete_event_subscription(client, mock_api):
    mock_api.delete("/event-subscriptions/es-001").respond(204)
    await client.delete_event_subscription("es-001")


# ── Invoice lifecycle (new) ──────────────────────────────────────────


async def test_finalize_invoice(client, mock_api):
    mock_api.get("/invoices/inv-001").respond(
        200, json={"id": "inv-001", "version": 2}
    )
    mock_api.post("/invoices/inv-001/finalize").respond(
        200, json={"id": "inv-001", "voucherNumber": "RE-001"}
    )
    result = await client.finalize_invoice("inv-001")
    assert result["voucherNumber"] == "RE-001"


async def test_send_invoice(client, mock_api):
    mock_api.post("/invoices/inv-001/send").respond(204)
    await client.send_invoice("inv-001", "test@test.de")


# ── Quotation lifecycle (new) ───────────────────────────────────────


async def test_finalize_quotation(client, mock_api):
    mock_api.get("/quotations/q-001").respond(200, json={"id": "q-001", "version": 1})
    mock_api.post("/quotations/q-001/finalize").respond(
        200, json={"id": "q-001", "voucherNumber": "AG-001"}
    )
    result = await client.finalize_quotation("q-001")
    assert result["voucherNumber"] == "AG-001"


async def test_pursue_quotation(client, mock_api):
    mock_api.post("/quotations/q-001/pursue").respond(200, json={"id": "inv-new"})
    result = await client.pursue_quotation("q-001")
    assert result["id"] == "inv-new"


# ── Dunnings ────────────────────────────────────────────────────────


async def test_create_dunning(client, mock_api):
    mock_api.post("/dunnings").respond(200, json={"id": "d-001"})
    result = await client.create_dunning({"invoiceId": "inv-001"})
    assert result["id"] == "d-001"


async def test_render_dunning_document(client, mock_api):
    mock_api.post("/dunnings/d-001/document").respond(200, json={"documentFileId": "f-d"})
    result = await client.render_dunning_document("d-001")
    assert result["documentFileId"] == "f-d"


# ── Articles ────────────────────────────────────────────────────────


async def test_create_article(client, mock_api):
    mock_api.post("/articles").respond(200, json={"id": "a-001"})
    result = await client.create_article({"title": "Consulting", "type": "SERVICE"})
    assert result["id"] == "a-001"


async def test_get_article(client, mock_api):
    mock_api.get("/articles/a-001").respond(200, json={"id": "a-001", "title": "Consulting"})
    result = await client.get_article("a-001")
    assert result["title"] == "Consulting"


async def test_update_article(client, mock_api):
    mock_api.put("/articles/a-001").respond(200, json={"id": "a-001", "version": 2})
    result = await client.update_article("a-001", {"version": 1, "title": "Updated"})
    assert result["version"] == 2


async def test_list_articles(client, mock_api):
    mock_api.get("/articles").respond(200, json={"content": [{"id": "a-001"}]})
    result = await client.list_articles()
    assert len(result["content"]) == 1


# ── Payments ────────────────────────────────────────────────────────


async def test_get_payments(client, mock_api):
    mock_api.get("/payments/inv-001").respond(200, json={"openAmount": 500})
    result = await client.get_payments("inv-001")
    assert result["openAmount"] == 500


# ── File upload ─────────────────────────────────────────────────────


async def test_upload_file(client, mock_api):
    mock_api.post("/files").respond(200, json={"id": "f-001"})
    result = await client.upload_file(b"fake-content", "bill.pdf")
    assert result["id"] == "f-001"


# ── Rate limit retry ────────────────────────────────────────────────


async def test_429_retry(client, mock_api):
    route = mock_api.get("/profile")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"companyName": "CDIT"}),
    ]
    result = await client.get_profile()
    assert result["companyName"] == "CDIT"


# ── Error handling ───────────────────────────────────────────────────


async def test_http_error_propagates(client, mock_api):
    mock_api.get("/profile").respond(401, json={"message": "Unauthorized"})
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_profile()


async def test_404_propagates(client, mock_api):
    mock_api.get("/invoices/nonexistent").respond(404, json={"message": "Not found"})
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.get_invoice("nonexistent")
    assert exc_info.value.response.status_code == 404
