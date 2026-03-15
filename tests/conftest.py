"""Shared fixtures for mcp-lexoffice tests."""

from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest
import respx

from mcp_lexoffice.client import BASE_URL, LexofficeClient


@pytest.fixture()
def mock_api():
    """respx mock router scoped to the Lexoffice base URL."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture()
def client(mock_api):
    """LexofficeClient with a fake API key (requests hit respx mocks)."""
    with patch.dict(os.environ, {"LEXOFFICE_API_KEY": "test-key-000"}):
        return LexofficeClient()
