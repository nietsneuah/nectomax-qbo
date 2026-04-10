# widmers-qbo Pattern Map

**Phase 6.0 task 6.0-R2** — Comprehensive catalog of every QBO integration pattern in `widmers-qbo` for extraction into `nectomax-qbo`.

**Source repo:** `~/Dev/widmers-qbo/` (frozen POC reference)
**Target repo:** `~/Dev/nectomax-qbo/` (Python dialect library)
**Date:** 2026-04-10

---

## 1. OAUTH2 TOKEN MANAGEMENT

### A. Token Acquisition (Initial)
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/auth.js` (lines 1-89)

**What it does**: Express app that captures OAuth2 authorization code via browser redirect, exchanges it for access + refresh tokens via Intuit OAuth endpoint, and persists both to `.env` file.

**QBO API endpoints**:
- Authorization: `https://appcenter.intuit.com/connect/oauth2` (GET, redirect)
- Token exchange: `https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer` (POST)

**Key logic**:
1. Builds auth URI with client_id, redirect_uri, scope (`com.intuit.quickbooks.accounting`)
2. Receives auth code + realmId in callback
3. Encodes credentials as Basic auth: `Base64(client_id:client_secret)`
4. POSTs to token endpoint with `grant_type=authorization_code`
5. Extracts `access_token`, `refresh_token`, `expires_in` (3600s), `x_refresh_token_expires_in` (~100 days)
6. Overwrites `.env` with new tokens (regex replace lines)
7. Exits process after success

**Hardcoded values**:
- Scopes: `com.intuit.quickbooks.accounting`
- Auth URL: `https://appcenter.intuit.com/connect/oauth2`
- Token URL: `https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer`
- Port: 3000
- Content-Type: `application/x-www-form-urlencoded`

**Error handling**: JSON error response if token exchange fails; exits with status 400

---

### B. Token Refresh (Programmatic)
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/refresh-token.js` (lines 1-42)

**What it does**: Standalone script to refresh access + refresh tokens without user browser interaction. Auto-saves both tokens to `.env`.

**QBO API endpoints**:
- Token endpoint: `https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer` (POST)

**Key logic**:
1. Reads `QB_CLIENT_ID`, `QB_CLIENT_SECRET`, `QB_REFRESH_TOKEN` from env
2. Encodes credentials as Basic auth
3. POSTs with `grant_type=refresh_token`
4. Intuit issues NEW refresh token on each refresh (rotation)
5. Both tokens must be persisted immediately
6. Logs token TTLs to console

**Hardcoded values**: Token URL, grant type, content-type

**Called by**: `daily-sync.js` Step 1 (inline), and standalone `node scripts/refresh-token.js`

**Critical note**: Intuit issues a new refresh token on EVERY refresh call. The old one becomes invalid. Must persist immediately or subsequent refreshes fail with `invalid_client`.

---

### C. In-Flight Token Handling
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/qb-api.js` (lines 8-33)

**What it does**: Module-level token capture strategy. Access token is read fresh on EVERY request (not cached at module load time), so token refreshes in Step 1 are picked up immediately.

**Key logic**:
```javascript
// NOTE at top: QB_ACCESS_TOKEN is NOT destructured at module load
// headers() function reads process.env.QB_ACCESS_TOKEN on every call
function headers() {
  return { Authorization: `Bearer ${process.env.QB_ACCESS_TOKEN}`, ... }
}
```

**Why this matters**: If token were captured at `import` time, a just-refreshed token would be ignored. This pattern ensures refresh → process.env update → next fetch sees fresh token.

**Hardcoded values**: MINOR_VERSION = 73

---

### D. 401 Error Handling (Token Expiry)
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/qb-api.js` (lines 45-86, `fetchWithRetry`)

**What it does**: Detects 401 Unauthorized responses and provides diagnostic output for operator.

**Key logic**:
1. On `res.status === 401`:
   - Logs first 12 chars of token in use
   - Suggests manual recovery via Intuit OAuth Playground
   - Recommends `node scripts/set-tokens.js` CLI
   - **Does NOT auto-retry** — exits with code 1
2. Operator must manually re-run script (which triggers Step 1 token refresh)

**Error messages**:
```
Token refreshed. ← means refresh succeeded
  But if 401 follows, connection was revoked in Intuit
If 401 without prior refresh, token simply expired (3600s TTL)
```

**Critical pattern**: NectoMax must distinguish between:
- Token expired (auto-refresh on next run)
- Token revoked (operator intervention needed)
- Connection disconnected in Intuit portal

---

## 2. ACCOUNT RESOLUTION (Name → QBO ID Lookup + Caching)

### A. Account Ref Lookup
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/qb-api.js` (lines 195-210)

**What it does**: Query-and-cache pattern for converting account names to QBO ID references.

**QBO API endpoint**: 
- Query: `GET /v3/company/{realmId}/query?query=<SQL>&minorversion=73`

**Key logic**:
1. Check `accountRefCache` (module-level Map)
2. On miss: Query `SELECT * FROM Account WHERE Name = '<escaped_name>'`
3. If 0 results: throw error (account doesn't exist)
4. Cache: `{ value: accounts[0].Id, name: accounts[0].Name }`
5. Return ref object (value + name)

**Escaping**: Single quotes in names are escaped: `name.replace(/'/g, "\\'")` before building SQL

**Error**: Throws with message "Account not found: "{name}". Run setup-coa.js first."

**Caller pattern**:
```javascript
const ACCT = {};
const acctNames = ['Accounts Receivable (A/R)', 'Payments to deposit', ...];
for (const name of acctNames) {
  ACCT[name] = await getAccountRef(name);  // Cached on first call
}
```

**Cache scope**: Module-level, single process lifetime. Cleared on script restart.

---

### B. Account Pre-Loading (daily-sync pattern)
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 70-99)

**What it does**: Batch load all account refs needed for a sync run upfront, with fallback for optional accounts.

**Accounts loaded**:
```javascript
const acctNames = [
  'Accounts Receivable (A/R)', 'Payments to deposit',
  'Carpet Cleaning Income', 'Area Rug Cleaning Income',
  'Treatment Income', 'Product Sales Income', 'Miscellaneous Income',
  'Storage Income', 'Rug Sales Income', 'Discounts & Refunds',
  'Deferred Sales Tax', 'Fifth Third Business Checking',
  'Petty Cash (Rugs)',
];
for (const name of acctNames) {
  ACCT[name] = await getAccountRef(name);
}
```

**Soft-load pattern** (for optional accounts):
```javascript
try {
  ACCT['Petty Cash (Carpet)'] = await getAccountRef('Petty Cash (Carpet)');
} catch {
  ACCT['Petty Cash (Carpet)'] = null;
  console.warn('Account not found — fallback to Payments to deposit with warning');
}
```

