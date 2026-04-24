"""Shared types and dataclasses — pure QBO dialect primitives.

Scope: only types whose shape is dictated by the QBO REST API itself
(credentials, tokens, environment, response envelope, account refs).

Industry-specific types (cleaner-industry tenant config, cash routing
results, JE category labels) live in ``translators.filemaker`` — they
belong to the translator that uses them, not the core library.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class QbEnvironment(StrEnum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"


@dataclass(frozen=True)
class QbCredentials:
    """QuickBooks OAuth2 credentials. Passed in by the caller."""

    client_id: str
    client_secret: str
    access_token: str
    refresh_token: str
    realm_id: str
    environment: QbEnvironment = QbEnvironment.PRODUCTION


@dataclass(frozen=True)
class QbTokens:
    """Result of a token refresh."""

    access_token: str
    refresh_token: str
    expires_in: int
    x_refresh_token_expires_in: int


@dataclass(frozen=True)
class QbResponse:
    """Wrapper for QBO API responses."""

    ok: bool
    data: dict | None = None
    error: dict | None = None
    status_code: int = 200


@dataclass
class AccountRef:
    """QBO account/entity reference (value + name)."""

    value: str
    name: str
