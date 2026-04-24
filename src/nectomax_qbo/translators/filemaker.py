"""FileMaker → QBO translator — cleaner-industry accounting flows.

Converts FM-sourced Order / Payment / adjustment data into QBO JournalEntry
payloads following Widmers-originated carpet/rug-cleaning accounting
conventions. Ported from widmers-qbo/scripts/daily-sync.js.

Tenant policy (account roles, doc number prefix, cash routing overrides)
arrives as ``CleanerTenantQbConfig`` — the caller loads it from their
config store and passes it in. This module never reads config from a DB.

Consumers: any orchestrator workflow that transforms FM payment/order
data into QBO. The calling convention is:

    from nectomax_qbo import qb_create
    from nectomax_qbo.translators.filemaker import (
        CleanerTenantQbConfig,
        build_wc_je,
        route_cash_payment,
    )

    policy = load_tenant_config(tenant_id)  # returns CleanerTenantQbConfig
    payload = build_wc_je(
        order_id="123", customer_name="...", date="2026-04-24",
        doc_number="WS-00042", total=150.0,
        revenue_lines=[...], tax=12.0, config=policy,
    )
    await qb_create(credentials, "JournalEntry", payload)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..types import AccountRef
from ._shared import _line, _round

# ── Tenant policy (cleaner-industry shape) ──────────────────────────────


class JeType(StrEnum):
    """Widmers JE category labels — carpet/rug-cleaning cash-sale flow."""

    WC = "WC"  # Work Complete — revenue recognition
    PAY = "PAY"  # Payment — A/R clearing
    BATCH = "BATCH"  # Auth.net batch deposit (lives in authnet translator)
    RJE = "RJE"  # Reversal JE


@dataclass
class CleanerTenantQbConfig:
    """Cleaner-industry accounting role → QBO account/class/customer refs.

    The orchestrator loads this from its tenant config store and passes
    it in. The library never reads config from a database.

    Field naming reflects the Widmers/cleaner chart of accounts. A non-
    cleaner tenant would use a different config dataclass (e.g. future
    ``RetailTenantQbConfig``) in a different translator module.
    """

    realm_id: str
    doc_number_prefix: str = "WS"

    # Account roles → AccountRef
    ar_receivable: AccountRef | None = None
    payments_to_deposit: AccountRef | None = None
    carpet_revenue: AccountRef | None = None
    rug_cleaning_revenue: AccountRef | None = None
    treatment_revenue: AccountRef | None = None
    product_sales_revenue: AccountRef | None = None
    misc_revenue: AccountRef | None = None
    storage_revenue: AccountRef | None = None
    rug_sales_revenue: AccountRef | None = None
    discounts_refunds: AccountRef | None = None
    deferred_sales_tax: AccountRef | None = None
    sales_tax_payable: AccountRef | None = None
    checking_account: AccountRef | None = None
    petty_cash_carpet: AccountRef | None = None
    petty_cash_rug: AccountRef | None = None

    # Class roles → AccountRef
    class_plant: AccountRef | None = None
    class_on_location: AccountRef | None = None

    # Customer roles → AccountRef
    customer_rug_sales: AccountRef | None = None
    customer_carpet_sales: AccountRef | None = None


# ── Cash routing (payment method → deposit account) ──────────────────────


SMALL_ADJUSTMENT_CEILING = 5.0


@dataclass
class PaymentLink:
    """A single payment link record from FM."""

    payment_type: str  # Cash, Credit Card, Check, eCheck, Adjustment, NONE
    payment_amount: float


@dataclass(frozen=True)
class CashRoutingLine:
    """A single line in a cash routing result."""

    description: str
    amount: float
    account_ref: AccountRef
    posting_type: str = "Debit"


@dataclass
class CashRoutingResult:
    """Result of cash routing decision."""

    lines: list[CashRoutingLine]
    warning: dict | None = None


def route_cash_payment(
    payment_links: list[PaymentLink],
    invoice_amount: float,
    petty_cash_ref: AccountRef | None,
    payments_to_deposit_ref: AccountRef,
) -> CashRoutingResult:
    """Route payment to Petty Cash or Payments to Deposit.

    6-case decision tree ported from widmers-qbo/scripts/lib/cash-routing.js.

    Cases:
      0: Petty Cash ref is None → fallback all to PTD
      A: Pure Cash → Petty Cash
      A2: Pure non-Cash → PTD
      B: Single type + negative Adjustment → net and route
      C: Multiple types + negative Adjustment → fallback PTD
      D: Small positive Adjustment (≤ ceiling) → inflate PTD bucket
      E: Large positive Adjustment (> ceiling) → fallback PTD
      F: Mixed +/- Adjustments → fallback PTD
    """
    if not payment_links:
        return CashRoutingResult(
            lines=[
                CashRoutingLine(
                    description="Payment",
                    amount=_round(abs(invoice_amount)),
                    account_ref=payments_to_deposit_ref,
                )
            ],
        )

    # Case 0: No petty cash account
    if petty_cash_ref is None:
        return CashRoutingResult(
            lines=[
                CashRoutingLine(
                    description="Payment (no petty cash account)",
                    amount=_round(abs(invoice_amount)),
                    account_ref=payments_to_deposit_ref,
                )
            ],
            warning={"reason": "Petty Cash account not configured, routing all to PTD"},
        )

    adjustments = [pl for pl in payment_links if pl.payment_type == "Adjustment"]
    payments = [pl for pl in payment_links if pl.payment_type != "Adjustment"]

    type_totals: dict[str, float] = {}
    for p in payments:
        type_totals[p.payment_type] = type_totals.get(p.payment_type, 0) + p.payment_amount

    neg_adj_total = _round(sum(a.payment_amount for a in adjustments if a.payment_amount < 0))
    pos_adj_total = _round(sum(a.payment_amount for a in adjustments if a.payment_amount > 0))

    # Case F: Mixed +/- adjustments
    if neg_adj_total < 0 and pos_adj_total > 0:
        return _fallback(
            invoice_amount, payments_to_deposit_ref, "Mixed positive and negative adjustments"
        )

    # Case E: Large positive adjustment
    if pos_adj_total > SMALL_ADJUSTMENT_CEILING:
        return _fallback(
            invoice_amount,
            payments_to_deposit_ref,
            f"Positive adjustment ${pos_adj_total:.2f} "
            f"exceeds ${SMALL_ADJUSTMENT_CEILING:.2f} ceiling",
        )

    payment_types = [t for t in type_totals if t not in ("NONE", "Adjustment")]

    # Case C: Multiple payment types + negative adjustment
    if len(payment_types) > 1 and neg_adj_total < 0:
        return _fallback(
            invoice_amount,
            payments_to_deposit_ref,
            "Multiple payment types with negative adjustment",
        )

    # Case B: Single type + negative adjustment → net
    if len(payment_types) == 1 and neg_adj_total < 0:
        ptype = payment_types[0]
        net = _round(type_totals[ptype] + neg_adj_total)
        if net <= 0:
            return _fallback(
                invoice_amount, payments_to_deposit_ref, f"Net after adjustment is ${net:.2f}"
            )
        ref = petty_cash_ref if ptype == "Cash" else payments_to_deposit_ref
        desc = "Cash at plant → Petty Cash" if ptype == "Cash" else "Payment"
        return CashRoutingResult(
            lines=[
                CashRoutingLine(
                    description=desc,
                    amount=_round(abs(invoice_amount)),
                    account_ref=ref,
                )
            ],
        )

    # Case D: Small positive adjustment → inflate PTD bucket
    cash_total = _round(type_totals.get("Cash", 0))
    other_total = _round(
        sum(v for k, v in type_totals.items() if k not in ("Cash", "NONE", "Adjustment"))
    )

    if pos_adj_total > 0:
        other_total = _round(other_total + pos_adj_total)

    # Case A: Pure Cash
    if cash_total > 0 and other_total == 0:
        return CashRoutingResult(
            lines=[
                CashRoutingLine(
                    description="Cash at plant → Petty Cash",
                    amount=_round(abs(invoice_amount)),
                    account_ref=petty_cash_ref,
                )
            ],
        )

    # Case A2: Pure non-Cash
    if cash_total == 0 and other_total > 0:
        return CashRoutingResult(
            lines=[
                CashRoutingLine(
                    description="Payment",
                    amount=_round(abs(invoice_amount)),
                    account_ref=payments_to_deposit_ref,
                )
            ],
        )

    # Mixed Cash + Other → two lines
    if cash_total > 0 and other_total > 0:
        return CashRoutingResult(
            lines=[
                CashRoutingLine(
                    description="Cash at plant → Petty Cash",
                    amount=_round(cash_total),
                    account_ref=petty_cash_ref,
                ),
                CashRoutingLine(
                    description="Payment",
                    amount=_round(other_total),
                    account_ref=payments_to_deposit_ref,
                ),
            ],
        )

    # Fallback: no categorizable payments
    return _fallback(invoice_amount, payments_to_deposit_ref, "No categorizable payment types")


def _fallback(
    invoice_amount: float,
    ptd_ref: AccountRef,
    reason: str,
) -> CashRoutingResult:
    return CashRoutingResult(
        lines=[
            CashRoutingLine(
                description="Payment (fallback)",
                amount=_round(abs(invoice_amount)),
                account_ref=ptd_ref,
            )
        ],
        warning={"reason": reason},
    )


# ── JE builders ──────────────────────────────────────────────────────────


def build_wc_je(
    *,
    order_id: str,
    customer_name: str,
    date: str,
    doc_number: str,
    total: float,
    revenue_lines: list[dict[str, float]],
    tax: float,
    config: CleanerTenantQbConfig,
    customer_ref: AccountRef | None = None,
    class_ref: AccountRef | None = None,
    memo_prefix: str = "",
) -> dict[str, Any] | None:
    """Build a Work Complete (revenue recognition) journal entry.

    revenue_lines: list of {"account_role": str, "amount": float}
      where account_role maps to a CleanerTenantQbConfig field name.

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
        lines.append(
            _line(
                f"{memo} | AR",
                abs(total),
                "Debit" if total > 0 else "Credit",
                ar_ref,
                entity_ref=customer_ref,
            )
        )

    # Credit: Revenue lines
    for rev in revenue_lines:
        role = rev["account_role"]
        amount = rev["amount"]
        if amount == 0:
            continue
        acct = getattr(config, role, None)
        if acct is None:
            continue
        lines.append(
            _line(
                f"{memo} | {acct.name}",
                abs(amount),
                "Credit" if total > 0 else "Debit",
                acct,
                class_ref=class_ref,
            )
        )

    # Credit: Tax
    if tax != 0 and config.deferred_sales_tax:
        lines.append(
            _line(
                f"{memo} | Tax",
                abs(tax),
                "Credit" if tax > 0 else "Debit",
                config.deferred_sales_tax,
            )
        )

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
    config: CleanerTenantQbConfig,
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
        lines.append(
            _line(
                f"{memo} | {cr_line.description}",
                cr_line.amount,
                posting,
                cr_line.account_ref,
            )
        )

    # Credit: A/R clearing
    ar_ref = config.ar_receivable
    if ar_ref:
        lines.append(
            _line(
                f"{memo} | AR clear",
                abs(total),
                "Credit" if total > 0 else "Debit",
                ar_ref,
                entity_ref=customer_ref,
            )
        )

    # Tax: reverse deferred, recognize as payable
    if tax != 0 and config.deferred_sales_tax and config.sales_tax_payable:
        lines.append(
            _line(
                f"{memo} | Deferred tax",
                abs(tax),
                "Debit",
                config.deferred_sales_tax,
            )
        )
        lines.append(
            _line(
                f"{memo} | Tax to pay",
                abs(tax),
                "Credit",
                config.sales_tax_payable,
            )
        )

    return {
        "DocNumber": doc_number,
        "TxnDate": date,
        "PrivateNote": private_note[:4000],
        "Line": lines,
    }
