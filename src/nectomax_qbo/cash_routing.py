"""Cash routing — payment method → deposit account mapping.

Ports the 6-case decision tree from widmers-qbo/scripts/lib/cash-routing.js.
Pure function: inspects payment links, returns debit-side JE lines.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import AccountRef, CashRoutingLine, CashRoutingResult

SMALL_ADJUSTMENT_CEILING = 5.0


@dataclass
class PaymentLink:
    """A single payment link record from FM."""

    payment_type: str  # Cash, Credit Card, Check, eCheck, Adjustment, NONE
    payment_amount: float


def _round(n: float) -> float:
    return round(n, 2)


def route_cash_payment(
    payment_links: list[PaymentLink],
    invoice_amount: float,
    petty_cash_ref: AccountRef | None,
    payments_to_deposit_ref: AccountRef,
) -> CashRoutingResult:
    """Route payment to Petty Cash or Payments to Deposit.

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
            lines=[CashRoutingLine(
                description="Payment",
                amount=_round(abs(invoice_amount)),
                account_ref=payments_to_deposit_ref,
            )],
        )

    # Case 0: No petty cash account
    if petty_cash_ref is None:
        return CashRoutingResult(
            lines=[CashRoutingLine(
                description="Payment (no petty cash account)",
                amount=_round(abs(invoice_amount)),
                account_ref=payments_to_deposit_ref,
            )],
            warning={"reason": "Petty Cash account not configured, routing all to PTD"},
        )

    # Partition: adjustments vs real payments
    adjustments = [l for l in payment_links if l.payment_type == "Adjustment"]
    payments = [l for l in payment_links if l.payment_type != "Adjustment"]

    # Sum by type
    type_totals: dict[str, float] = {}
    for p in payments:
        type_totals[p.payment_type] = type_totals.get(p.payment_type, 0) + p.payment_amount

    neg_adj_total = _round(sum(a.payment_amount for a in adjustments if a.payment_amount < 0))
    pos_adj_total = _round(sum(a.payment_amount for a in adjustments if a.payment_amount > 0))

    # Case F: Mixed +/- adjustments
    if neg_adj_total < 0 and pos_adj_total > 0:
        return _fallback(invoice_amount, payments_to_deposit_ref,
                         "Mixed positive and negative adjustments")

    # Case E: Large positive adjustment
    if pos_adj_total > SMALL_ADJUSTMENT_CEILING:
        return _fallback(invoice_amount, payments_to_deposit_ref,
                         f"Positive adjustment ${pos_adj_total:.2f} exceeds ${SMALL_ADJUSTMENT_CEILING:.2f} ceiling")

    payment_types = [t for t in type_totals if t not in ("NONE", "Adjustment")]

    # Case C: Multiple payment types + negative adjustment
    if len(payment_types) > 1 and neg_adj_total < 0:
        return _fallback(invoice_amount, payments_to_deposit_ref,
                         "Multiple payment types with negative adjustment")

    # Case B: Single type + negative adjustment → net
    if len(payment_types) == 1 and neg_adj_total < 0:
        ptype = payment_types[0]
        net = _round(type_totals[ptype] + neg_adj_total)
        if net <= 0:
            return _fallback(invoice_amount, payments_to_deposit_ref,
                             f"Net after adjustment is ${net:.2f}")
        ref = petty_cash_ref if ptype == "Cash" else payments_to_deposit_ref
        desc = "Cash at plant → Petty Cash" if ptype == "Cash" else "Payment"
        return CashRoutingResult(
            lines=[CashRoutingLine(description=desc, amount=_round(abs(invoice_amount)), account_ref=ref)],
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
            lines=[CashRoutingLine(
                description="Cash at plant → Petty Cash",
                amount=_round(abs(invoice_amount)),
                account_ref=petty_cash_ref,
            )],
        )

    # Case A2: Pure non-Cash
    if cash_total == 0 and other_total > 0:
        return CashRoutingResult(
            lines=[CashRoutingLine(
                description="Payment",
                amount=_round(abs(invoice_amount)),
                account_ref=payments_to_deposit_ref,
            )],
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
        lines=[CashRoutingLine(
            description="Payment (fallback)",
            amount=_round(abs(invoice_amount)),
            account_ref=ptd_ref,
        )],
        warning={"reason": reason},
    )
