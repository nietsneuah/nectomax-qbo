"""Shared primitives for translator modules — JE line builder + rounding.

Internal to the translators package. Not exported publicly; translator
modules import these directly.
"""

from __future__ import annotations

from typing import Any

from ..types import AccountRef


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
    """Build a single QBO JournalEntry line detail dict.

    Common shape used by every translator that composes JE payloads.
    Pure — returns a dict, does no I/O.
    """
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