**Tax account discovery** (handles QB auto-creation):
```javascript
try {
  ACCT['Sales tax to pay'] = await getAccountRef('Sales tax to pay');
} catch {
  const taxAccts = await query('Account', "AccountSubType = 'SalesTaxPayable'");
  if (taxAccts.length > 0) ACCT['Sales tax to pay'] = { value: taxAccts[0].Id, ... };
}
```

---

### C. Customer Caching
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 108-111)

**QBO API endpoint**: `GET /v3/company/{realmId}/query?query=SELECT * FROM Customer&minorversion=73`

**Key logic**:
1. Single query: fetch ALL customers (pagination if > 1000, not shown here)
2. Build lookup map: `customerCache[DisplayName] → { value: Id, name: DisplayName }`
3. Used by order loops to find customer ref by name

**Customer selection logic** (lines 151-158):
```javascript
function getCustomerRef(order) {
  if (order._type === 'rug') return customerCache['Area Rug Sales'];
  const name = (order.name || '').trim();
  if (customerCache[name]) return customerCache[name];
  for (const [key, ref] of Object.entries(customerCache)) {
    if (key.toLowerCase() === name.toLowerCase()) return ref;  // Case-insensitive fallback
  }
  return customerCache['Residential Carpet Sales'];
}
```

---

### D. Class Caching
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 102-106)

**QBO API endpoint**: `GET /v3/company/{realmId}/query?query=SELECT * FROM Class WHERE Name = '...'&minorversion=73`

**Key logic**:
```javascript
const classCache = {};
for (const name of ['Plant', 'On-Location']) {
  const cls = await query('Class', `Name = '${name}'`);
  classCache[name] = { value: cls[0].Id, name };
}
```

**Usage**: Debit/credit lines on revenue JEs include `ClassRef: cls` to track by business unit (plant vs on-location).

---

## 3. JOURNAL ENTRY CREATION (Core Revenue Pattern)

### A. WC Entry (Work Completed / Revenue Recognition)
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 249-266, carpet; lines 333-367, rug)

**What it does**: Creates a journal entry to record revenue when work is completed and an invoice is posted.

**QBO API endpoint**: `POST /v3/company/{realmId}/journalentry?minorversion=73`

**Carpet WC entry structure**:
```javascript
{
  DocNumber: formatDocNumber(nextDocNumber++),  // WS-00105
  TxnDate: date,  // 2026-03-15
  PrivateNote: `${orderId} | ${name} | On-Location | ${tag}`,  // Idempotency tag
  Line: [
    {
      Description: `${memo} | AR`,
      Amount: total,  // Full invoice amount
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Debit',
        AccountRef: ACCT['Accounts Receivable (A/R)'],
        Entity: { Type: 'Customer', EntityRef: custRef }
      }
    },
    {
      Description: `${memo} | Carpet`,
      Amount: taxable,  // Post-tax, post-discount
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Credit',
        AccountRef: ACCT['Carpet Cleaning Income'],
        ClassRef: cls  // On-Location
      }
    },
    {
      Description: `${memo} | Tax`,
      Amount: tax,
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Credit',
        AccountRef: ACCT['Deferred Sales Tax']
      }
    }
  ]
}
```

**Rug WC entry** (more complex, multi-category):
```javascript
// Lines for each revenue category: Cleaning, Treatment, Moth, Pads, Misc, Storage, Rug Sales
// Each with Amount > 0 and ClassRef: 'Plant'
// Discount line if: categoryTotal > netSales
// Tax line if: tax > 0
```

**Gate logic** (Carpet):
- WC JE only if: `Work_Completed = '1' AND total != 0`
- Skip if already exists (idempotency via PrivateNote tag)

**Gate logic** (Rug):
- WC JE if: `Invoice != 0` (no explicit Work_Completed flag)
- Handles negative invoices (credits) naturally

**Idempotency**: PrivateNote includes tag `${orderId}|WC`. Before creating, check:
```javascript
const tag = `${orderId}|WC`;
if (!alreadyExists(tag)) {  // Queries existingMemos Set
  // Create JE
}
```

**Line balance check**: Must balance exactly — floating point rounding errors cause rejection.

---

### B. PAY Entry (Payment Application / A/R Clearing)
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 268-302, carpet; lines 370-409, rug)

**What it does**: Clears Accounts Receivable when payment is collected, routing cash to either Petty Cash (if collected at plant) or Payments to Deposit (if credit card/bank).

**QBO API endpoint**: `POST /v3/company/{realmId}/journalentry?minorversion=73`

**Carpet PAY entry structure**:
```javascript
{
  DocNumber: formatDocNumber(nextDocNumber++),
  TxnDate: date,
  PrivateNote: `${memo} | ${tag}`,  // tag = '${orderId}|PAY'
  Line: [
    // Cash side (computed by routeCashPayment helper):
    {
      Description: `${memo} | Cash at plant → Petty Cash`,
      Amount: cashTotal,
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Debit',
        AccountRef: ACCT['Petty Cash (Carpet)']
      }
    },
    // OR
    {
      Description: `${memo} | Payment`,
      Amount: otherTotal,  // CC/check/echeck
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Debit',
        AccountRef: ACCT['Payments to deposit']
      }
    },
    // A/R clearing:
    {
      Description: `${memo} | AR clear`,
      Amount: total,
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Credit',
        AccountRef: ACCT['Accounts Receivable (A/R)'],
        Entity: { Type: 'Customer', EntityRef: custRef }
      }
    },
    // Deferred tax reversal (if WC had tax):
    {
      Description: `${memo} | Deferred tax`,
      Amount: tax,
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Debit',
        AccountRef: ACCT['Deferred Sales Tax']
      }
    },
    {
      Description: `${memo} | Tax to pay`,
      Amount: tax,
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Credit',
        AccountRef: ACCT['Sales tax to pay']
      }
    }
  ]
}
```

**Rug PAY entry** with refund handling (lines 385-389):
```javascript
// If invoiceAmt < 0 (credit), flip all cash-side PostingType:
if (invoiceAmt < 0) {
  for (const l of cashLines) {
    l.JournalEntryLineDetail.PostingType = 
      l.JournalEntryLineDetail.PostingType === 'Debit' ? 'Credit' : 'Debit';
  }
}
```

**Gate logic** (Carpet):
- PAY JE only if: `Balance_Due <= 0 AND total != 0`

**Gate logic** (Rug):
- PAY JE only if: `Math.abs(paidAmt) > 0 AND Math.abs(paidAmt - invoiceAmt) < 0.01` (payment matches invoice)
- Works for credits: if Paid = -$50 and Invoice = -$50, both are negative → matches

**Cash routing** (see section 4 below): Debit side is computed by `routeCashPayment()` helper, which inspects Payment_InvoiceLink records.

**Tax handling**: Two lines to reverse deferred tax from WC and recognize it as payable.

---

### C. BATCH Entry (Auth.net Deposit Reconciliation)
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 447-477)

**What it does**: Records Auth.net settled batches as deposits to Fifth Third checking account from Payments to Deposit.

**QBO API endpoint**: `POST /v3/company/{realmId}/journalentry?minorversion=73`

