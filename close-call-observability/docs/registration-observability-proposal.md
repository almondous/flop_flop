# Proposal: durable registration tracking and verifiable per-owner mint status

**Design proposal, not deployed functionality.** Endpoint names and response
shapes below are proposed. Do not call them as if they already existed.
The production referee/ingestion implementation is maintained separately from
the public rules/fold package. Integration must occur in the operator's service;
this document does not claim to patch that service or its database.

Related existing issues: #6/#10 (truncated flow lists), #21 (redacted-record
signatures), #22 (per-owner state proofs), #24/#26/#27/#28 (registration tracing),
#15/#25 (archive publication lag). This connects those gaps without assuming they
share a single ingestion bug. A saved owner message is not a failed mint merely
because a participant cannot find it in a compact summary.

## 1. Model the request and allocation separately

A request is identified by `(season, room, seq)` and a digest of its verified
signed envelope. An allocation is identified by `(season, owner DID)`.

Request dispositions:

| Disposition | Required evidence |
| --- | --- |
| `stored_in_transport` | Exact transport receipt; does not promise referee ingestion. |
| `queued` | Durable referee inbox entry has committed. |
| `processing` | A worker has a bounded, renewable lease on a durable entry. |
| `applied` | Authoritative allocation and result committed together. |
| `duplicate` | Allocation already exists; return the original mint sweep, not a new credit. |
| `rejected` | A terminal validation/rule reason for this exact request; include a stable reason code. |
| `gap_detected` | Source interval could not be ingested; explicit loss/recovery state. |
| `unknown` | No authoritative answer available, including outage or unindexed legacy input. |

Allocation states are independent: `minted`, `not_minted_as_of`, or `unknown`.
Only an authoritative complete ledger lookup may return `not_minted_as_of`, and
it must state the sweep and publication time. An archive search cannot produce
that negative state. A rejected duplicate request must not mark a previously
minted account invalid. A transport timeout is ambiguous, not a terminal rejection.

Do not show `queued` just because the chat server returned HTTP 200. Preserve the
existing chat API contract. Either the consumer issues a separate queue receipt
once it commits the inbox entry, or an additive registration gateway acknowledges
queuing only after durable handoff. Do not silently reinterpret historical HTTP
receipts as queue guarantees.

## 2. Durable handoff and once-only allocation effects

A transport integration must retain a verified registration until the consumer
has durably accepted it, rather than relying solely on a busy room's rolling
history. Persist the source envelope/fingerprint and a monotonic room cursor.
Advance the ingested cursor only in the same transaction as inbox persistence.
Store separate ingested and applied checkpoints; catching up on reading must not
be confused with applying allocations.

Use at-least-once delivery with an idempotent effect, not an unsupported claim of
exactly-once network delivery. Adapt this outline to the real authoritative fold
checkpoint or ledger store; do not introduce a competing balance database:

```text
BEGIN authoritative transaction
  lock/claim durable request (lease/version checked)
  validate verified signer == requested owner, season, timing and rule eligibility
  look up authoritative allocation using UNIQUE(season, owner)
  if allocation exists:
      record this request as duplicate, referencing original mint
  else:
      apply the existing fold's initial mint once
      persist allocation, resulting ledger checkpoint and applied request result
  persist publication-outbox event in this same transaction
COMMIT
```

If the service stores append-only sweep events instead of mutable account rows,
use its existing single-writer/transactional checkpoint boundary and idempotent
event IDs. The uniqueness and recovery guarantees must cover the *actual ledger*,
not only a cache or the public lookup database.

A worker crash before commit must leave no credit. A crash after commit but
before publication must leave a retryable outbox event, never a reason to mint
again. A stale processing lease can be reclaimed. Publishing and signing are
retryable; failure there does not undo or repeat an allocation.

Replay a retained source interval after an export failure. Do not silently jump
to the newest messages and mark the missing interval consumed. If data is truly
unavailable, persist a gap with room, inclusive sequence bounds and reason, expose
it in the status surface, and retain the gap until explicitly reconciled.

Validate identity before any owner-required filter for room/trade messages: a new
owner cannot already be in the owner table. Whether the live implementation has
such a filter bug is unconfirmed; this is a regression requirement, not a diagnosis.

Exact-envelope retries can return their existing receipt. A genuinely new signed
request still obeys transport nonce rules. Support must distinguish the transport's
replay rejection from the allocation's idempotent duplicate success.

## 3. A small signed receipt, independent of large/redacted trade archives

Proposed public, read-only lookup:

```text
GET /close-1/owners/{did}/registration
GET /close-1/registrations/{room}/{seq}
```

The public response exposes initial allocation and request disposition only, not
private-room trades or an owner's confidential account history. An example payload
(shape only, no real participant or signature):

