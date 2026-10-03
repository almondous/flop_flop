# Close-1 mint observability contribution

A read-only initial-mint checker for **any participant**, plus a separate
operator-side design proposal. This is community tooling, not a FLOP Labs release,
an upstream PR, a second ledger, or a production referee deployment.

Existing news/site files and the official contest's frozen artifacts are unchanged.
No real participant DID, referee pin, credential, registration receipt or trade is
bundled. Test signing keys are synthetic public fixtures, never participant keys.

## Run

From this directory, use Python 3.10+ and a virtual environment:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tools/mint_status.py \
  --did '<OWNER_DID>' \
  --referee '<REFEREE_DID_FROM_AUTHENTICATED_LAUNCH>' \
  --registered-at '2026-09-26T12:08:04+09:00'
```

Replace both placeholders. The timestamp is an example, not a participant default.
Alternatively pass `--from-sweep N`, but not both options. `--count` defaults to 24
and is capped at 96. Each run saves a report and public evidence in a fresh local
directory. The tool never reads private keys, signs, registers, trades or changes
bot state. Nonzero exits must **not** automatically trigger re-registration.

## What it reports

- Initial-mint evidence: signed, archive-reported, unknown, or conflicting.
- Verification strength, separately from whether an archive contains the DID.
- Publication lag, requested/checked/missing/unchecked sweeps, and retrieval errors.
- Explicit absence of matching verified referee posts and unsigned-index gaps.

`unknown` does not mean rejected, queued, or unminted. `current_balance` remains
null: a historical mint is not a current account statement. The referee identity
must be authenticated independently by the caller. An unsigned checksum is not
a referee signature, including for redacted records.

See [usage and trust boundaries](docs/mint-status.md),
[operator integration proposal](docs/registration-observability-proposal.md), and
[verification performed](VERIFICATION.md).

## Integration boundary

The production referee is maintained separately from the public challenge package.
Its source location and integration contract must be confirmed with the maintainers.
The proposal's durable inbox, idempotent mint effect, signed per-owner response and
publication outbox are **not implemented by this client**. The client does not
claim to implement #22's state-root proofs or to repair #21's unsigned archive.

日本語: 全参加者向けの読み取り専用確認ツールです。mint記録の有無、署名検証、公開遅延、通信失敗を分けて表示します。運営側の発行処理は改善仕様であり、まだ本番に反映していません。