**BATCH entry structure**:
```javascript
{
  DocNumber: formatDocNumber(nextDocNumber++),
  TxnDate: batch.settlementDate,  // 2026-03-15
  PrivateNote: `BATCH-${batchId} | ${paymentMethod} | ${settlementDate} | ${settled.length} txns | $${netAmount.toFixed(2)}`,
  Line: [
    {
      Description: `Auth.net Batch ${batchId} | ${paymentMethod}`,
      Amount: netAmount,
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Debit',
        AccountRef: ACCT['Fifth Third Business Checking']
      }
    },
    {
      Description: `Auth.net Batch ${batchId} | ${paymentMethod}`,
      Amount: netAmount,
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Credit',
        AccountRef: ACCT['Payments to deposit']
      }
    }
  ]
}
```

**Amount calculation**:
```javascript
const settled = txns.filter(t => t.status === 'settledSuccessfully');
const refunded = txns.filter(t => t.status === 'refundSettledSuccessfully');
const netAmount = r(settled.reduce((s, t) => s + t.settleAmount, 0) - 
                    refunded.reduce((s, t) => s + t.settleAmount, 0));
```

**Idempotency**: `BATCH-${batchId}` tag in PrivateNote. Skip if already exists.

**Skip conditions**:
- Net amount <= 0 (all refunds, net zero, or error)
- Batch already processed

---

## 4. CASH ROUTING (Payment Method → Deposit Account Mapping)

### A. Cash Routing Rules
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/cash-routing.js` (lines 26-178)

**What it does**: Inspects Payment_InvoiceLink records to decide whether a payment was collected in cash (route to Petty Cash) or via credit card/check/eCheck (route to Payments to Deposit).

**QBO API endpoint**: None — this is pure FM data inspection logic.

**Input data** (Payment_InvoiceLink table from FM):
```javascript
{
  PaymentType: 'Cash' | 'Credit Card' | 'Check' | 'eCheck' | 'Adjustment' | 'NONE',
  PaymentAmount: number,  // Positive or negative
  InvoiceID: string,
  InvoiceType: 'Rug' | 'Carpet'
}
```

**Routing rules** (Cases A–F):

| Case | Condition | Action | Line Structure |
|------|-----------|--------|-----------------|
| **0** | Petty Cash ref is null | Fallback: route all to PTD | Single line, Debit PTD, warning issued |
| **A** | Pure Cash (no other types) | Debit Petty Cash | Single line, Debit Petty Cash |
| **A2** | Pure non-Cash (CC, check, eCheck) | Debit PTD | Single line, Debit PTD |
| **B** | Single payment type + negative Adjustment | Net the adjustment, route netting | Single line (or fallback if net ≤ 0) |
| **C** | Multiple payment types + negative Adjustment | Ambiguous — fallback to PTD | Single line, fallback warning |
| **D** | Small positive Adjustment (≤ $5 ceiling) | Inflation: apply to PTD bucket | Two lines if Cash + Other both > 0 |
| **E** | Large positive Adjustment (> $5) | Guardrail exceeded — fallback | Single line, fallback warning |
| **F** | Mixed +/- Adjustments | Ambiguous — fallback to PTD | Single line, fallback warning |

**Key algorithm** (lines 52-127):
1. Partition links: adjustments vs payments
2. Sum payments by type → `typeTotals` Map
3. Split adjustments: negativeAdjustmentTotal vs positiveAdjustmentTotal
4. Apply Cases F, E, C checks first (guardrails)
5. Case B: net single-type with negative adjustment
6. Case D: inflate "other" bucket with small positive adjustment
7. Extract Cash vs Other totals
8. Reconciliation check: `cash + other ≈ invoiceAmt`
9. Return: `{ lines: [...], warning: null }` or `{ lines: [...], warning: { reason, links, invoice, routed } }`

**Output**:
```javascript
{
  lines: [
    {
      Description: 'Cash at plant → Petty Cash' | 'Payment',
      Amount: number,
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: {
        PostingType: 'Debit',
        AccountRef: pettyCashRef | paymentsToDepositRef
      }
    },
    ...
  ],
  warning: {
    reason: string,
    links: Array<{type, amount}>,
    invoice: number,
    routed: number,
    // or null
  }
}
```

**Integration into PAY JE**:
```javascript
const { lines: cashLines, warning } = routeCashPayment(
  orderId,
  carpetPaymentLinks.get(orderId) || [],
  total,
  ACCT['Petty Cash (Carpet)'],
  ACCT['Payments to deposit'],
  r
);
if (warning) {
  console.warn(...formatCashRoutingWarning('daily-sync', orderId, warning, 'Carpet'));
}
for (const l of cashLines) l.Description = `${memo} | ${l.Description}`;
// Append cashLines to JE.Line array
```

---

### B. Data Fetching for Cash Routing
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 188-216)

**What it does**: Fetches Payment_InvoiceLink records once per sync run and builds lookup maps keyed by InvoiceID.

**FM OData query**:
```javascript
const filter = `CreationTimestamp ge 2026-01-01`;
const select = 'PaymentType,PaymentAmount,InvoiceID,InvoiceType,CreationTimestamp';
const orderby = 'CreationTimestamp asc';
const rows = await fetchFMOrders('Payment_InvoiceLink', { filter, select, orderby });
```

**Lookup maps**:
```javascript
const rugPaymentLinks = new Map();  // InvoiceID → [{ PaymentType, PaymentAmount }, ...]
const carpetPaymentLinks = new Map();
for (const row of rows) {
  const bucket = row.InvoiceType === 'Rug' ? rugPaymentLinks : carpetPaymentLinks;
  const key = row.InvoiceID;
  if (!bucket.has(key)) bucket.set(key, []);
  bucket.get(key).push({ PaymentType: row.PaymentType, PaymentAmount: row.PaymentAmount });
}
```

**Error handling**: On FM fetch failure, returns empty maps. Cash routing falls back gracefully.

---

## 5. DOC NUMBER GENERATION (WS-NNNNN Sequence, Self-Healing)

### A. Number Formatting and Parsing
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/doc-number.js` (lines 28-35)

**What it does**: Converts between sequence integers and WS-NNNNN formatted strings.

**Format**: `WS-` prefix + 5-digit zero-padded sequence number
- Example: 1 → `WS-00001`, 105 → `WS-00105`

**Functions**:
```javascript
export const formatDocNumber = (n) => `WS-${String(n).padStart(5, '0')}`;
export function parseWsNumber(docNumber) {
  const m = (docNumber || '').match(/^WS-(\d+)$/);
  return m ? parseInt(m[1], 10) : null;
}
```

**Non-WS numbers return null**: Allows distinguishing programmatic JEs from manual ones.

---

