"""Tests for payments module."""

from __future__ import annotations

from nectomax_qbo.payments import build_payment
from nectomax_qbo.types import AccountRef

CUST = AccountRef("50", "Residential Carpet Sales")
DEPOSIT = AccountRef("8", "Fifth Third Business Checking")


class TestBuildPayment:
    def test_basic_payment(self) -> None:
        p = build_payment(
            customer_ref=CUST,
            amount=150.0,
            date="2026-03-15",
        )
        assert p is not None
        assert p["TotalAmt"] == 150.0
        assert p["TxnDate"] == "2026-03-15"
        assert p["CustomerRef"]["value"] == "50"

    def test_with_deposit_account(self) -> None:
        p = build_payment(
            customer_ref=CUST,
            amount=100.0,
            date="2026-03-15",
            deposit_to_ref=DEPOSIT,
        )
        assert p is not None
        assert "DepositToAccountRef" in p
        assert p["DepositToAccountRef"]["value"] == "8"

    def test_with_memo(self) -> None:
        p = build_payment(
            customer_ref=CUST,
            amount=75.0,
            date="2026-03-15",
            memo="Payment for C-5920",
        )
        assert p is not None
        assert p["PrivateNote"] == "Payment for C-5920"

    def test_zero_amount_returns_none(self) -> None:
        p = build_payment(
            customer_ref=CUST,
            amount=0,
            date="2026-03-15",
        )
        assert p is None

    def test_negative_amount_returns_none(self) -> None:
        p = build_payment(
            customer_ref=CUST,
            amount=-50.0,
            date="2026-03-15",
        )
        assert p is None

    def test_rounds_amount(self) -> None:
        p = build_payment(
            customer_ref=CUST,
            amount=99.999,
            date="2026-03-15",
        )
        assert p is not None
        assert p["TotalAmt"] == 100.0
