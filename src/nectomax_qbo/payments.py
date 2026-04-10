"""Payment builders for QBO payment creation."""

from __future__ import annotations

from typing import Any

from .types import AccountRef


def build_payment(
    *,
    customer_ref: AccountRef,
    amount: float,
    date: str,
    deposit_to_ref: AccountRef | None = None,
    payment_method: str | None = None,
    memo: str | None = None,
) -> dict[str, Any] | None:
    """Build a QBO Payment entity dict.

    Returns None if amount <= 0.
    """
    if amount <= 0:
        return None

    payment: dict[str, Any] = {
        "CustomerRef": {"value": customer_ref.value, "name": customer_ref.name},
        "TotalAmt": round(amount, 2),
        "TxnDate": date,
    }

    if deposit_to_ref:
        payment["DepositToAccountRef"] = {
            "value": deposit_to_ref.value,
            "name": deposit_to_ref.name,
        }

    if payment_method:
        payment["PaymentMethodRef"] = {"value": payment_method}

    if memo:
        payment["PrivateNote"] = memo[:4000]

    return payment
