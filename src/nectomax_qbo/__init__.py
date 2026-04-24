"""nectomax-qbo — QuickBooks Online dialect library for NectoMax.

Public surface is the pure QBO dialect: transport, REST primitives,
account resolution, doc-number helpers, generic payment builder.

Source-specific translators (Authnet → QBO, FileMaker → QBO, …) live
under ``nectomax_qbo.translators.*`` and are imported by their full
path. They are NOT re-exported from this package root — per convention
each translator's namespace is explicit at the call site:

    from nectomax_qbo.translators.authnet import build_batch_je
    from nectomax_qbo.translators.filemaker import (
        CleanerTenantQbConfig,
        build_wc_je,
        route_cash_payment,
    )
"""

__version__ = "0.3.0"

from .accounts import AccountCache, AccountNotFoundError
from .api import CreateResult, create_journal_entry, create_payment
from .doc_numbers import format_doc_number, parse_doc_number, reserve_next_doc_number
from .payments import build_payment
from .transport import (
    QbApiError,
    QbAuthError,
    RefreshCallback,
    qb_create,
    qb_query,
    qb_request,
    refresh_tokens,
)
from .types import (
    AccountRef,
    QbCredentials,
    QbEnvironment,
    QbResponse,
    QbTokens,
)

__all__ = [
    "AccountCache",
    "AccountNotFoundError",
    "AccountRef",
    "CreateResult",
    "QbApiError",
    "QbAuthError",
    "QbCredentials",
    "QbEnvironment",
    "QbResponse",
    "QbTokens",
    "RefreshCallback",
    "build_payment",
    "create_journal_entry",
    "create_payment",
    "format_doc_number",
    "parse_doc_number",
    "qb_create",
    "qb_query",
    "qb_request",
    "refresh_tokens",
    "reserve_next_doc_number",
]
