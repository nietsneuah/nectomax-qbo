"""Tests for journal_entries module — WC, PAY, BATCH builders."""

from __future__ import annotations

from nectomax_qbo.journal_entries import build_batch_je, build_pay_je, build_wc_je
from nectomax_qbo.types import AccountRef, CashRoutingLine, CashRoutingResult, TenantQbConfig


def _config() -> TenantQbConfig:
    return TenantQbConfig(
        realm_id="123",
        ar_receivable=AccountRef("1", "Accounts Receivable (A/R)"),
        payments_to_deposit=AccountRef("2", "Payments to deposit"),
        carpet_revenue=AccountRef("3", "Carpet Cleaning Income"),
        rug_cleaning_revenue=AccountRef("4", "Area Rug Cleaning Income"),
        treatment_revenue=AccountRef("5", "Treatment Income"),
        deferred_sales_tax=AccountRef("6", "Deferred Sales Tax"),
        sales_tax_payable=AccountRef("7", "Sales tax to pay"),
        checking_account=AccountRef("8", "Fifth Third Business Checking"),
        class_on_location=AccountRef("10", "On-Location"),
        class_plant=AccountRef("11", "Plant"),
    )


AR = AccountRef("1", "Accounts Receivable (A/R)")
PTD = AccountRef("2", "Payments to deposit")
PETTY = AccountRef("9", "Petty Cash (Carpet)")
CUST = AccountRef("50", "Residential Carpet Sales")


class TestBuildWcJe:
    def test_carpet_wc(self) -> None:
        je = build_wc_je(
            order_id="C-5920",
            customer_name="John Doe",
            date="2026-03-15",
            doc_number="WS-00105",
            total=250.0,
            revenue_lines=[{"account_role": "carpet_revenue", "amount": 230.0}],
            tax=20.0,
            config=_config(),
            customer_ref=CUST,
            class_ref=AccountRef("10", "On-Location"),
        )
        assert je is not None
        assert je["DocNumber"] == "WS-00105"
        assert je["TxnDate"] == "2026-03-15"
        assert "C-5920|WC" in je["PrivateNote"]
        assert len(je["Line"]) == 3  # AR + Revenue + Tax

        # AR line is debit
        ar_line = je["Line"][0]
        assert ar_line["JournalEntryLineDetail"]["PostingType"] == "Debit"
        assert ar_line["Amount"] == 250.0

        # Revenue line is credit
        rev_line = je["Line"][1]
        assert rev_line["JournalEntryLineDetail"]["PostingType"] == "Credit"
        assert rev_line["Amount"] == 230.0

        # Tax line is credit
        tax_line = je["Line"][2]
        assert tax_line["JournalEntryLineDetail"]["PostingType"] == "Credit"
        assert tax_line["Amount"] == 20.0

    def test_zero_total_returns_none(self) -> None:
        je = build_wc_je(
            order_id="C-0000",
            customer_name="Nobody",
            date="2026-01-01",
            doc_number="WS-00001",
            total=0,
            revenue_lines=[],
            tax=0,
            config=_config(),
        )
        assert je is None

    def test_skips_zero_revenue_lines(self) -> None:
        je = build_wc_je(
            order_id="C-5920",
            customer_name="John",
            date="2026-03-15",
            doc_number="WS-00105",
            total=100.0,
            revenue_lines=[
                {"account_role": "carpet_revenue", "amount": 100.0},
                {"account_role": "treatment_revenue", "amount": 0},
            ],
            tax=0,
            config=_config(),
        )
        assert je is not None
        # AR + 1 revenue (treatment skipped because amount=0)
        assert len(je["Line"]) == 2

    def test_rug_wc_with_multiple_revenue(self) -> None:
        je = build_wc_je(
            order_id="R-1234",
            customer_name="Jane",
            date="2026-03-20",
            doc_number="WS-00110",
            total=500.0,
            revenue_lines=[
                {"account_role": "rug_cleaning_revenue", "amount": 300.0},
                {"account_role": "treatment_revenue", "amount": 150.0},
            ],
            tax=50.0,
            config=_config(),
            class_ref=AccountRef("11", "Plant"),
            memo_prefix="Plant",
        )
        assert je is not None
        assert "Plant" in je["PrivateNote"]
        # AR + 2 revenue + tax
        assert len(je["Line"]) == 4


