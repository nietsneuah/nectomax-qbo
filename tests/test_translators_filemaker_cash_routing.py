"""Tests for translators.filemaker.route_cash_payment — all 6 cases plus edge cases."""

from __future__ import annotations

from nectomax_qbo.translators.filemaker import PaymentLink, route_cash_payment
from nectomax_qbo.types import AccountRef

PETTY_CASH = AccountRef(value="100", name="Petty Cash (Carpet)")
PTD = AccountRef(value="200", name="Payments to deposit")


class TestCaseNoPettyCash:
    def test_routes_all_to_ptd(self) -> None:
        links = [PaymentLink("Cash", 100.0)]
        result = route_cash_payment(links, 100.0, None, PTD)
        assert len(result.lines) == 1
        assert result.lines[0].account_ref == PTD
        assert result.warning is not None


class TestCasePureCash:
    def test_routes_to_petty_cash(self) -> None:
        links = [PaymentLink("Cash", 150.0)]
        result = route_cash_payment(links, 150.0, PETTY_CASH, PTD)
        assert len(result.lines) == 1
        assert result.lines[0].account_ref == PETTY_CASH
        assert result.lines[0].amount == 150.0
        assert result.warning is None

    def test_multiple_cash_payments(self) -> None:
        links = [PaymentLink("Cash", 50.0), PaymentLink("Cash", 100.0)]
        result = route_cash_payment(links, 150.0, PETTY_CASH, PTD)
        assert len(result.lines) == 1
        assert result.lines[0].account_ref == PETTY_CASH


class TestCasePureNonCash:
    def test_credit_card(self) -> None:
        links = [PaymentLink("Credit Card", 200.0)]
        result = route_cash_payment(links, 200.0, PETTY_CASH, PTD)
        assert len(result.lines) == 1
        assert result.lines[0].account_ref == PTD
        assert result.warning is None

    def test_check(self) -> None:
        links = [PaymentLink("Check", 75.0)]
        result = route_cash_payment(links, 75.0, PETTY_CASH, PTD)
        assert result.lines[0].account_ref == PTD

    def test_echeck(self) -> None:
        links = [PaymentLink("eCheck", 50.0)]
        result = route_cash_payment(links, 50.0, PETTY_CASH, PTD)
        assert result.lines[0].account_ref == PTD


class TestCaseSingleTypeNegAdjustment:
    def test_cash_with_negative_adjustment(self) -> None:
        links = [PaymentLink("Cash", 100.0), PaymentLink("Adjustment", -10.0)]
        result = route_cash_payment(links, 90.0, PETTY_CASH, PTD)
        assert len(result.lines) == 1
        assert result.lines[0].account_ref == PETTY_CASH
        assert result.warning is None

    def test_cc_with_negative_adjustment(self) -> None:
        links = [PaymentLink("Credit Card", 100.0), PaymentLink("Adjustment", -5.0)]
        result = route_cash_payment(links, 95.0, PETTY_CASH, PTD)
        assert result.lines[0].account_ref == PTD

    def test_net_zero_after_adjustment(self) -> None:
        links = [PaymentLink("Cash", 10.0), PaymentLink("Adjustment", -10.0)]
        result = route_cash_payment(links, 0.0, PETTY_CASH, PTD)
        assert result.warning is not None  # Fallback


class TestCaseMultiTypeNegAdjustment:
    def test_fallback(self) -> None:
        links = [
            PaymentLink("Cash", 50.0),
            PaymentLink("Credit Card", 50.0),
            PaymentLink("Adjustment", -10.0),
        ]
        result = route_cash_payment(links, 90.0, PETTY_CASH, PTD)
        assert len(result.lines) == 1
        assert result.lines[0].account_ref == PTD
        assert result.warning is not None
        assert "Multiple payment types" in result.warning["reason"]


class TestCaseSmallPosAdjustment:
    def test_inflates_ptd_bucket(self) -> None:
        links = [
            PaymentLink("Credit Card", 95.0),
            PaymentLink("Adjustment", 5.0),
        ]
        result = route_cash_payment(links, 100.0, PETTY_CASH, PTD)
        assert len(result.lines) == 1
        assert result.lines[0].account_ref == PTD
        assert result.warning is None


class TestCaseLargePosAdjustment:
    def test_fallback(self) -> None:
        links = [
            PaymentLink("Cash", 50.0),
            PaymentLink("Adjustment", 50.0),
        ]
        result = route_cash_payment(links, 100.0, PETTY_CASH, PTD)
        assert result.warning is not None
        assert "ceiling" in result.warning["reason"]


class TestCaseMixedAdjustments:
    def test_fallback(self) -> None:
        links = [
            PaymentLink("Cash", 100.0),
            PaymentLink("Adjustment", -10.0),
            PaymentLink("Adjustment", 5.0),
        ]
        result = route_cash_payment(links, 95.0, PETTY_CASH, PTD)
        assert result.warning is not None
        assert "Mixed" in result.warning["reason"]


class TestMixedCashAndOther:
    def test_two_lines(self) -> None:
        links = [PaymentLink("Cash", 30.0), PaymentLink("Credit Card", 70.0)]
        result = route_cash_payment(links, 100.0, PETTY_CASH, PTD)
        assert len(result.lines) == 2
        cash_line = [ln for ln in result.lines if ln.account_ref == PETTY_CASH]
        other_line = [ln for ln in result.lines if ln.account_ref == PTD]
        assert len(cash_line) == 1
        assert cash_line[0].amount == 30.0
        assert len(other_line) == 1
        assert other_line[0].amount == 70.0


class TestEmptyLinks:
    def test_routes_to_ptd(self) -> None:
        result = route_cash_payment([], 100.0, PETTY_CASH, PTD)
        assert len(result.lines) == 1
        assert result.lines[0].account_ref == PTD
        assert result.warning is None
