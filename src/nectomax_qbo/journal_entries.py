"""Journal entry builders — WC, PAY, and BATCH as pure functions.

Ports carpet/rug WC and PAY JE construction from widmers-qbo daily-sync.js.
All functions return dicts ready for qb_create("JournalEntry", ...).
"""

from __future__ import annotations

from typing import Any

from .types import AccountRef, CashRoutingResult, TenantQbConfig


def _round(n: float) -> float:
    return round(n, 2)


def _line(
    description: str,
    amount: float,
    posting_type: str,
    account_ref: AccountRef,
    *,
    class_ref: AccountRef | None = None,
    entity_ref: AccountRef | None = None,
    entity_type: str = "Customer",
) -> dict[str, Any]:
    """Build a single JE line detail dict."""
    detail: dict[str, Any] = {
        "PostingType": posting_type,
        "AccountRef": {"value": account_ref.value, "name": account_ref.name},
    }
    if class_ref:
        detail["ClassRef"] = {"value": class_ref.value, "name": class_ref.name}
    if entity_ref:
        detail["Entity"] = {
            "Type": entity_type,
            "EntityRef": {"value": entity_ref.value, "name": entity_ref.name},
        }

    return {
        "Description": description,
        "Amount": _round(amount),
        "DetailType": "JournalEntryLineDetail",
        "JournalEntryLineDetail": detail,
    }


def build_wc_je(
    *,
    order_id: str,
    customer_name: str,
    date: str,
    doc_number: str,
    total: float,
    revenue_lines: list[dict[str, float]],
    tax: float,
    config: TenantQbConfig,
    customer_ref: AccountRef | None = None,
    class_ref: AccountRef | None = None,
    memo_prefix: str = "",
) -> dict[str, Any] | None:
    """Build a Work Complete (revenue recognition) journal entry.

    revenue_lines: list of {"account_role": str, "amount": float}
      where account_role maps to a TenantQbConfig field name.

    Returns None if total == 0 (skip).
    """
    if total == 0:
        return None

    memo = f"{order_id} | {customer_name}"
    if memo_prefix:
        memo = f"{memo} | {memo_prefix}"
    tag = f"{order_id}|WC"
    private_note = f"{memo} | {tag}"

    lines: list[dict[str, Any]] = []

    # Debit: Accounts Receivable
    ar_ref = config.ar_receivable
    if ar_ref:
        lines.append(_line(
            f"{memo} | AR",
            abs(total),
            "Debit" if total > 0 else "Credit",
            ar_ref,
            entity_ref=customer_ref,
        ))

    # Credit: Revenue lines
    for rev in revenue_lines:
        role = rev["account_role"]
        amount = rev["amount"]
        if amount == 0:
            continue
        acct = getattr(config, role, None)
        if acct is None:
            continue
        lines.append(_line(
            f"{memo} | {acct.name}",
            abs(amount),
            "Credit" if total > 0 else "Debit",
            acct,
            class_ref=class_ref,
        ))

    # Credit: Tax
    if tax != 0 and config.deferred_sales_tax:
        lines.append(_line(
            f"{memo} | Tax",
            abs(tax),
            "Credit" if tax > 0 else "Debit",
            config.deferred_sales_tax,
        ))

    return {
        "DocNumber": doc_number,
        "TxnDate": date,
        "PrivateNote": private_note[:4000],
        "Line": lines,
    }


def build_pay_je(
    *,
    order_id: str,
    customer_name: str,
    date: str,
    doc_number: str,
    total: float,
    tax: float,
    cash_routing: CashRoutingResult,
    config: TenantQbConfig,
    customer_ref: AccountRef | None = None,
    memo_prefix: str = "",
) -> dict[str, Any] | None:
    """Build a Payment (A/R clearing) journal entry.

    Returns None if total == 0.
    """
    if total == 0:
        return None

    memo = f"{order_id} | {customer_name}"
    if memo_prefix:
        memo = f"{memo} | {memo_prefix}"
    tag = f"{order_id}|PAY"
    private_note = f"{memo} | {tag}"

    lines: list[dict[str, Any]] = []

    # Debit: Cash routing lines (Petty Cash and/or PTD)
    for cr_line in cash_routing.lines:
        posting = cr_line.posting_type
        # Flip for negative invoices (credits/refunds)
        if total < 0:
            posting = "Credit" if posting == "Debit" else "Debit"
        lines.append(_line(
            f"{memo} | {cr_line.description}",
            cr_line.amount,
            posting,
            cr_line.account_ref,
        ))

    # Credit: A/R clearing
    ar_ref = config.ar_receivable
    if ar_ref:
        lines.append(_line(
            f"{memo} | AR clear",
            abs(total),
            "Credit" if total > 0 else "Debit",
            ar_ref,
            entity_ref=customer_ref,
        ))

    # Tax: reverse deferred, recognize as payable
    if tax != 0 and config.deferred_sales_tax and config.sales_tax_payable:
        lines.append(_line(
            f"{memo} | Deferred tax",
            abs(tax),
            "Debit",
            config.deferred_sales_tax,
        ))
        lines.append(_line(
            f"{memo} | Tax to pay",
            abs(tax),
            "Credit",
            config.sales_tax_payable,
        ))

    return {
        "DocNumber": doc_number,
        "TxnDate": date,
        "PrivateNote": private_note[:4000],
        "Line": lines,
    }


def build_batch_je(
    *,
    batch_id: str,
    payment_method: str,
    settlement_date: str,
    net_amount: float,
    txn_count: int,
    doc_number: str,
    config: TenantQbConfig,
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
        lines.append(_line(
            f"Auth.net Batch {batch_id} | {payment_method}",
            net_amount,
            "Debit",
            config.checking_account,
        ))

    # Credit: Payments to deposit
    if config.payments_to_deposit:
        lines.append(_line(
            f"Auth.net Batch {batch_id} | {payment_method}",
            net_amount,
            "Credit",
            config.payments_to_deposit,
        ))

    return {
        "DocNumber": doc_number,
        "TxnDate": settlement_date,
        "PrivateNote": memo[:4000],
        "Line": lines,
    }
