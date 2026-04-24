"""Auth.net → QBO translator — settled-batch deposit reconciliation.

Converts Authorize.net batch-settlement data into a QBO JournalEntry
that reconciles the deposit: Debit Checking, Credit Payments-to-Deposit.

The batch_id + payment_method + settlement_date drive the memo; the
tenant's ``checking_account`` and ``payments_to_deposit`` account refs
come from the caller-supplied ``CleanerTenantQbConfig`` policy.

Imports ``CleanerTenantQbConfig`` from the filemaker translator because
the cleaner-industry account roles (checking_account, payments_to_deposit)
are shared across both FM- and Authnet-sourced flows for Widmers. A non-
cleaner tenant would have its own translator + config pair.
"""

from __future__ import annotations

from typing import Any

from ._shared import _line
from .filemaker import CleanerTenantQbConfig


def build_batch_je(
    *,
    batch_id: str,
    payment_method: str,
    settlement_date: str,
    net_amount: float,
    txn_count: int,
    doc_number: str,
    config: CleanerTenantQbConfig,
) -> dict[str, Any] | None:
    """Build an Auth.net deposit reconciliation JE.

    Returns None if net_amount <= 0.
    """
    if net_amount <= 0:
        return None

    memo = (
        f"BATCH-{batch_id} | {payment_method} | {settlement_date} "
        f"| {txn_count} txns | ${net_amount:.2f}"
    )

    lines: list[dict[str, Any]] = []

    # Debit: Checking account
    if config.checking_account:
        lines.append(
            _line(
                f"Auth.net Batch {batch_id} | {payment_method}",
                net_amount,
                "Debit",
                config.checking_account,
            )
        )

    # Credit: Payments to deposit
    if config.payments_to_deposit:
        lines.append(
            _line(
                f"Auth.net Batch {batch_id} | {payment_method}",
                net_amount,
                "Credit",
                config.payments_to_deposit,
            )
        )

    return {
        "DocNumber": doc_number,
        "TxnDate": settlement_date,
        "PrivateNote": memo[:4000],
        "Line": lines,
    }