### B. State Persistence
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/doc-number.js` (lines 37-56)

**What it does**: Persist next sequence number to `data/sync-state.json`.

**State file structure**:
```json
{
  "lastRevenueSyncDate": "2026-04-08",
  "lastDepositSyncDate": "2026-04-08",
  "lastRun": "2026-04-09T12:47:18.059Z",
  "lastRunResults": { ... },
  "nextDocNumber": 107
}
```

**Functions**:
```javascript
export function loadStateNumber() {
  if (!existsSync(STATE_FILE)) return 1;
  const state = JSON.parse(readFileSync(STATE_FILE, 'utf8'));
  return state.nextDocNumber || 1;
}

export function saveStateNumber(nextNumber) {
  let state = {};
  if (existsSync(STATE_FILE)) {
    try { state = JSON.parse(readFileSync(STATE_FILE, 'utf8')); } catch {}
  }
  state.nextDocNumber = nextNumber;
  writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}
```

**Preservation**: Reads existing state, updates only `nextDocNumber`, preserves other fields.

---

### C. Self-Healing Against State Loss
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/doc-number.js` (lines 64-81, 92-98)

**What it does**: Provides belt-and-suspenders against state file corruption: query QBO to find the maximum WS-NNNNN in use, and take the max of (state file number, qbo max + 1).

**QBO query for max**:
```javascript
export async function queryQboMaxWsNumber() {
  let max = 0;
  let startPos = 1;
  while (true) {
    const page = await query('JournalEntry', null, { maxResults: 1000, startPosition: startPos });
    for (const je of page) {
      const n = parseWsNumber(je.DocNumber);
      if (n !== null && n > max) max = n;
    }
    if (page.length < 1000) break;
    startPos += 1000;
  }
  return max;
}
```

**Paginated**: Iterates by 1000 until all JEs are scanned.

**One-shot reservation** (used by post-rje.js and similar):
```javascript
export async function reserveNextDocNumber() {
  const stateNumber = loadStateNumber();
  const qboMax = await queryQboMaxWsNumber();
  const sequence = Math.max(stateNumber, qboMax + 1);
  saveStateNumber(sequence + 1);  // Burn number before returning
  return { docNumber: formatDocNumber(sequence), sequence };
}
```

**Burning the number**: Persists `sequence + 1` to state BEFORE returning, so if the caller crashes before posting the JE, the number is still reserved (gap tolerated, collision prevented).

---

### D. Integration into daily-sync
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 141-149)

**What it does**: Seeds nextDocNumber at script start from max of (state file, qbo scan).

```javascript
const stateNumber = state.nextDocNumber || 1;
let maxWsNumber = 0;
let page = 1;
while (true) {
  const startPos = (page - 1) * 1000 + 1;
  const sql = `SELECT Id,DocNumber,PrivateNote FROM JournalEntry STARTPOSITION ${startPos} MAXRESULTS 1000`;
  const url = `https://quickbooks.api.intuit.com/v3/company/${QB_REALM_ID}/query?query=${encodeURIComponent(sql)}&minorversion=73`;
  const res = await fetch(url, { headers: { ... } });
  const records = data.QueryResponse?.JournalEntry || [];
  records.forEach(j => {
    existingMemos.add(j.PrivateNote || '');
    const n = parseWsNumber(j.DocNumber);
    if (n !== null && n > maxWsNumber) maxWsNumber = n;
  });
  if (records.length < 1000) break;
  page++;
}
const nextDocNumber = Math.max(stateNumber, maxWsNumber + 1);
console.log(`DocNumber seed: stateNumber=${stateNumber}, qboMaxWs=${maxWsNumber}, nextDocNumber starting at ${formatDocNumber(nextDocNumber)}`);
```

**Piggyback benefit**: The pagination loop harvests existing PrivateNote memos for idempotency checking at the same time.

---

## 6. IDEMPOTENCY & STATE TRACKING

### A. PrivateNote Tagging
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 114-160, 246-266)

**What it does**: Uses PrivateNote field as a unique idempotency key and audit trail.

**Tag formats**:
- Carpet WC: `${orderId} | ${name} | On-Location | ${orderId}|WC`
- Carpet PAY: `${orderId} | ${name} | On-Location | ${orderId}|PAY`
- Rug WC: `${orderId} | ${name} | Plant | ${orderId}|WC`
- Rug PAY: `${orderId} | ${name} | Plant | ${orderId}|PAY`
- Auth.net BATCH: `BATCH-${batchId} | ${paymentMethod} | ${settlementDate} | ${settled.length} txns | $${netAmount.toFixed(2)}`

**Idempotency check**:
```javascript
const tag = `${orderId}|WC`;
if (!alreadyExists(tag)) {
  // Create JE
  existingMemos.add(tag);
}
```

**alreadyExists function**:
```javascript
function alreadyExists(tag) {
  for (const memo of existingMemos) { if (memo.includes(tag)) return true; }
  return false;
}
```

**Load from QBO**:
```javascript
const existingMemos = new Set();
// (paginated loop at start of script)
records.forEach(j => existingMemos.add(j.PrivateNote || ''));
```

**Benefit**: Survives state file loss. Can re-run script and JEs won't be created twice.

---

### B. State File Sync Dates
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 20-38, 484-494)

**What it does**: Tracks last successful sync date for each data stream (revenue, deposits).

**State structure**:
```json
{
  "lastRevenueSyncDate": "2026-04-08",
  "lastDepositSyncDate": "2026-04-08",
  "lastRun": "2026-04-09T12:47:18.059Z",
  "lastRunResults": {
    "revenue": { "created": 22, "skipped": 9, "errors": 0 },
    "deposits": { "created": 1, "skipped": 1, "errors": 0 }
  },
  "nextDocNumber": 107
}
```

**Date advancement**:
```javascript
state.lastRevenueSyncDate = toDate;
state.lastDepositSyncDate = depositTo;
state.lastRun = new Date().toISOString();
state.lastRunResults = { revenue: {...}, deposits: {...} };
state.nextDocNumber = nextDocNumber;
saveState(state);
```

**Default on missing state** (lines 22-25):
```javascript
function loadState() {
  if (existsSync(STATE_FILE)) return JSON.parse(readFileSync(STATE_FILE, 'utf8'));
  return { lastRevenueSyncDate: '2026-03-31', lastDepositSyncDate: '2026-03-31' };
}
```

**Manual date override** (lines 14-16):
```javascript
const forceFrom = process.argv.find(a => a.startsWith('--from='))?.split('=')[1];
const forceTo = process.argv.find(a => a.startsWith('--to='))?.split('=')[1];
const fromDate = forceFrom || state.lastRevenueSyncDate;
```

---

## 7. ERROR HANDLING & RETRY LOGIC

### A. fetchWithRetry Pattern
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/qb-api.js` (lines 45-86)

**What it does**: Implements exponential backoff for 429 (rate limit) and error code 610 (throttled).