```json
{
  "schema": "close-call-owner-status-v1",
  "season": "close-1",
  "owner": "<queried owner DID>",
  "referee": "<authenticated referee DID>",
  "allocation": {
    "state": "minted",
    "amount": "10000",
    "mint_sweep": "182"
  },
  "request": {
    "room": "close1",
    "seq": "<queried sequence>",
    "envelope_sha256": "<exact verified envelope digest>",
    "state": "applied",
    "reason": null
  },
  "as_of_sweep": "<authoritative checkpoint>",
  "issued_at": "<UTC timestamp>",
  "revision": "<monotonic publication revision>"
}
```

No request query should default to another same-DID request. For owner-only
lookups, omit the request or explicitly label it as the last processed request.
All DIDs, season, outcome, amount, request binding, sweep and freshness fields must
be inside the signed payload. Use decimal strings for sequences/amounts to avoid
cross-language integer/decimal rounding.

A simple transport envelope can carry `payload_b64u`, `signature_b64u` and `signer`.
Sign the exact decoded payload bytes with an unambiguous domain separator:
`b"close-call-owner-status:v1\x00" + payload_bytes`. Verify those original bytes,
not a reserialized JSON value. Reject duplicate keys, noncanonical encodings and
unexpected schema values. Require the signer and payload referee to match an
independently authenticated launch pin. Document key rotation explicitly.

An old mint receipt proves an historical mint, not current balance or liveness.
Clients display the signed `as_of_sweep` and `issued_at` and compare them with an
independent recent signed checkpoint. For an interactive freshness requirement,
accept a bounded random client challenge and include it in the freshly signed
response; reject a response that fails to echo it. Static snapshots must not be
labelled real-time. Signed statements authenticate the operator; they do not prove
global consistency or prevent an operator's equivocation. #22's committed state
proofs remain a stronger separate facility for current account state.

Serve indexed lookups, not a multi-gigabyte replay for every owner. A database
index on `(season, DID)` suffices initially. An alternative is immutable mint-only
files with hash-sharded DID indexes and a signed manifest. Do not expose private
trades to make mint records verifiable. Rate-limit abusive queries without making
legitimate users generate new DIDs or sign trades merely to check eligibility.

## 4. Make archive publication a monitored part of the pipeline

Publish a new record first, verify the served bytes, then atomically advertise it
in the public manifest. Sign a manifest that binds season, revision, contiguous
coverage, every sweep number, original `file`, served `sha256`, size and path. A
second *unsigned* checksum does not close #21. Avoid exposing a new index entry
before its target exists. On failure keep the last good manifest and retry the
outbox item without reminting.

Expose operational status separately from owner results:

- observed transport head vs durable ingestion cursor, per room;
- oldest unprocessed registration, queue depth and expired processing leases;
- authoritative applied sweep vs contiguous published sweep;
- unapplied source gaps, outbox failures and last successful publication time.

Document a target publication delay and alert when exceeded (for example, a
proposed target of two scheduled sweeps; not a claim about the current service).
A stalled publisher must visibly say "mint lookup data is delayed", not leave
every participant with the impression that their registration failed.

## 5. Operator acceptance tests (not yet run against the private service)

| Test | Required outcome |
| --- | --- |
| Many owner messages exceed compact-flow length | Every DID remains directly queryable; omission has no effect on allocation or lookup. |
| Same owner concurrently submitted on two workers | One allocation; other valid request returns original mint as duplicate. |
| Replay after process restart | Same original amount/sweep; no second credit. |
| Crash between ledger mutation and receipt persistence | Entire authoritative transaction rolls back or both are committed. |
| Crash after commit, before public response | Outbox retry publishes existing result; no second mint. |
| Chat/export timeout | No silent cursor advance over unavailable messages; retained input is retried or a gap is published. |
| New owner's otherwise valid registration | Reaches the registration path before existing-owner-only trade/room filters. |
| Wrong signature, wrong season, signer/key mismatch | Exact request gets explicit reason; no mutation of another owner's state. |
| Rejected new request after an earlier valid mint | Request is rejected; allocation remains minted with original receipt. |
| Redacted private trades | Initial mint remains verifiable without disclosing trades. |
| Index signature, owner, amount or sweep tampered | Client rejects the receipt/manifest. |
| Replay an old status against a freshness challenge | Challenge/revision/as-of checks prevent presentation as a fresh result. |
| Archive publication failure or out-of-order entries | Report lag/gaps; do not claim contiguous freshness from a maximum alone. |
| Registration at the lock boundary | Existing frozen timing and sweep semantics remain unchanged. |

## Rollout boundaries

Start with the additive read-only lookup and publication pipeline. Backfill the
mint index from authoritative historical ledger records, never by allocating a
second time. Historical outcomes and timing must not be silently rewritten.
Deduplication, eligibility, fee, lock and allocation rules remain those in the
frozen contest. Any proposed change of contest semantics requires an explicit
operator decision and versioned/announced rollout, rather than a stealth patch.

The included client tests validate public-evidence handling only. They do not
claim that the queue/transaction/operator tests above have already passed. Access
to the actual referee ingestion and persistence code is needed to implement and
validate those changes against the real service.
