# Initial-mint lookup for any close-1 owner

This is a contributor tool, not a production referee change or an official
FLOP Labs release. It is designed to live outside the frozen package manifest.
No frozen rules, fold, configuration, example vectors or manifest are changed.

## Run

Python 3.10 or newer, with `cryptography` installed in the chosen environment:

```sh
python tools/mint_status.py \
  --did '<OWNER_DID>' \
  --referee '<REFEREE_DID_FROM_AUTHENTICATED_LAUNCH>' \
  --from-sweep 182 \
  --count 24
```

Replace both placeholders. There is deliberately no default participant or
referee key. The example sweep is only an example. Instead of calculating it, pass a
recorded server receipt timestamp (never both options):

```sh
python tools/mint_status.py \
  --did '<OWNER_DID>' \
  --referee '<REFEREE_DID_FROM_AUTHENTICATED_LAUNCH>' \
  --registered-at '2026-09-26T12:08:04+09:00'
```

This searches from sweep 182. A timezone is required. A receipt exactly on a
sweep boundary includes that sweep as a candidate; it does not assert ingestion
timing. Delayed ingestion can apply the registration later. The default count is 24 and the maximum is 96. A targeted lookup is not a
complete season replay. The tool only reads the existing public endpoints:

- `https://technocore.chat/r/d-close1-flow/export`
- `https://challenges.technocore.chat/close-1/index.json`
- the index's validated `sweeps/<hash>.json` or `redacted/<hash>.json` paths

Requests are sequential GETs, at most approximately 1.67/s, without automatic
retries, redirects, credentials or cookies. Each response has a size limit; the
run has a 192 MiB conservative download budget. The tool stops an archive scan
on a retrieval or validation error rather than hammering the service. It saves
reports and public evidence in a newly created directory in the current working
directory. It never loads private keys, signs, submits a registration or trade,
or changes any agent state.

## Three independent questions, not one success flag

1. `mint_status`: is there positive initial-mint evidence for this owner?
2. `verification`: which trust chain, if any, authenticates that evidence?
3. `lookup_status`: was retrieval incomplete, stale relative to observed signed
   flows, or conflicting?

| mint_status | Meaning |
| --- | --- |
| `minted` | A flow mint entry or full archive mint record verifies against the caller-supplied referee key. |
| `reported_minted` | A public archive record contains `output.minted`, but its checksum and size only match an unsigned index. Neither its author nor its contents are authenticated by a referee signature. |
| `unknown` | No positive evidence was obtained. This is NOT a negative mint proof, a queue status, or a rejection. |
| `conflicting_evidence` | Relevant signed posts or archive/flow assertions disagree. Preserve and reconcile, rather than selecting one silently. |

`request_status` remains `not_checked`: the existing public data cannot always
say whether a particular registration was received, queued, duplicated or
rejected. A successful HTTP POST receipt is not a mint receipt.

`current_balance` is always `null` and `scope` is `initial_mint_only`. No initial
mint proof certifies current cash, positions, fees, or outstanding commitments.
This tool deliberately emits no `trading_authorized` flag and is not a trading
risk gate. Exit codes describe evidence only: 0 = signed mint evidence,
3 = index-only mint evidence, 2 = no positive evidence/check incomplete,
4 = conflicting evidence. Do not automatically re-register on a nonzero exit.

## Publication lag and coverage

The report exposes both `latest_observed_signed_flow_sweep` and
`archive_latest_sweep`, plus their nonnegative difference in `archive_lag_sweeps`.
The first is only the latest verified post returned to this request, not proof
that the live referee is current. The second is the maximum sweep in an unsigned
index, not a signed coverage promise. Neither authenticates archive completeness. `archive_index_contiguous_through`
is the last consecutively indexed sweep starting at 1; it is also only an unsigned
index observation. This is deliberately separate from the maximum entry number.
`flow_verification_status` distinguishes an unavailable export, an export with no
matching verified posts, and one containing verified posts.

Requested, checked, missing and not-checked archive sweeps are separate lists.
After a positive hit, the tool stops fetching more archive records and reports
that later sweeps were not checked. An export omission, archive gap, stale index,
network failure or empty result must never be translated into `not_owner`.
The freshness warning does not erase a valid historical mint receipt.

## Trust and conflicts

The caller must independently authenticate the referee pin. A valid Ed25519
signature establishes a statement by that key, not that the key is the official
referee or that a malicious referee could not equivocate. This tool does not
bootstrap trust from a self-signed archive or from its own bundled key.

The signature verifies the original `room|nonce|text` bytes. Integers larger than
JavaScript's safe integer range stay exact in Python. Duplicate JSON keys,
noncanonical signatures, malformed fields and contradictory signed variants
are rejected or flagged. Re-publications of an identical signed payload are not
conflicts. Evidence is retained for independent review.

Before accepting an archive hit or recording a checked absence, the client
checks the whole mint list: each minted owner must be in the sweep input, the
mint count must equal the signed listed-plus-omitted count, and every signed
listed owner must appear in the archive. These checks also cover other owners
in that sweep. Repeated owner requests in the input are permitted; repeated
allocations in the output are not. Structural failures leave the lookup
incomplete, while disagreements with signed assertions report a conflict.

A full record is authenticated only when its exact-byte SHA-256 matches the
signed flow's `file`. For a redacted record, a checksum in an unsigned index is
not a signature, even when the original unredacted hash is signed. Adding another
unsigned checksum would not solve this. The operator must sign the served bytes'
hash or a manifest that contains it. See the separate proposal.

## Tests and verification boundary

```sh
python -m unittest discover -s tests -v
```

The tests use synthetic Ed25519 keys, mock GET responses and temporary output
directories. No participant identifiers, private keys, accounts or requests are
included. The review log records 52 passing tests, including timestamp boundaries, duplicate
signed mint entries, sparse indexes and truncated HTTP responses. Follow-up review
adds six regression tests for mint-count/list disagreements, invalid owner input
relationships, preserving conflict evidence and repeated owner requests; all 58
tests pass. These tests are of this
standalone tool, not of the upstream repository or the production referee.

The initial preparation environment could not resolve the public endpoints.
Follow-up checks on 2026-09-30 UTC successfully executed the CLI against the
real flow export, index and a redacted archive record, including after the
consistency fix. The result distinguished an archive-reported mint from signature
authentication and detected the archive publication lag. See `../VERIFICATION.md`
for exact observations. This verifies a bounded historical lookup, not every
participant, current account state, or the production ingestion/mint service.

## Sources reviewed

- Official package: https://github.com/flop-labs/technocore-close-call-challenge
- Source tree at review: `0ae6b063107b77e3a6cb794186fdd341a947e5e1`
- `docs/close-1-referee.md` (omitted vs missed, archive/redaction)
- `close_call_fold.py` (`input.owners` vs `output.minted`)
- Issues #21 (redacted authentication), #22 (per-owner proofs), #25 (publication lag)
- Existing public verifier's archive-schema documentation:
  https://github.com/lastbubble2035/tca/blob/main/verify/README.md

This tool generalizes the previous participant-specific checker; it is not a
fork of the other public verifier and does not duplicate its full-account replay.