**Retry strategy**:
```javascript
async function fetchWithRetry(url, options, retries = 3) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    const res = await fetch(url, options);

    // 401 Unauthorized — no retry
    if (res.status === 401) {
      console.error('401 Unauthorized from QBO.');
      console.error('Token in use:', (QB_ACCESS_TOKEN || '').slice(0, 12) + '...');
      console.error('Manual recovery: ...');
      process.exit(1);
    }

    // 429 Too Many Requests — exponential backoff
    if (res.status === 429 && attempt < retries) {
      const delay = Math.pow(2, attempt + 1) * 1000;  // 2s, 4s, 8s
      console.error(`Rate limited, retrying in ${delay / 1000}s...`);
      await new Promise(r => setTimeout(r, delay));
      continue;
    }

    const data = await res.json();

    // Error code 610 — throttled (business validation)
    if (data.Fault) {
      const err = data.Fault.Error?.[0];
      if (err?.code === '610' && attempt < retries) {
        const delay = Math.pow(2, attempt + 1) * 1000;
        console.error(`Throttled (610), retrying in ${delay / 1000}s...`);
        await new Promise(r => setTimeout(r, delay));
        continue;
      }
      return { ok: false, data, error: err };
    }

    return { ok: true, data };
  }

  return { ok: false, data: null, error: { Message: 'Max retries exceeded' } };
}
```

**Backoff formula**: `2^(attempt + 1) * 1000` ms → 2s, 4s, 8s, 16s for retries 0, 1, 2, 3.

**Non-retriable errors**:
- 401: Token invalid/expired → exit immediately
- 6240: Duplicate name → query retry (different pattern, see findOrCreate)
- Other Fault errors: return error object, caller decides

---

### B. Duplicate Handling (Error Code 6240)
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/qb-api.js` (lines 143-175, `findOrCreate`)

**What it does**: Detects race condition where another process created the entity between our query and our create.

**Logic**:
```javascript
export async function findOrCreate(entity, matchField, matchValue, body) {
  // Query for existing
  const escaped = matchValue.replace(/'/g, "\\'");
  const existing = await query(entity, `${matchField} = '${escaped}'`);

  if (existing.length > 0) {
    return { entity: existing[0], created: false };
  }

  // Create new
  const result = await create(entity, body);

  if (!result.ok) {
    // Handle duplicate name error (code 6240)
    if (result.error?.code === '6240') {
      console.error(`Duplicate detected for "${matchValue}", re-querying...`);
      const retry = await query(entity, `${matchField} = '${escaped}'`);
      if (retry.length > 0) {
        return { entity: retry[0], created: false };
      }
    }
    throw new Error(`Failed to create ${entity} "${matchValue}": ${result.error?.Detail || result.error?.Message}`);
  }

  return { entity: result.entity, created: true };
}
```

**Used by**: setup-coa.js (accounts), setup-items.js, setup-classes.js, etc.

---

### C. Order-Level Error Handling
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 221-416)

**Pattern**:
```javascript
let revenueCreated = 0, revenueSkipped = 0, revenueErrors = 0;

try {
  // Fetch orders from FM
} catch (err) {
  console.error(`FM fetch error: ${err.message}`);
  revenueErrors = /* count of failed orders */;
}

for (const o of carpetOrders) {
  // WC JE
  const result = dryRun ? { ok: true } : await create('JournalEntry', {...});
  if (result.ok) {
    revenueCreated++;
    console.log(`OK-WC ${docNum}: ...`);
  } else {
    revenueErrors++;
    console.error(`ERR-WC: ${orderId} — ${result.error?.Detail}`);
  }

  // PAY JE
  const result = dryRun ? { ok: true } : await create('JournalEntry', {...});
  if (result.ok) {
    revenueCreated++;
  } else {
    revenueErrors++;
    console.error(`ERR-PAY: ${orderId} — ${result.error?.Detail}`);
  }
}

console.log(`Revenue: Created ${revenueCreated}, Skipped ${revenueSkipped}, Errors ${revenueErrors}`);

if (totalErrors > 0) process.exit(1);
```

**On error**: Logs per-order detail, increments error counter, continues processing other orders (fail-soft).

**Exit code**: Returns 1 if any errors to signal to scheduler/cron that manual review is needed.

---

## 8. FM ODATA INTEGRATION

### A. Field Quoting & URL Construction
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/fm-odata.js` (lines 32-107)

**What it does**: Correctly builds FM OData v4 query URLs with proper field name quoting and encoding.

**Critical FM OData quirks**:
1. **Field names with spaces MUST be quoted**: `"_kp_Order ID"`, not `_kp_Order ID`
2. **Quote ALL field names unconditionally** for consistency
3. **Spaces encode as %20** via `encodeURIComponent()` (NOT as `+`)
4. **Commas between fields must remain LITERAL** (NOT encoded to %2C)
5. **Table names in URL path are NOT quoted**

**Functions**:
```javascript
export function quoteFieldsInSelect(select) {
  // "Name,City" → '"Name","City"'
  return select.split(',').map(f => f.trim())
    .filter(f => f.length > 0)
    .map(f => (f.startsWith('"') ? f : `"${f}"`))
    .join(',');
}

export function quoteFieldsInOrderby(orderby) {
  // "Name asc,City desc" → '"Name" asc,"City" desc'
  return orderby.split(',').map(clause => clause.trim())
    .filter(clause => clause.length > 0)
    .map(clause => {
      const m = clause.match(/^(.*?)(\s+(asc|desc))?$/i);
      const field = (m[1] || clause).trim();
      const direction = m[2] || '';
      const quoted = field.startsWith('"') ? field : `"${field}"`;
      return quoted + direction;
    })
    .join(',');
}

export function buildFMODataUrl({ host, db, table, filter, select, orderby, top = 10000 }) {
  const parts = [];
  if (filter) parts.push(`$filter=${encodeURIComponent(filter)}`);
  if (select) {
    const quoted = quoteFieldsInSelect(select);
    const encoded = quoted.split(',').map(encodeURIComponent).join(',');  // Rejoin with literal commas
    parts.push(`$select=${encoded}`);
  }
  if (orderby) {
    const quoted = quoteFieldsInOrderby(orderby);
    const encoded = quoted.split(',').map(encodeURIComponent).join(',');
    parts.push(`$orderby=${encoded}`);
  }
  parts.push(`$top=${top}`);
  return `https://${host}/fmi/odata/v4/${db}/${table}?${parts.join('&')}`;
}
```

---

### B. FM Record Fetching
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/fm-odata.js` (lines 116-145)

**What it does**: Fetches records from FM OData with Basic auth.

```javascript
export async function fetchFMRecords(table, { filter, select, orderby, host = 'widmers.fmrug.com', db = 'Production', top = 10000 } = {}) {
  const { FM_USER, FM_PASS } = process.env;
  if (!FM_USER || !FM_PASS) {
    throw new Error('FM_USER / FM_PASS not set in environment');
  }

  const url = buildFMODataUrl({ host, db, table, filter, select, orderby, top });

  const res = await fetch(url, {
    headers: {
      'Authorization': 'Basic ' + Buffer.from(`${FM_USER}:${FM_PASS}`).toString('base64'),
      'Accept': 'application/json',
    },
  });

  if (!res.ok) {
    const text = await res.text();
    const err = new Error(`FM OData ${res.status}: ${text.substring(0, 300)}`);
    err.url = url;
    err.status = res.status;
    throw err;
  }

  const data = await res.json();
  return data.value || [];
}
```

