"""High-level API — composes transport + domain modules into convenience functions.

The dedupe_callback is an injected hook: the library calls it before creating
and after returning. The callback implementation (e.g., writing to
adapter_idempotency_log) lives in the orchestrator, not here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .transport import qb_create
from .types import QbCredentials


@dataclass
class CreateResult:
    """Result of a create operation with idempotency tracking."""

    ok: bool
    entity: dict[str, Any] | None = None
    was_duplicate: bool = False
    error: dict[str, Any] | None = None


# Type alias for the dedupe callback
DedupeCallback = Callable[[str, dict[str, Any] | None], Awaitable[bool | None]]
"""
Called with (idempotency_key, result_or_none).
- Before create: callback(key, None) → return True if already exists (skip create)
- After create: callback(key, result) → persist the result
"""


async def create_journal_entry(
    credentials: QbCredentials,
    je_body: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    dedupe_callback: DedupeCallback | None = None,
) -> CreateResult:
    """Create a journal entry with optional idempotency.

    If dedupe_callback is provided and returns True for the pre-check,
    the create is skipped and was_duplicate=True is returned.
    """
    # Pre-check: is this a duplicate?
    if idempotency_key and dedupe_callback:
        is_dup = await dedupe_callback(idempotency_key, None)
        if is_dup:
            return CreateResult(ok=True, was_duplicate=True)

    resp = await qb_create(credentials, "journalentry", je_body)

    if not resp.ok:
        return CreateResult(ok=False, error=resp.error)

    entity = (resp.data or {}).get("JournalEntry")

    # Post-create: persist the result
    if idempotency_key and dedupe_callback and entity:
        await dedupe_callback(idempotency_key, entity)

    return CreateResult(ok=True, entity=entity)


async def create_payment(
    credentials: QbCredentials,
    payment_body: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    dedupe_callback: DedupeCallback | None = None,
) -> CreateResult:
    """Create a payment with optional idempotency."""
    if idempotency_key and dedupe_callback:
        is_dup = await dedupe_callback(idempotency_key, None)
        if is_dup:
            return CreateResult(ok=True, was_duplicate=True)

    resp = await qb_create(credentials, "payment", payment_body)

    if not resp.ok:
        return CreateResult(ok=False, error=resp.error)

    entity = (resp.data or {}).get("Payment")

    if idempotency_key and dedupe_callback and entity:
        await dedupe_callback(idempotency_key, entity)

    return CreateResult(ok=True, entity=entity)
