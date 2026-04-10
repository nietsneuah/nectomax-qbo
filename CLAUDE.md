# nectomax-qbo

QuickBooks Online dialect library for the NectoMax four-layer architecture.

## What this is

A **dialect library** — encapsulates QBO REST API transport, account resolution, JE/payment builders, and doc number management. Consumed by `fmrug-orchestrator` via vendored import.

This is NOT a product, service, or adapter. It has no HTTP server, no CLI, no awareness of tenants or workflows. Those are orchestrator concerns.

## Architecture context

- **Layer:** Shared library consumed by Layer 4.4 (orchestrator service adapters)
- **Doc 1 reference:** §4.4 ServiceAdapter pattern — this library is what `QuickBooksAdapter` wraps
- **Doc 2 reference:** §5.0 Phase 6.0 — this repo's creation and structure
- **Source patterns:** Extracted from `widmers-qbo` (POC reference, JS → Python port)

## Project structure

```
src/nectomax_qbo/
├── __init__.py
├── transport.py      — OAuth2 client, token refresh, authenticated requests
├── accounts.py       — Account name → QBO ID resolution via TenantQbConfig
├── doc_numbers.py    — WS-NNNNN sequence with self-healing
├── journal_entries.py — WC + PAY JE builders (pure functions)
├── payments.py       — Payment application builders
├── cash_routing.py   — Payment method → deposit account mapping
└── api.py            — High-level compose module
tests/
docs/
```

## Conventions

- Python 3.12+
- `httpx` for HTTP (async)
- `pydantic` for models/config
- Strict mypy, ruff for linting
- TDD — tests before implementation
- Pure functions where possible; side effects only in transport layer

## Key design decisions

- **`TenantQbConfig` is passed in, not loaded.** The library doesn't know about Supabase or config storage. The orchestrator loads config and passes it.
- **Idempotency via callback.** `create_journal_entry` accepts a `dedupe_callback` — the library calls it before creating and after returning. The callback implementation (writing to `adapter_idempotency_log`) lives in the orchestrator.
- **No tenant awareness.** The library operates on one QBO realm at a time. Multi-tenancy is the orchestrator's job.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy src/
```