**Default parameters**: host = widmers.fmrug.com, db = Production, top = 10000 (FM max)

**Error handling**: Throws with descriptive message including URL (for debugging) and first 300 chars of response body.

---

### C. Integration into daily-sync
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 176-218)

**Pattern**:
```javascript
async function fetchFMOrders(table, filter, select, orderby) {
  return fetchFM(table, { filter, select, orderby });
}

// Carpet orders
const carpetFilter = `Date_of_Service ge ${fromDate} and Date_of_Service le ${toDate}`;
const carpetSelect = 'InvoiceNumber,Name,Date_of_Service,InvoiceAmtTaxable,...';
const carpetOrders = await fetchFMOrders('InHomeInvoiceHeader', carpetFilter, carpetSelect, 'Date_of_Service asc');

// Payment links
const filter = `CreationTimestamp ge 2026-01-01`;
const select = 'PaymentType,PaymentAmount,InvoiceID,InvoiceType,CreationTimestamp';
const rows = await fetchFMOrders('Payment_InvoiceLink', filter, select, orderby);
```

**Rug order fetch** (lines 307-310):
```javascript
const rugFilter = `timestamp_Create ge ${fromDate} and timestamp_Create le ${toDate}`;
const rugSelect = '_kp_Order ID,Name,timestamp_Create,Invoice,InvoiceNetSales,Tax,Paid,Cleaning,Treatment,...';
const rugOrders = await fetchFMOrders('Orders', rugFilter, rugSelect, 'timestamp_Create asc');
```

**Error handling**: Catches FM errors and logs warning, skipping that data stream but continuing with others.

---

## 9. AUTH.NET INTEGRATION (Deposit Sync)

### A. Auth.net API Wrapper
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/authnet.js` (lines 1-118)

**What it does**: Wraps Auth.net XML API with pure fetch (no SDK).

**Endpoints**:
- Production: `https://api.authorize.net/xml/v1/request.api`
- Sandbox: `https://apitest.authorize.net/xml/v1/request.api`

**Auth**: API Login ID + Transaction Key in XML body (not HTTP headers)

**Base request function**:
```javascript
async function request(requestType, body) {
  const xml = `<?xml version="1.0" encoding="utf-8"?>
<${requestType} xmlns="AnetApi/xml/v1/schema/AnetApiSchema.xsd">
  <merchantAuthentication>
    <name>${AUTHNET_API_LOGIN_ID}</name>
    <transactionKey>${AUTHNET_TRANSACTION_KEY}</transactionKey>
  </merchantAuthentication>
  ${body}
</${requestType}>`;

  const res = await fetch(API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/xml' },
    body: xml,
  });

  const text = await res.text();
  const resultCode = getVal(text, 'resultCode');

  if (resultCode !== 'Ok') {
    const errorText = getVal(text, 'text') || 'Unknown error';
    throw new Error(`Auth.net ${requestType}: ${errorText}`);
  }

  return text;
}
```

**XML helpers**:
```javascript
function getVal(xml, tag) { /* return first <tag>...</tag> value */ }
function getAll(xml, tag) { /* return all <tag>...</tag> values */ }
function getBlocks(xml, tag) { /* return all <tag>...</tag> blocks as XML */ }
```

---

### B. Settled Batches Query
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/authnet.js` (lines 64-82)

**What it does**: Fetches settled batches in a date range (max 31 days).

**Request type**: `getSettledBatchListRequest`

```javascript
export async function getSettledBatches(fromDate, toDate) {
  const xml = await request('getSettledBatchListRequest', `
    <includeStatistics>true</includeStatistics>
    <firstSettlementDate>${fromDate}T00:00:00</firstSettlementDate>
    <lastSettlementDate>${toDate}T23:59:59</lastSettlementDate>
  `);

  const batchBlocks = getBlocks(xml, 'batch');
  return batchBlocks.map(block => ({
    batchId: getVal(block, 'batchId'),
    settlementTime: getVal(block, 'settlementTimeLocal'),
    settlementDate: getVal(block, 'settlementTimeLocal')?.substring(0, 10),
    paymentMethod: getVal(block, 'paymentMethod'),  // creditCard, eCheck
    chargeAmount: parseFloat(getVal(block, 'chargeAmount')) || 0,
    chargeCount: parseInt(getVal(block, 'chargeCount')) || 0,
    refundAmount: parseFloat(getVal(block, 'refundAmount')) || 0,
    refundCount: parseInt(getVal(block, 'refundCount')) || 0,
  }));
}
```

**Integration in daily-sync** (lines 432-445):
```javascript
let batches = [];
let chunkStart = new Date(depositFrom);
const endDate = new Date(depositTo);

while (chunkStart <= endDate) {
  const chunkEnd = new Date(Math.min(chunkStart.getTime() + 30 * 86400000, endDate.getTime()));
  const from = chunkStart.toISOString().substring(0, 10);
  const to = chunkEnd.toISOString().substring(0, 10);
  const chunk = await getSettledBatches(from, to);
  batches.push(...chunk);
  chunkStart = new Date(chunkEnd.getTime() + 86400000);
}
```

**Chunking**: Splits by 30-day windows to stay within Auth.net API limits.

---

### C. Transaction List Query
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/lib/authnet.js` (lines 84-102)

**What it does**: Fetches transactions within a specific batch to calculate net settlement amount.

**Request type**: `getTransactionListRequest`

```javascript
export async function getTransactionList(batchId) {
  const xml = await request('getTransactionListRequest', `
    <batchId>${batchId}</batchId>
  `);

  const txnBlocks = getBlocks(xml, 'transaction');
  return txnBlocks.map(block => ({
    transId: getVal(block, 'transId'),
    submitTime: getVal(block, 'submitTimeLocal'),
    submitDate: getVal(block, 'submitTimeLocal')?.substring(0, 10),
    settleAmount: parseFloat(getVal(block, 'settleAmount')) || 0,
    status: getVal(block, 'transactionStatus'),
    accountType: getVal(block, 'accountType'),
    accountNumber: getVal(block, 'accountNumber'),
    firstName: getVal(block, 'firstName'),
    lastName: getVal(block, 'lastName'),
    invoiceNumber: getVal(block, 'invoiceNumber'),
  }));
}
```

**Status values**:
- `settledSuccessfully` — charge that settled
- `refundSettledSuccessfully` — refund that settled
- Other statuses (pending, failed, etc.) — excluded from deposit

---

### D. Integration into Deposit JE Creation
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 447-477)

