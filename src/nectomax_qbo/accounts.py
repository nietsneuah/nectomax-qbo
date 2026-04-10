"""Account resolution — name → QBO ID lookup with caching."""

from __future__ import annotations

from .transport import qb_query
from .types import AccountRef, QbCredentials, TenantQbConfig


class AccountNotFoundError(Exception):
    """Account name does not exist in QBO."""


class AccountCache:
    """Query-and-cache for QBO account/class/customer refs.

    One instance per sync run. Cache is module-level within the run,
    cleared on next run (no cross-run persistence).
    """

    def __init__(self, credentials: QbCredentials) -> None:
        self._credentials = credentials
        self._cache: dict[tuple[str, str], AccountRef] = {}

    async def get_account_ref(self, name: str) -> AccountRef:
        """Look up an account by name, caching the result."""
        return await self._get_ref("Account", name)

    async def get_class_ref(self, name: str) -> AccountRef:
        """Look up a class by name, caching the result."""
        return await self._get_ref("Class", name)

    async def get_customer_ref(self, name: str) -> AccountRef:
        """Look up a customer by name, caching the result."""
        return await self._get_ref("Customer", name)

    async def try_get_account_ref(self, name: str) -> AccountRef | None:
        """Soft-load: return None instead of raising if not found."""
        try:
            return await self.get_account_ref(name)
        except AccountNotFoundError:
            return None

    async def _get_ref(self, entity: str, name: str) -> AccountRef:
        key = (entity, name)
        if key in self._cache:
            return self._cache[key]

        escaped = name.replace("'", "\\'")
        results = await qb_query(
            self._credentials,
            entity,
            f"Name = '{escaped}'",
        )

        if not results:
            raise AccountNotFoundError(f"{entity} not found: \"{name}\"")

        ref = AccountRef(value=results[0]["Id"], name=results[0]["Name"])
        self._cache[key] = ref
        return ref

    async def resolve_tenant_config(self, config: TenantQbConfig) -> TenantQbConfig:
        """Resolve all account names in a TenantQbConfig to QBO IDs.

        This is a convenience for the orchestrator to call once at sync start.
        Accounts that are None in the config are skipped.
        """
        # This method would populate AccountRefs from QBO lookups.
        # For Phase 6.0, config is pre-populated by the orchestrator.
        # This is a placeholder for future auto-resolution.
        return config
