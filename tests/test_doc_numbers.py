"""Tests for doc_numbers module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nectomax_qbo.doc_numbers import (
    format_doc_number,
    parse_doc_number,
    query_qbo_max_doc_number,
    reserve_next_doc_number,
    resolve_next_doc_number,
)
from nectomax_qbo.types import QbCredentials, QbEnvironment


@pytest.fixture
def creds() -> QbCredentials:
    return QbCredentials(
        client_id="c",
        client_secret="s",
        access_token="a",
        refresh_token="r",
        realm_id="123",
        environment=QbEnvironment.SANDBOX,
    )


class TestFormatDocNumber:
    def test_default_prefix(self) -> None:
        assert format_doc_number(1) == "WS-00001"
        assert format_doc_number(105) == "WS-00105"
        assert format_doc_number(99999) == "WS-99999"

    def test_custom_prefix(self) -> None:
        assert format_doc_number(42, "AR") == "AR-00042"

    def test_zero(self) -> None:
        assert format_doc_number(0) == "WS-00000"


class TestParseDocNumber:
    def test_valid(self) -> None:
        assert parse_doc_number("WS-00105") == 105
        assert parse_doc_number("WS-00001") == 1

    def test_custom_prefix(self) -> None:
        assert parse_doc_number("AR-00042", "AR") == 42

    def test_wrong_prefix(self) -> None:
        assert parse_doc_number("XX-00001") is None

    def test_non_numeric(self) -> None:
        assert parse_doc_number("WS-abc") is None

    def test_empty(self) -> None:
        assert parse_doc_number("") is None

    def test_no_prefix_match(self) -> None:
        assert parse_doc_number("12345") is None


class TestResolveNextDocNumber:
    def test_state_higher(self) -> None:
        assert resolve_next_doc_number(state_number=100, qbo_max=50) == 100

    def test_qbo_higher(self) -> None:
        assert resolve_next_doc_number(state_number=50, qbo_max=100) == 101

    def test_equal(self) -> None:
        assert resolve_next_doc_number(state_number=100, qbo_max=99) == 100

    def test_both_zero(self) -> None:
        assert resolve_next_doc_number(state_number=0, qbo_max=0) == 1

    def test_state_file_lost(self) -> None:
        """Self-healing: state file gone (number=1), QBO has docs up to 105."""
        assert resolve_next_doc_number(state_number=1, qbo_max=105) == 106


class TestQueryQboMaxDocNumber:
    @pytest.mark.asyncio
    async def test_finds_max(self, creds: QbCredentials) -> None:
        with patch("nectomax_qbo.doc_numbers.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [
                {"DocNumber": "WS-00050"},
                {"DocNumber": "WS-00105"},
                {"DocNumber": "MANUAL-001"},
                {"DocNumber": "WS-00003"},
            ]
            result = await query_qbo_max_doc_number(creds)

        assert result == 105

    @pytest.mark.asyncio
    async def test_no_matching_docs(self, creds: QbCredentials) -> None:
        with patch("nectomax_qbo.doc_numbers.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [
                {"DocNumber": "MANUAL-001"},
                {"DocNumber": ""},
            ]
            result = await query_qbo_max_doc_number(creds)

        assert result == 0

    @pytest.mark.asyncio
    async def test_empty_qbo(self, creds: QbCredentials) -> None:
        with patch("nectomax_qbo.doc_numbers.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            result = await query_qbo_max_doc_number(creds)

        assert result == 0

    @pytest.mark.asyncio
    async def test_pagination(self, creds: QbCredentials) -> None:
        page1 = [{"DocNumber": f"WS-{str(i).zfill(5)}"} for i in range(1, 1001)]
        page2 = [{"DocNumber": "WS-01001"}, {"DocNumber": "WS-01050"}]

        with patch("nectomax_qbo.doc_numbers.qb_query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [page1, page2]
            result = await query_qbo_max_doc_number(creds)

        assert result == 1050
        assert mock_query.call_count == 2


class TestReserveNextDocNumber:
    @pytest.mark.asyncio
    async def test_reserve(self, creds: QbCredentials) -> None:
        target = "nectomax_qbo.doc_numbers.query_qbo_max_doc_number"
        with patch(target, new_callable=AsyncMock) as mock_max:
            mock_max.return_value = 105
            doc_num, next_seq = await reserve_next_doc_number(creds, state_number=100)

        assert doc_num == "WS-00106"
        assert next_seq == 107

    @pytest.mark.asyncio
    async def test_reserve_state_higher(self, creds: QbCredentials) -> None:
        target = "nectomax_qbo.doc_numbers.query_qbo_max_doc_number"
        with patch(target, new_callable=AsyncMock) as mock_max:
            mock_max.return_value = 50
            doc_num, next_seq = await reserve_next_doc_number(creds, state_number=200)

        assert doc_num == "WS-00200"
        assert next_seq == 201