**Pattern**:
```javascript
for (const batch of batches) {
  const batchTag = `BATCH-${batch.batchId}`;
  if (alreadyExists(batchTag)) { depositSkipped++; continue; }

  let txns = [];
  try { txns = await getTransactionList(batch.batchId); } catch (e) { /* skip */ }

  const settled = txns.filter(t => t.status === 'settledSuccessfully');
  const refunded = txns.filter(t => t.status === 'refundSettledSuccessfully');
  const netAmount = r(settled.reduce((s, t) => s + t.settleAmount, 0) - refunded.reduce((s, t) => s + t.settleAmount, 0));

  if (netAmount <= 0) { depositSkipped++; continue; }

  const memo = `${batchTag} | ${batch.paymentMethod} | ${batch.settlementDate} | ${settled.length} txns | $${netAmount.toFixed(2)}`;
  const lines = [
    { Description: `Auth.net Batch ${batch.batchId} | ${batch.paymentMethod}`, Amount: netAmount,
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: { PostingType: 'Debit', AccountRef: checkingRef } },
    { Description: `Auth.net Batch ${batch.batchId} | ${batch.paymentMethod}`, Amount: netAmount,
      DetailType: 'JournalEntryLineDetail',
      JournalEntryLineDetail: { PostingType: 'Credit', AccountRef: depositsRef } },
  ];

  const docNum = formatDocNumber(nextDocNumber++);
  const result = dryRun ? { ok: true } : await create('JournalEntry', {..., DocNumber: docNum, TxnDate: batch.settlementDate, PrivateNote: memo.substring(0, 4000), Line: lines});
  if (result.ok) { existingMemos.add(memo); depositCreated++; console.log(`OK ${docNum}: ...`); }
  else { depositErrors++; console.error(`ERR: Batch ${batch.batchId} — ${result.error?.Detail}`); }
}
```

**Gotcha**: Batch header `chargeAmount` only covers ONE card type. MUST sum actual transactions from `getTransactionList`, not rely on batch header.

---

## 10. DAILY SYNC FLOW (Orchestration)

### Complete Sync Sequence
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/daily-sync.js` (lines 1-508)

**Invocation**:
```bash
node scripts/daily-sync.js [--dry-run] [--from=YYYY-MM-DD] [--to=YYYY-MM-DD]
```

**Step 1: Token Refresh** (lines 40-66)
1. POST to Intuit token endpoint with refresh token
2. Extract new access + refresh tokens
3. Rewrite .env with new tokens (regex replace)
4. Update process.env for this run

**Step 2: FM → QB Revenue** (lines 163-416)
1. Load QB account refs (ACCT map)
2. Load QB classes (Plant, On-Location)
3. Load QB customers
4. Load existing JE tags (PrivateNote) for idempotency, harvest max WS-NNNNN
5. Seed nextDocNumber from max(state file, qbo scan)
6. Fetch Payment_InvoiceLink records → build cash routing lookup maps
7. **Carpet orders**: Fetch + iterate, create WC and PAY JEs per gate logic
8. **Rug orders**: Fetch + iterate, create WC and PAY JEs per gate logic
9. Log results (created, skipped, errors)

**Step 3: Auth.net → QB Deposits** (lines 418-482)
1. Chunk date range into 31-day windows
2. Fetch settled batches per window
3. For each batch:
   - Check idempotency (PrivateNote tag exists?)
   - Fetch transaction list
   - Sum settled − refunded = netAmount
   - Skip if netAmount <= 0
   - Create deposit JE: Dr Fifth Third, Cr Payments to deposit
   - Log results

**Step 4: Save State** (lines 484-494)
1. Advance lastRevenueSyncDate, lastDepositSyncDate to toDate
2. Update lastRun timestamp
3. Log lastRunResults (created, skipped, errors per stream)
4. Persist nextDocNumber for next run
5. Write sync-state.json

**Step 5: Summary** (lines 496-507)
1. Print totals
2. Exit with code 1 if errors > 0

**Dry-run mode** (lines 14):
- Creates no actual JEs
- Prints proposed JEs to console
- Does NOT consume DocNumbers (not reserved)
- Does NOT advance state file (no --dry-run check before save, but conditional JE creation means no state changes)

---

## 11. HARDCODED VALUES REQUIRING CONFIGURATION

### QBO-Specific
| Value | Source | Purpose | Config Strategy |
|-------|--------|---------|-----------------|
| MINOR_VERSION = 73 | qb-api.js:24 | QB API version | Env var QB_MINOR_VERSION, default 73 |
| BASE_URL (sandbox/prod) | qb-api.js:19-21 | API endpoint | Env var QB_ENVIRONMENT |
| Account names (13 required) | daily-sync.js:71-78 | Chart of accounts | Config file + env vars for each |
| Customer names (3) | daily-sync.js:151-158 | Lookup table | Config file or hardcoded |
| Class names (2) | daily-sync.js:102-106 | Rug/Carpet LOB split | Config file |
| Payment method default | daily-sync.js:74 | Petty Cash fallback for missing account | Soft error + warning |

### FM-Specific
| Value | Source | Purpose | Config Strategy |
|-------|--------|---------|-----------------|
| FM_HOST | fm-odata.js:116 | FM domain | Env var FM_HOST, default widmers.fmrug.com |
| FM_DB | fm-odata.js:116 | FM database | Env var FM_DB, default Production |
| Carpet table: InHomeInvoiceHeader | daily-sync.js:227 | Source data | Hardcoded (standard FM schema) |
| Rug table: Orders | daily-sync.js:309 | Source data | Hardcoded (standard FM schema) |
| Field names (15+ per table) | daily-sync.js:226, 308 | Column selection | Hardcoded in select statement |
| Payment link table | daily-sync.js:194 | Cash routing data | Hardcoded Payment_InvoiceLink |
| From date (pivot) | daily-sync.js:24, 189 | Start of sync window | Env var or state file |

### Auth.net-Specific
| Value | Source | Purpose | Config Strategy |
|-------|--------|---------|-----------------|
| API endpoint | authnet.js:9-11 | Auth.net server | Env var AUTHNET_ENVIRONMENT |
| Max date range (31 days) | daily-sync.js:437 | Chunking for API limits | Hardcoded constant |
| Status filter (settledSuccessfully) | daily-sync.js:454 | Transaction inclusion | Hardcoded (correct behavior) |

### Business Logic (Widmers-Specific)
| Value | Source | Purpose | Config Strategy |
|-------|--------|---------|-----------------|
| WC gate logic (Work_Completed, Balance_Due) | daily-sync.js:242-243, 268 | Order closure detection | Hardcoded per business rule |
| PAY gate logic (Paid == Invoice) | daily-sync.js:327, 371 | Payment matching | Hardcoded (standard accrual) |
| Positive adjustment ceiling ($5) | cash-routing.js:82 | Guardrail | Config constant |
| Tax account query (SalesTaxPayable) | daily-sync.js:87 | QB account discovery | Hardcoded query |

---

## 12. REVERSING JOURNAL ENTRY (One-Shot Utility)

### A. RJE Creation
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/post-rje.js` (lines 1-187)

