"""Doc number generation — WS-NNNNN sequence with self-healing."""

from __future__ import annotations

from typing import Any

from .transport import qb_query
from .types import QbCredentials


def format_doc_number(sequence: int, prefix: str = "WS") -> str:
    """Format a sequence number as PREFIX-NNNNN."""
    return f"{prefix}-{str(sequence).zfill(5)}"


def parse_doc_number(doc_number: str, prefix: str = "WS") -> int | None:
    """Parse PREFIX-NNNNN back to sequence int. Returns None if not matching."""
    expected = f"{prefix}-"
    if not doc_number.startswith(expected):
        return None
    digits = doc_number[len(expected):]
    if not digits.isdigit():
        return None
    return int(digits)


async def query_qbo_max_doc_number(
    credentials: QbCredentials,
    prefix: str = "WS",
) -> int:
    """Scan all JEs in QBO and find the max PREFIX-NNNNN in use.

    Returns 0 if no matching doc numbers found.
    """
    max_num = 0
    start_pos = 1

    while True:
        page = await qb_query(
            credentials,
            "JournalEntry",
            max_results=1000,
            start_position=start_pos,
        )

        for je in page:
            n = parse_doc_number(je.get("DocNumber", ""), prefix)
            if n is not None and n > max_num:
                max_num = n

        if len(page) < 1000:
            break
        start_pos += 1000

    return max_num


def resolve_next_doc_number(
    state_number: int,
    qbo_max: int,
) -> int:
    """Self-healing: return max(state_number, qbo_max + 1).

    Survives state file corruption — if QBO has higher numbers,
    we use QBO's max + 1 instead of the stale state.
    """
    return max(state_number, qbo_max + 1)


async def reserve_next_doc_number(
    credentials: QbCredentials,
    state_number: int,
    prefix: str = "WS",
) -> tuple[str, int]:
    """Reserve the next doc number. Returns (formatted, next_sequence).

    The caller must persist next_sequence to state storage.
    """
    qbo_max = await query_qbo_max_doc_number(credentials, prefix)
    sequence = resolve_next_doc_number(state_number, qbo_max)
    return format_doc_number(sequence, prefix), sequence + 1
