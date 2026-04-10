"""Tests for accounts module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nectomax_qbo.accounts import AccountCache, AccountNotFoundError
from nectomax_qbo.types import QbCredentials, QbEnvironment


@pytest.fixture
def creds() -> QbCredentials:
    return QbCredentials(
        client_id="c", client_secret="s", access_token="a",
        refresh_token="r", realm_id="123", environment=QbEnvironment.SANDBOX,
    )


@pytest.fixture
def cache(creds: QbCredentials) -> AccountCache:
    return AccountCache(creds)


class TestAccountCache:
    @pytest.mark.asyncio
    async def test_get_account_ref(self, cache: AccountCache) -> None:
        with patch("nectomax_qbo.accounts.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [{"Id": "42", "Name": "Accounts Receivable (A/R)"}]
            ref = await cache.get_account_ref("Accounts Receivable (A/R)")

        assert ref.value == "42"
        assert ref.name == "Accounts Receivable (A/R)"

    @pytest.mark.asyncio
    async def test_caches_result(self, cache: AccountCache) -> None:
        with patch("nectomax_qbo.accounts.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [{"Id": "42", "Name": "Cash"}]

            ref1 = await cache.get_account_ref("Cash")
            ref2 = await cache.get_account_ref("Cash")

        assert ref1.value == ref2.value
        assert mock_query.call_count == 1  # Only one API call

    @pytest.mark.asyncio
    async def test_not_found_raises(self, cache: AccountCache) -> None:
        with patch("nectomax_qbo.accounts.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []

            with pytest.raises(AccountNotFoundError, match='Account not found: "Nonexistent"'):
                await cache.get_account_ref("Nonexistent")

    @pytest.mark.asyncio
    async def test_try_get_returns_none(self, cache: AccountCache) -> None:
        with patch("nectomax_qbo.accounts.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            ref = await cache.try_get_account_ref("Missing Account")

        assert ref is None

    @pytest.mark.asyncio
    async def test_get_class_ref(self, cache: AccountCache) -> None:
        with patch("nectomax_qbo.accounts.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [{"Id": "7", "Name": "Plant"}]
            ref = await cache.get_class_ref("Plant")

        assert ref.value == "7"
        assert ref.name == "Plant"

    @pytest.mark.asyncio
    async def test_get_customer_ref(self, cache: AccountCache) -> None:
        with patch("nectomax_qbo.accounts.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [{"Id": "99", "Name": "Area Rug Sales"}]
            ref = await cache.get_customer_ref("Area Rug Sales")

        assert ref.value == "99"

    @pytest.mark.asyncio
    async def test_escapes_single_quotes(self, cache: AccountCache) -> None:
        with patch("nectomax_qbo.accounts.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [{"Id": "1", "Name": "O'Brien"}]
            await cache.get_account_ref("O'Brien")

        call_args = mock_query.call_args
        where_clause = call_args[0][2]  # Third positional arg
        assert "\\'" in where_clause

    @pytest.mark.asyncio
    async def test_different_entity_types_cached_separately(self, cache: AccountCache) -> None:
        with patch("nectomax_qbo.accounts.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [
                [{"Id": "1", "Name": "Plant"}],  # Account
                [{"Id": "2", "Name": "Plant"}],  # Class
            ]
            acct = await cache.get_account_ref("Plant")
            cls = await cache.get_class_ref("Plant")

        assert acct.value == "1"
        assert cls.value == "2"
        assert mock_query.call_count == 2
