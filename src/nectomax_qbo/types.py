"""Shared types and dataclasses for nectomax-qbo."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class QbEnvironment(StrEnum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"


@dataclass(frozen=True)
class QbCredentials:
    """QuickBooks OAuth2 credentials. Passed in by the orchestrator."""

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

    lines: list[CashRoutingLine] = field(default_factory=list)
    warning: dict | None = None


class JeType(StrEnum):
    WC = "WC"
    PAY = "PAY"
    BATCH = "BATCH"
    RJE = "RJE"


@dataclass
class TenantQbConfig:
    """Maps abstract accounting roles to QBO account/class/customer IDs.

    The orchestrator loads this from tenant_qb_config and passes it in.
    The library never loads config from a database.
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
