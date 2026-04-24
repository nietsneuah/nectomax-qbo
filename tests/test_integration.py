"""Integration tests against Widmers QB sandbox.

Run with: pytest tests/test_integration.py -v
Requires .env with valid QB sandbox credentials.
Skipped automatically if credentials are missing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nectomax_qbo.accounts import AccountCache
from nectomax_qbo.doc_numbers import query_qbo_max_doc_number
from nectomax_qbo.transport import qb_query, refresh_tokens
from nectomax_qbo.types import QbCredentials, QbEnvironment

# Load .env manually (no dotenv dependency)
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            if value and key.strip() not in os.environ:
                os.environ[key.strip()] = value.strip()


def _get_credentials() -> QbCredentials | None:
    client_id = os.environ.get("QB_CLIENT_ID", "")
    client_secret = os.environ.get("QB_CLIENT_SECRET", "")
    access_token = os.environ.get("QB_ACCESS_TOKEN", "")
    refresh_token = os.environ.get("QB_REFRESH_TOKEN", "")
    realm_id = os.environ.get("QB_REALM_ID", "")
    env = os.environ.get("QB_ENVIRONMENT", "sandbox")

    if not all([client_id, client_secret, refresh_token, realm_id]):
        return None

    return QbCredentials(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        refresh_token=refresh_token,
        realm_id=realm_id,
        environment=QbEnvironment(env),
    )


_creds = _get_credentials()
skip_no_creds = pytest.mark.skipif(_creds is None, reason="QB credentials not configured")


@pytest.fixture
def creds() -> QbCredentials:
    assert _creds is not None
    return _creds


@skip_no_creds
class TestTokenRefresh:
    @pytest.mark.asyncio
    async def test_refresh_tokens(self, creds: QbCredentials) -> None:
        tokens = await refresh_tokens(creds)
        assert tokens.access_token
        assert tokens.refresh_token
        assert tokens.expires_in > 0

        # Update env for subsequent tests
        os.environ["QB_ACCESS_TOKEN"] = tokens.access_token
        os.environ["QB_REFRESH_TOKEN"] = tokens.refresh_token


@skip_no_creds
class TestQueryAccounts:
    @pytest.mark.asyncio
    async def test_query_accounts(self, creds: QbCredentials) -> None:
        # Refresh token first to get valid access token
        tokens = await refresh_tokens(creds)
        fresh_creds = QbCredentials(
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            realm_id=creds.realm_id,
            environment=creds.environment,
        )

        accounts = await qb_query(fresh_creds, "Account", max_results=5)
        assert len(accounts) > 0
        assert "Id" in accounts[0]
        assert "Name" in accounts[0]


@skip_no_creds
class TestAccountCache:
    @pytest.mark.asyncio
    async def test_resolve_ar(self, creds: QbCredentials) -> None:
        tokens = await refresh_tokens(creds)
        fresh_creds = QbCredentials(
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            realm_id=creds.realm_id,
            environment=creds.environment,
        )

        cache = AccountCache(fresh_creds)
        ref = await cache.get_account_ref("Accounts Receivable (A/R)")
        assert ref.value
        assert ref.name == "Accounts Receivable (A/R)"


@skip_no_creds
class TestDocNumbers:
    @pytest.mark.asyncio
    async def test_scan_max_doc_number(self, creds: QbCredentials) -> None:
        tokens = await refresh_tokens(creds)
        fresh_creds = QbCredentials(
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            realm_id=creds.realm_id,
            environment=creds.environment,
        )

        max_num = await query_qbo_max_doc_number(fresh_creds)
        # Sandbox may have 0 or some existing JEs
        assert isinstance(max_num, int)
        assert max_num >= 0
