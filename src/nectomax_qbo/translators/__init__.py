"""Source-shape → QBO-payload translators.

Each module in this package converts a specific source dialect's data
(Authnet batch, FileMaker payment row, GHL contact event, …) into QBO
REST-shaped entity dicts ready to hand to the core library's
``create_journal_entry`` / ``create_payment`` functions.

Convention — this package name is level 3 of the three-segment path
established in reference_adapter_translator_naming_convention:

    nectomax.<target>.translators.<source>

Tenant-specific policy (account role mappings, doc number prefixes,
cash routing overrides) arrives as a dataclass parameter to each
translator function — it is DATA, not code. Tenant-keyed import paths
are forbidden.

Nothing here knows about Supabase, Vault, or any orchestrator concern.
Translators are pure: given the same source-shape input + policy, they
produce the same QBO payload. Caller invokes ``qb_create`` / ``qb_query``
from the core library.
"""
