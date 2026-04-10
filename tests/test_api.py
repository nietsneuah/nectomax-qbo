"""Tests for api module — high-level compose functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nectomax_qbo.api import create_journal_entry, create_payment
from nectomax_qbo.types import QbCredentials, QbEnvironment, QbResponse


@pytest.fixture
def creds() -> QbCredentials:
    return QbCredentials(
        client_id="c", client_secret="s", access_token="a",
        refresh_token="r", realm_id="123", environment=QbEnvironment.SANDBOX,
    )


JE_BODY = {"DocNumber": "WS-00001", "TxnDate": "2026-03-15", "Line": []}
PAYMENT_BODY = {"CustomerRef": {"value": "1"}, "TotalAmt": 100.0}


class TestCreateJournalEntry:
    @pytest.mark.asyncio
    async def test_successful_create(self, creds: QbCredentials) -> None:
        with patch("nectomax_qbo.api.qb_create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = QbResponse(
                ok=True,
                data={"JournalEntry": {"Id": "99", "DocNumber": "WS-00001"}},
            )
            result = await create_journal_entry(creds, JE_BODY)

        assert result.ok is True
        assert result.entity is not None
        assert result.entity["Id"] == "99"
        assert result.was_duplicate is False

    @pytest.mark.asyncio
    async def test_failed_create(self, creds: QbCredentials) -> None:
        with patch("nectomax_qbo.api.qb_create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = QbResponse(
                ok=False,
                error={"code": "6000", "Detail": "Validation error"},
            )
            result = await create_journal_entry(creds, JE_BODY)

        assert result.ok is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_idempotency_skip(self, creds: QbCredentials) -> None:
        callback = AsyncMock(return_value=True)  # Already exists

        with patch("nectomax_qbo.api.qb_create", new_callable=AsyncMock) as mock_create:
            result = await create_journal_entry(
                creds, JE_BODY,
                idempotency_key="test-key",
                dedupe_callback=callback,
            )

        assert result.ok is True
        assert result.was_duplicate is True
        mock_create.assert_not_called()  # No API call made

    @pytest.mark.asyncio
    async def test_idempotency_create_and_persist(self, creds: QbCredentials) -> None:
        call_log: list[tuple] = []

        async def callback(key: str, result: dict | None) -> bool | None:
            call_log.append((key, result))
            if result is None:
                return False  # Not a duplicate, proceed
            return None  # Post-create persist

        with patch("nectomax_qbo.api.qb_create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = QbResponse(
                ok=True,
                data={"JournalEntry": {"Id": "99"}},
            )
            result = await create_journal_entry(
                creds, JE_BODY,
                idempotency_key="test-key",
                dedupe_callback=callback,
            )

        assert result.ok is True
        assert result.was_duplicate is False
        assert len(call_log) == 2  # Pre-check + post-persist
        assert call_log[0] == ("test-key", None)
        assert call_log[1][0] == "test-key"
        assert call_log[1][1]["Id"] == "99"

    @pytest.mark.asyncio
    async def test_no_callback_skips_idempotency(self, creds: QbCredentials) -> None:
        with patch("nectomax_qbo.api.qb_create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = QbResponse(
                ok=True, data={"JournalEntry": {"Id": "1"}},
            )
            result = await create_journal_entry(
                creds, JE_BODY, idempotency_key="key",
            )

        assert result.ok is True
        mock_create.assert_called_once()


class TestCreatePayment:
    @pytest.mark.asyncio
    async def test_successful_create(self, creds: QbCredentials) -> None:
        with patch("nectomax_qbo.api.qb_create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = QbResponse(
                ok=True,
                data={"Payment": {"Id": "55"}},
            )
            result = await create_payment(creds, PAYMENT_BODY)

        assert result.ok is True
        assert result.entity is not None
        assert result.entity["Id"] == "55"

    @pytest.mark.asyncio
    async def test_idempotency_skip(self, creds: QbCredentials) -> None:
        callback = AsyncMock(return_value=True)

        with patch("nectomax_qbo.api.qb_create", new_callable=AsyncMock) as mock_create:
            result = await create_payment(
                creds, PAYMENT_BODY,
                idempotency_key="pay-key",
                dedupe_callback=callback,
            )

        assert result.was_duplicate is True
        mock_create.assert_not_called()
