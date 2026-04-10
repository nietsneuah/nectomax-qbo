# nectomax-qbo

QuickBooks Online dialect library for the NectoMax platform.

## Scope

This is a **dialect library**, not a product. It encapsulates QBO-specific knowledge:

- **Transport** — OAuth2 token refresh, authenticated REST calls, retry on 401
- **Account resolution** — map tenant-configured account names to QBO account IDs
- **Doc numbers** — `WS-NNNNN` sequence generation with self-healing gap detection
- **Journal entries** — WC (work complete) and PAY (payment) JE builders as pure functions
- **Payments** — Payment application builders
- **Cash routing** — Payment method → QBO deposit account mapping

## What this is NOT

- Not a standalone service — no HTTP server, no CLI
- Not an adapter — the `QuickBooksAdapter` in `fmrug-orchestrator` wraps this library
- Not aware of tenants, workflows, or orchestration — those are orchestrator concerns
- Not aware of `adapter_idempotency_log` — idempotency is injected via callback

## Consumers

- `fmrug-orchestrator` — vendors a subset into `src/fmrug_orchestrator/qbo/`

## Derived from

Patterns extracted from [`widmers-qbo`](https://github.com/nietsneuah/widmers-qbo) (frozen POC reference codebase). See `docs/widmers-qbo-pattern-map.md` for the extraction mapping.
