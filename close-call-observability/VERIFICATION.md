# Verification performed

## Initial PR version

Python 3.13.5, cryptography 46.0.4: 52 synthetic/offline tests passed, including
the 41 original tests plus 11 timestamp, transport and coverage cases. CLI help
also succeeded. That environment's live attempt failed at DNS resolution and
returned `unknown` / `incomplete`.

The initial code/test blobs were `524ece0905334d0bd816dbd9fb75cab68184b0fe` and
`bc5f07d6f170f4d92c26c656f9d952ba9bf7de93`. Follow-up review retrieved that exact
PR commit (`1cfdfe99fc7f4e7e479af566c64bdb48574fb0c5`), confirmed all eight file
blob hashes, and independently reran those 52 tests successfully.

## Follow-up consistency fix

The original inspector accepted an archive hit even when its total mint count
disagreed with the signed listed-plus-omitted count. It also only checked the
queried owner's input relationship and signed-list membership, so contradictions
involving another owner could be missed. These are defects in the client;
no such contradictory live record or production mint defect is claimed.

Six additional synthetic tests cover count mismatches with/without a target hit,
another signed-listed owner missing from the archive, another minted owner absent
from input, repeated input requests, and preservation of conflict/invalid-record
results through the lookup. Against the old client, the regression run produced
six failures (including two subcases). After the fix:

```text
Python 3.12.14, cryptography 46.0.0
python3 -m unittest discover -s tests -v
Ran 58 tests
OK
```

One pre-existing fixture's omitted count was corrected from 100 to 1 to match
its one minted owner. It still checks that omission alone is not a contradiction.
All tests use synthetic fixtures, mocked GETs and temporary directories.

Final tested code blob: `9e62aceb6f35298f65720d9675ecf5face24feae`.
Final tested test blob: `47695f293edd8aef6d86d34acff9f12cd2ee78ba`.

## Successful live read-only CLI checks

The follow-up environment reached the actual HTTPS flow export, archive index
and historical redacted record. Caller-supplied public owner/referee pins stayed
in local evidence directories and are not bundled in the repository.

| Observation | Initial PR client | Final client after consistency fix |
| --- | --- | --- |
| Check started (UTC) | 2026-09-30 15:04:28 | 2026-09-30 15:08:03 |
| Requested/checked archive sweep | 182 | 182 |
| `mint_status` | `reported_minted` | `reported_minted` |
| `verification` | `unsigned_index_only` | `unsigned_index_only` |
| `lookup_status` | `archive_behind_observed_flow` | `archive_behind_observed_flow` |
| Latest verified flow sweep | 1476 | 1477 |
| Maximum/consecutive index sweep | 1119 | 1119 |
| Archive lag (sweeps) | 357 | 358 |
| Downloaded bytes | 7,921,230 | 7,926,021 |
| Errors / invalid export rows | 0 / 0 | 0 / 0 |
| CLI exit code | 3 | 3 |

This is a bounded historical mint lookup. An unsigned redacted archive remains
index-only evidence even when the original unredacted hash is signed. Neither
this live check nor the synthetic tests verify current balance, every participant,
the production referee's intake/persistence, or a deployment. No registrations
or trades were sent. No CI pass or upstream package test run is claimed here.

## Content-Length transport fix (2026-10-01)

Independently checked PR head `e0f095b1f0d8842dd391b7b8e70bfa2f85d249e5`
using Python 3.12.14 and cryptography 50.0.0: the existing 58 tests passed.
Two added regressions failed against that exact source. The real Python
`http.client.HTTPResponse` parser, fed synthetic HTTP wire bytes through an
in-memory socket, silently returned a short Content-Length body when called with
`read(limit + 1)`. Empty and valid-JSONL-prefix truncations both incorrectly
reported `archive_gap` with no communication error. Existing tests injected
`IncompleteRead` directly and therefore did not exercise this transport behavior.

The reader now validates Content-Length within the existing size bound and
raises IncompleteRead on premature EOF. Chunked framing retains precedence and
its parser detects incomplete chunks. Partial received bytes count toward the
download budget. Independently verified complete signed rows from a partial flow
remain evidence, with `partial_verified_posts_found` and an explicit retrieval
error; lookup status is `incomplete`, unless an observed conflict takes precedence.
The partial export is saved. This does not certify that missing rows contain no
conflicts, nor turn an absent mint into a rejection or queue status.

Eleven added tests cover both original failures, valid-response control, signed
and archive-positive preservation, conflict precedence, pre-read size bounds,
real chunked truncation, EOF framing without Content-Length, late candidates
beyond the archive watermark, and timeout/DNS/reset/disconnect/HTTP 429/503 errors.

```text
Python 3.12.14, cryptography 50.0.0
python3 -m unittest discover -s tests -v
Ran 69 tests
OK
python3 -m compileall -q tools tests
# exit 0
python3 tools/mint_status.py --help
# exit 0
```

This review used synthetic identities and offline HTTP fixtures. It did not repeat
the earlier live participant lookup, reproduce a production disconnect, or test
the production mint service. The successful live observations above remain dated
2026-09-30 and are not claims about this revision's live execution.
