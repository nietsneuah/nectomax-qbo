"""Tests for transport module — request construction, retry logic, error handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nectomax_qbo.transport import (
    QbAuthError,
    _api_url,
    _headers,
    qb_query,
    qb_request,
    refresh_tokens,
)
from nectomax_qbo.types import QbCredentials, QbEnvironment


def _mock_response(
    status_code: int = 200, json_data: dict | None = None, text: str = "",
) -> MagicMock:
    """Create a mock httpx response with sync .json() and .text."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def _mock_client(**kwargs: object) -> tuple[MagicMock, AsyncMock]:
    """Create a mock httpx.AsyncClient with async context manager support."""
    client = AsyncMock()
    for k, v in kwargs.items():
        setattr(client, k, v)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    cls = MagicMock(return_value=client)
    return cls, client


@pytest.fixture
def creds() -> QbCredentials:
    return QbCredentials(
        client_id="test_client_id",
        client_secret="test_client_secret",
        access_token="test_access_token_1234567890",
        refresh_token="test_refresh_token",
        realm_id="1234567890",
        environment=QbEnvironment.SANDBOX,
    )


@pytest.fixture
def prod_creds() -> QbCredentials:
    return QbCredentials(
        client_id="test_client_id",
        client_secret="test_client_secret",
        access_token="test_access_token_1234567890",
        refresh_token="test_refresh_token",
        realm_id="1234567890",
        environment=QbEnvironment.PRODUCTION,
    )


class TestUrlConstruction:
    def test_sandbox_url(self, creds: QbCredentials) -> None:
        url = _api_url(creds, "query")
        assert "sandbox-quickbooks.api.intuit.com" in url
        assert f"/v3/company/{creds.realm_id}/query" in url
        assert "minorversion=73" in url

    def test_production_url(self, prod_creds: QbCredentials) -> None:
        url = _api_url(prod_creds, "journalentry")
        assert "quickbooks.api.intuit.com" in url
        assert "sandbox" not in url

    def test_custom_minor_version(self, creds: QbCredentials) -> None:
        url = _api_url(creds, "query", minor_version=65)
        assert "minorversion=65" in url


class TestHeaders:
    def test_bearer_token(self) -> None:
        h = _headers("my_token_abc")
        assert h["Authorization"] == "Bearer my_token_abc"
        assert h["Accept"] == "application/json"


class TestRefreshTokens:
    @pytest.mark.asyncio
    async def test_successful_refresh(self, creds: QbCredentials) -> None:
        resp = _mock_response(200, {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
            "x_refresh_token_expires_in": 8726400,
        })
        cls, client = _mock_client()
        client.post = AsyncMock(return_value=resp)

        with patch("nectomax_qbo.transport.httpx.AsyncClient", cls):
            tokens = await refresh_tokens(creds)

        assert tokens.access_token == "new_access"
        assert tokens.refresh_token == "new_refresh"
        assert tokens.expires_in == 3600

    @pytest.mark.asyncio
    async def test_refresh_failure_raises(self, creds: QbCredentials) -> None:
        resp = _mock_response(401, text="invalid_client")
        cls, client = _mock_client()
        client.post = AsyncMock(return_value=resp)

        with patch("nectomax_qbo.transport.httpx.AsyncClient", cls):
            with pytest.raises(QbAuthError, match="Token refresh failed"):
                await refresh_tokens(creds)


class TestQbRequest:
    @pytest.mark.asyncio
    async def test_successful_get(self, creds: QbCredentials) -> None:
        resp = _mock_response(200, {"QueryResponse": {"Account": [{"Id": "1"}]}})
        cls, client = _mock_client()
        client.request = AsyncMock(return_value=resp)

        with patch("nectomax_qbo.transport.httpx.AsyncClient", cls):
            result = await qb_request(creds, "GET", "query")

        assert result.ok is True
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self, creds: QbCredentials) -> None:
        resp = _mock_response(401)
        cls, client = _mock_client()
        client.request = AsyncMock(return_value=resp)

        with patch("nectomax_qbo.transport.httpx.AsyncClient", cls):
            with pytest.raises(QbAuthError, match="401 Unauthorized"):
                await qb_request(creds, "GET", "query")

    @pytest.mark.asyncio
    async def test_429_retries_with_backoff(self, creds: QbCredentials) -> None:
        resp_429 = _mock_response(429)
        resp_ok = _mock_response(200, {"ok": True})
        cls, client = _mock_client()
        client.request = AsyncMock(side_effect=[resp_429, resp_ok])

        with patch("nectomax_qbo.transport.httpx.AsyncClient", cls):
            with patch("nectomax_qbo.transport.asyncio.sleep", new_callable=AsyncMock):
                result = await qb_request(creds, "GET", "query", max_retries=3)

        assert result.ok is True

    @pytest.mark.asyncio
    async def test_610_retries(self, creds: QbCredentials) -> None:
        fault_data = {"Fault": {"Error": [{"code": "610", "Detail": "Throttled"}]}}
        resp_610 = _mock_response(200, fault_data)
        resp_ok = _mock_response(200, {"JournalEntry": {"Id": "99"}})
        cls, client = _mock_client()
        client.request = AsyncMock(side_effect=[resp_610, resp_ok])

        with patch("nectomax_qbo.transport.httpx.AsyncClient", cls):
            with patch("nectomax_qbo.transport.asyncio.sleep", new_callable=AsyncMock):
                result = await qb_request(creds, "GET", "query", max_retries=3)

        assert result.ok is True

    @pytest.mark.asyncio
    async def test_non_retriable_fault(self, creds: QbCredentials) -> None:
        fault_data = {"Fault": {"Error": [{"code": "6000", "Detail": "Validation error"}]}}
        resp = _mock_response(400, fault_data)
        cls, client = _mock_client()
        client.request = AsyncMock(return_value=resp)

        with patch("nectomax_qbo.transport.httpx.AsyncClient", cls):
            result = await qb_request(creds, "GET", "query")

        assert result.ok is False
        assert result.error is not None
        assert result.error["code"] == "6000"

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, creds: QbCredentials) -> None:
        resp_429 = _mock_response(429)
        cls, client = _mock_client()
        client.request = AsyncMock(return_value=resp_429)

        with patch("nectomax_qbo.transport.httpx.AsyncClient", cls):
            with patch("nectomax_qbo.transport.asyncio.sleep", new_callable=AsyncMock):
                result = await qb_request(creds, "GET", "query", max_retries=1)

        assert result.ok is False
        assert "Max retries" in (result.error or {}).get("Message", "")


class TestQbQuery:
    @pytest.mark.asyncio
    async def test_query_returns_entities(self, creds: QbCredentials) -> None:
        resp = _mock_response(200, {"QueryResponse": {"Account": [{"Id": "1", "Name": "Cash"}]}})
        cls, client = _mock_client()
        client.request = AsyncMock(return_value=resp)

        with patch("nectomax_qbo.transport.httpx.AsyncClient", cls):
            results = await qb_query(creds, "Account", "Name = 'Cash'")

        assert len(results) == 1
        assert results[0]["Name"] == "Cash"

    @pytest.mark.asyncio
    async def test_query_empty_result(self, creds: QbCredentials) -> None:
        resp = _mock_response(200, {"QueryResponse": {}})
        cls, client = _mock_client()
        client.request = AsyncMock(return_value=resp)

        with patch("nectomax_qbo.transport.httpx.AsyncClient", cls):
            results = await qb_query(creds, "Account", "Name = 'NonExistent'")

        assert results == []
