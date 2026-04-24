"""Tests for translators.authnet — batch deposit JE builder."""

from __future__ import annotations

from nectomax_qbo.translators.authnet import build_batch_je
from nectomax_qbo.translators.filemaker import CleanerTenantQbConfig
from nectomax_qbo.types import AccountRef


def _config() -> CleanerTenantQbConfig:
    return CleanerTenantQbConfig(
        realm_id="123",
        checking_account=AccountRef("8", "Fifth Third Business Checking"),
        payments_to_deposit=AccountRef("2", "Payments to deposit"),
    )


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
