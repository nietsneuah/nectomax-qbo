"""QBO REST transport — OAuth2 refresh, authenticated requests, retry logic."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .types import QbCredentials, QbEnvironment, QbResponse, QbTokens

# Callback invoked with the fresh QbTokens after a successful 401-driven refresh.
# Implementations should persist the new access_token + refresh_token back to
# whatever credential store the caller uses (e.g., Supabase Vault). Called at
# most once per qb_request invocation — if the second request also returns
# 401, we give up.
RefreshCallback = Callable[[QbTokens], Awaitable[None]]

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

BASE_URLS: dict[QbEnvironment, str] = {
    QbEnvironment.SANDBOX: "https://sandbox-quickbooks.api.intuit.com",
    QbEnvironment.PRODUCTION: "https://quickbooks.api.intuit.com",
}

DEFAULT_MINOR_VERSION = 73
MAX_RETRIES = 3

# Per-credential-chain refresh serialization.
#
# Intuit rotates the refresh_token on every successful refresh — the OLD
# refresh_token becomes invalid immediately. Concurrent refresh_tokens()
# calls for the same credential chain create a race: whichever hits Intuit
# second presents a now-invalidated refresh_token and gets `invalid_grant`,
# which looks to the caller like "user must re-auth" when in fact a sibling
# request already refreshed successfully.
#
# Keyed by (client_id, realm_id) — unique per credential chain (one Intuit
# app against one QB company). Locks are created lazily and persist for
# the process lifetime. This is coordination primitive state, not business
# state.
_refresh_locks: dict[tuple[str, str], asyncio.Lock] = {}
_refresh_locks_guard = asyncio.Lock()

# Short-lived in-memory cache of the most-recent refresh result per credential
# chain. When a sibling request arrives within REFRESH_COALESCE_WINDOW seconds
# of a successful refresh, we return the cached result instead of re-refreshing
# (the stale refresh_token it holds would fail with invalid_grant). Cache key
# matches the lock key.
REFRESH_COALESCE_WINDOW = 30.0  # seconds
_recent_refreshes: dict[tuple[str, str], tuple[float, QbTokens]] = {}


async def _get_refresh_lock(credentials: QbCredentials) -> asyncio.Lock:
    """Return the per-credential-chain refresh lock, creating it on first use."""
    key = (credentials.client_id, credentials.realm_id)
    async with _refresh_locks_guard:
        lock = _refresh_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _refresh_locks[key] = lock
        return lock


class QbAuthError(Exception):
    """401 from QBO — token invalid or revoked. Cannot auto-retry."""


class QbApiError(Exception):
    """Non-retriable QBO API error."""

    def __init__(self, message: str, code: str | None = None, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.detail = detail


async def refresh_tokens(credentials: QbCredentials) -> QbTokens:
    """Refresh OAuth2 tokens. Intuit issues a NEW refresh token each time.

    Concurrency-safe: serialized per credential chain, and coalesces siblings
    that arrive within REFRESH_COALESCE_WINDOW of a successful refresh
    (returning the cached fresh tokens rather than sending their stale
    refresh_token to Intuit and getting `invalid_grant`). See module docstrings
    on `_refresh_locks` and `_recent_refreshes`.
    """
    key = (credentials.client_id, credentials.realm_id)
    lock = await _get_refresh_lock(credentials)
    async with lock:
        # Coalesce: if another caller just refreshed this chain, return theirs.
        recent = _recent_refreshes.get(key)
        if recent is not None:
            age, cached = recent
            if time.monotonic() - age < REFRESH_COALESCE_WINDOW:
                return cached

        auth_bytes = f"{credentials.client_id}:{credentials.client_secret}".encode()
        auth_header = base64.b64encode(auth_bytes).decode()

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TOKEN_URL,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": credentials.refresh_token,
                },
            )

        if resp.status_code != 200:
            raise QbAuthError(f"Token refresh failed: {resp.status_code} — {resp.text[:300]}")

        data = resp.json()
        tokens = QbTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=data.get("expires_in", 3600),
            x_refresh_token_expires_in=data.get("x_refresh_token_expires_in", 8726400),
        )
        # Cache for siblings arriving within the coalesce window.
        _recent_refreshes[key] = (time.monotonic(), tokens)
        return tokens


def _base_url(credentials: QbCredentials) -> str:
    return BASE_URLS[credentials.environment]


def _api_url(
    credentials: QbCredentials,
    endpoint: str,
    minor_version: int = DEFAULT_MINOR_VERSION,
) -> str:
    base = _base_url(credentials)
    return f"{base}/v3/company/{credentials.realm_id}/{endpoint}?minorversion={minor_version}"


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def qb_request(
    credentials: QbCredentials,
    method: str,
    endpoint: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    minor_version: int = DEFAULT_MINOR_VERSION,
    max_retries: int = MAX_RETRIES,
    on_auth_refresh: RefreshCallback | None = None,
) -> QbResponse:
    """Make an authenticated QBO API request with retry on 429/610.

    If `on_auth_refresh` is provided, also retries ONCE on 401: calls
    refresh_tokens(), invokes the callback so the caller can persist the
    rotated tokens, and retries the request with the fresh access_token.
    On a second 401 (after the one retry), raises QbAuthError. With no
    callback provided, any 401 raises QbAuthError immediately (previous behavior).
    """
    url = _api_url(credentials, endpoint, minor_version)

    if params:
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}&{param_str}"

    refreshed_once = False

    for attempt in range(max_retries + 1):
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method,
                url,
                headers=_headers(credentials.access_token),
                json=body if method.upper() != "GET" else None,
                timeout=30.0,
            )

        # 401 — refresh once if a callback is provided, else raise
        if resp.status_code == 401:
            if on_auth_refresh is not None and not refreshed_once:
                new_tokens = await refresh_tokens(credentials)
                credentials = dataclasses.replace(
                    credentials,
                    access_token=new_tokens.access_token,
                    refresh_token=new_tokens.refresh_token,
                )
                await on_auth_refresh(new_tokens)
                refreshed_once = True
                continue
            raise QbAuthError(
                f"401 Unauthorized from QBO. Token prefix: {credentials.access_token[:12]}..."
            )

        # 429 — rate limited, retry with backoff
        if resp.status_code == 429:
            if attempt < max_retries:
                delay = 2 ** (attempt + 1)
                await asyncio.sleep(delay)
                continue
            return QbResponse(
                ok=False,
                error={"Message": "Max retries exceeded (429)"},
                status_code=429,
            )

        data = resp.json()

        # Check for Fault (including 610 throttle)
        if "Fault" in data:
            fault = data["Fault"]
            errors = fault.get("Error", [])
            err = errors[0] if errors else {}
            code = err.get("code", "")

            # 610 — throttled, retry
            if code == "610" and attempt < max_retries:
                delay = 2 ** (attempt + 1)
                await asyncio.sleep(delay)
                continue

            return QbResponse(ok=False, data=data, error=err, status_code=resp.status_code)

        return QbResponse(ok=True, data=data, status_code=resp.status_code)

    return QbResponse(
        ok=False,
        error={"Message": "Max retries exceeded"},
        status_code=429,
    )


async def qb_query(
    credentials: QbCredentials,
    entity: str,
    where: str | None = None,
    *,
    max_results: int = 1000,
    start_position: int = 1,
) -> list[dict[str, Any]]:
    """Execute a QBO query and return the entity list."""
    sql = f"SELECT * FROM {entity}"
    if where:
        sql += f" WHERE {where}"
    sql += f" STARTPOSITION {start_position} MAXRESULTS {max_results}"

    resp = await qb_request(
        credentials,
        "GET",
        "query",
        params={"query": sql},
    )

    if not resp.ok:
        err = resp.error or {}
        raise QbApiError(
            f"Query failed: {err.get('Detail', err.get('Message', 'Unknown'))}",
            code=err.get("code"),
            detail=err.get("Detail"),
        )

    qr = (resp.data or {}).get("QueryResponse", {})
    return qr.get(entity, [])


async def qb_create(
    credentials: QbCredentials,
    entity: str,
    body: dict[str, Any],
) -> QbResponse:
    """Create a QBO entity."""
    return await qb_request(credentials, "POST", entity, body=body)