class TestBuildPayJe:
    def test_carpet_pay(self) -> None:
        routing = CashRoutingResult(
            lines=[CashRoutingLine("Payment", 250.0, PTD)]
        )
        je = build_pay_je(
            order_id="C-5920",
            customer_name="John Doe",
            date="2026-03-15",
            doc_number="WS-00106",
            total=250.0,
            tax=20.0,
            cash_routing=routing,
            config=_config(),
            customer_ref=CUST,
        )
        assert je is not None
        assert "C-5920|PAY" in je["PrivateNote"]
        # Cash routing + AR clear + deferred tax + tax to pay
        assert len(je["Line"]) == 4

    def test_zero_total_returns_none(self) -> None:
        routing = CashRoutingResult(lines=[])
        je = build_pay_je(
            order_id="C-0000",
            customer_name="Nobody",
            date="2026-01-01",
            doc_number="WS-00001",
            total=0,
            tax=0,
            cash_routing=routing,
            config=_config(),
        )
        assert je is None

    def test_negative_invoice_flips_postings(self) -> None:
        routing = CashRoutingResult(
            lines=[CashRoutingLine("Payment", 50.0, PTD, posting_type="Debit")]
        )
        je = build_pay_je(
            order_id="R-9999",
            customer_name="Refund",
            date="2026-03-20",
            doc_number="WS-00111",
            total=-50.0,
            tax=0,
            cash_routing=routing,
            config=_config(),
        )
        assert je is not None
        # Cash line should be flipped to Credit (negative invoice)
        cash_line = je["Line"][0]
        assert cash_line["JournalEntryLineDetail"]["PostingType"] == "Credit"
        # AR clearing should be Debit (flipped)
        ar_line = je["Line"][1]
        assert ar_line["JournalEntryLineDetail"]["PostingType"] == "Debit"

    def test_mixed_cash_routing(self) -> None:
        routing = CashRoutingResult(
            lines=[
                CashRoutingLine("Cash at plant", 30.0, PETTY),
                CashRoutingLine("Payment", 70.0, PTD),
            ]
        )
        je = build_pay_je(
            order_id="C-1000",
            customer_name="Split",
            date="2026-03-15",
            doc_number="WS-00112",
            total=100.0,
            tax=8.0,
            cash_routing=routing,
            config=_config(),
        )
        assert je is not None
        # 2 cash routing + AR + deferred tax + tax to pay
        assert len(je["Line"]) == 5


class TestBuildBatchJe:
    def test_deposit_je(self) -> None:
        je = build_batch_je(
            batch_id="12345",
            payment_method="creditCard",
            settlement_date="2026-03-15",
            net_amount=1500.50,
            txn_count=23,
            doc_number="WS-00120",
            config=_config(),
        )
        assert je is not None
        assert je["DocNumber"] == "WS-00120"
        assert "BATCH-12345" in je["PrivateNote"]
        assert len(je["Line"]) == 2

        # Debit checking
        assert je["Line"][0]["JournalEntryLineDetail"]["PostingType"] == "Debit"
        assert je["Line"][0]["Amount"] == 1500.50

        # Credit PTD
        assert je["Line"][1]["JournalEntryLineDetail"]["PostingType"] == "Credit"

    def test_zero_net_returns_none(self) -> None:
        je = build_batch_je(
            batch_id="99999",
            payment_method="eCheck",
            settlement_date="2026-03-15",
            net_amount=0,
            txn_count=0,
            doc_number="WS-00121",
            config=_config(),
        )
        assert je is None

    def test_negative_net_returns_none(self) -> None:
        je = build_batch_je(
            batch_id="88888",
            payment_method="creditCard",
            settlement_date="2026-03-15",
            net_amount=-100.0,
            txn_count=5,
            doc_number="WS-00122",
            config=_config(),
        )
        assert je is None