**What it does**: Posts a full or partial reversing journal entry to correct previously-posted JEs.

**CLI usage**:
```bash
node scripts/post-rje.js --je <Id> --reason "text" [--date YYYY-MM-DD] [--partial <amount>] [--dry-run]
```

**Logic**:
1. Fetch original JE by Id
2. Calculate scale factor: 1.0 for full, or (partial / original_total) for partial
3. Build reversal lines: flip debit ↔ credit, scale amounts, describe as REVERSAL
4. Reserve next DocNumber (burns number, self-heals)
5. Create RJE with same TxnDate or override --date
6. Sanity check: Dr == Cr in reversal

**Reversal line structure**:
```javascript
{
  DetailType: 'JournalEntryLineDetail',
  Amount: original_amount * scaleFactor,
  Description: `REVERSAL JE ${originalJe.Id}${scaleFactor < 1 ? ' (partial)' : ''} — ${original_description}`,
  JournalEntryLineDetail: {
    PostingType: flipPosting(original_posting),
    AccountRef: original_account_ref,
    ClassRef: original_class_ref_if_any,
    Entity: original_entity_if_any,
  }
}
```

**Audit trail**:
```javascript
const privateNote = `REVERSAL of JE ${args.je}${kind === 'FULL' ? '' : ` (${kind})`} — ${args.reason}`;
```

---

## 13. SETUP & PROVISIONING SCRIPTS

### A. Chart of Accounts (setup-coa.js)
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/setup-coa.js` (lines 1-185)

**What it does**: Idempotently creates 50+ accounts in QB.

**Account definition structure**:
```javascript
{
  AcctNum: '1000',
  Name: 'Fifth Third Business Checking',
  AccountType: 'Bank',
  AccountSubType: 'Checking',
  Description: 'Primary operating account — Fifth Third Bank'
}
```

**Idempotency**: `findOrCreate(entity, 'Name', acct.Name, body)` — queries first, creates if missing.

**Account type normalization** (lines 118-136):
- Production QB requires spaced names: `"Cost of Goods Sold"`, `"Fixed Asset"`, `"Other Current Liability"`
- Sandbox accepts camelCase
- Map both to spaced for compatibility

**Sub-account handling** (lines 161-165):
```javascript
if (acct.SubAccount && acct.ParentName) {
  body.SubAccount = true;
  const parent = await findOrCreate('Account', 'Name', acct.ParentName, {});
  body.ParentRef = { value: parent.entity.Id, name: acct.ParentName };
}
```

---

### B. Company Settings (setup-company.js)
**Source**: `/Users/doug/Dev/widmers-qbo/scripts/setup-company.js` (lines 1-58)

**What it does**: Enables account numbers and class tracking per line.

**Endpoints**:
- GET: `/v3/company/{realmId}/preferences?minorversion=73`
- POST (update): Same endpoint with modified Preferences object

**Settings**:
```javascript
prefs.AccountingInfoPrefs.UseAccountNumbers = true;
prefs.AccountingInfoPrefs.ClassTrackingPerTxnLine = true;
```

**Critical**: Must fetch full Preferences object, modify, and send back complete object. Sparse updates cause validation conflicts.

---

### C. Classes (setup-classes.js)
**Creates**: Plant, On-Location classes for LOB tracking.

---

### D. Items (setup-items.js)
**Creates**: Service items (Cleaning, Treatment, etc.) linked to income accounts.

---

## 14. EDGE CASES & WORKAROUNDS

### A. Deferred Sales Tax Pattern
**Observation**: Widmers collects tax at invoice but recognizes liability at payment.

**Pattern** (daily-sync.js:291-296):
```javascript
// WC JE: debit AR, credit Income, credit Deferred Sales Tax
if (tax > 0) lines.push({
  Description: `${memo} | Tax`,
  Amount: tax,
  JournalEntryLineDetail: { PostingType: 'Credit', AccountRef: ACCT['Deferred Sales Tax'] }
});

// PAY JE: reverse deferred tax and recognize as payable
if (tax > 0) {
  lines.push({
    Description: `${memo} | Deferred tax`,
    Amount: tax,
    JournalEntryLineDetail: { PostingType: 'Debit', AccountRef: ACCT['Deferred Sales Tax'] }
  });
  lines.push({
    Description: `${memo} | Tax to pay`,
    Amount: tax,
    JournalEntryLineDetail: { PostingType: 'Credit', AccountRef: ACCT['Sales tax to pay'] }
  });
}
```

**Why**: Allows tax liability reconciliation to actual tax returns (which may differ from collected tax).

---

### B. Negative Invoices (Credits)
**Handling** (daily-sync.js:385-389):
```javascript
// Rug orders: if invoiceAmt < 0, flip cash-side postings
if (invoiceAmt < 0) {
  for (const l of cashLines) {
    l.JournalEntryLineDetail.PostingType = 
      l.JournalEntryLineDetail.PostingType === 'Debit' ? 'Credit' : 'Debit';
  }
}
```

**Result**: Full reversal JE with correct direction for credit refund flow.

---

### C. Petty Cash Fallback
**Handling** (daily-sync.js:91-99, cash-routing.js:129-150):
- If Petty Cash account doesn't exist yet: soft-load returns null
- In `routeCashPayment()`: if null and Cash detected, route to PTD with warning
- Warning logged to console with FM order ID, links, amounts

---

### D. "In Development" App Token Issue
**Problem**: Sandbox apps in "In Development" state return `invalid_client` on programmatic refresh.

**Workaround** (documented in connector-notes.md:88):
1. Promote app to "Production" on Intuit Developer Portal
2. OR use OAuth Playground to get fresh tokens once, then use `refresh-token.js` going forward
3. Future refresh will work programmatically

---

### E. Stale State File Recovery
**Self-healing** (doc-number.js:92-98):
- On startup, query QBO max WS-NNNNN across all JEs
- Use `max(state file nextDocNumber, qbo max + 1)`
- Survives state file deletion or corruption

---

## SUMMARY: QBO PATTERNS FOR NECTOMAX PORT

**Critical Patterns**:
1. **OAuth2**: Token refresh (3600s TTL), new refresh token on each refresh, must persist immediately
2. **Account lookup**: Query + cache pattern, with soft-load fallback for optional accounts
3. **Revenue JEs**: Two-entry accrual (WC + PAY), gated by FM flags, with tax deferral
4. **Cash routing**: Inspect Payment_InvoiceLink to split cash vs other payment methods
5. **Doc numbering**: WS-NNNNN with self-healing against state loss
6. **Idempotency**: PrivateNote tags, checked against existing JEs at sync start
7. **Deposit reconciliation**: Query Auth.net batches + transactions, calculate net, create deposit JE
8. **Error handling**: Retry 429/610, exit on 401, continue per-order on other failures
9. **FM OData**: Field quoting, comma-literal joins, %20 encoding
10. **State tracking**: Date window advancement, per-stream result logging

All patterns are production-tested in the `widmers-qbo` POC and ready for extraction.