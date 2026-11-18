# FLOP #337: reconstructed common-helper prototype v1

**This is a newly reconstructed and re-tested artifact, not recovery of the lost original files.** It implements the scope described in [the earlier comment](https://github.com/flop-labs/network/issues/337#issuecomment-6972209320) for independent review requested by sunriseblack. Byte-for-byte identity with the earlier prototype cannot be claimed.

This is an independent, unreleased compiled-JavaScript experiment against official `@flop-labs/cli@0.5.0`, not a production fix or an upstream TypeScript build.

## Reproduce

Requirements: Node.js (tested v24.22.3), npm (tested 11.9.0), Python 3 standard library, and `patch`. Copy this directory from the immutable commit linked in the issue, then:

```sh
sha256sum -c SHA256SUMS
npm ci --ignore-scripts --no-audit --no-fund
python3 rebuild.py
node test.mjs
sha256sum generated/original.mjs generated/candidate.mjs generated/cli.js
```

Dependency installation and rebuild download only public npm artifacts. `rebuild.py` pins the CLI tarball URL and its SHA-512 integrity, then verifies the extracted `dist/cli.js` SHA-256 before applying `candidate.patch`. It checks the complete modified bundle's syntax and extracts the common factory block from both versions. Only `import("@flop-labs/sdk")` is redirected to `sdk-stub.mjs`, a recording boundary with no network/client implementation. The test itself has no RPC or SDK network connection. Keyring, crypto and encrypted-keystore operations are real library calls, not mocks.

The runner uses a public, all-0x11 test seed and public fixture password, never a user's key. No signatures, funding, broadcasts, enrollment, wallet migrations or live RPC calls are performed. Temporary encrypted fixtures are deleted in finally. Never fund or reuse this seed as an identity.

## Scope

Recognizes `ed25519:<secret-URI>` and `sr25519:<secret-URI>` in common helpers via a shared loader. `createClient` uses `createWithKeypair`; `agentSignerConfig` returns a keypair; DA helpers retain their sr25519-only restriction. Empty typed URIs fail. Unprefixed defaults and encrypted-keystore types are preserved.

Unchanged: enrollment wallet generation, special gateway probe signer path, every other unreviewed command consumer, DID/account attribution policy, CLI help, `--signer-type`, full CLI argument parsing, upstream TypeScript and release behavior. Do not use this as a claim that all commands support typed URIs. The stub proves routing/identity supplied at the SDK boundary, not real SDK transaction behavior.

## Results from this reconstruction

Nine grouped checks PASS on Node v24.22.3:
1. Explicit ed25519 expected identity and SDK keypair routing.
2. Explicit sr25519 expected identity and SDK keypair routing.
3. Unprefixed legacy parity.
4. Empty typed URI rejection.
5. Required/optional DA sr25519-only policy.
6. Explicit/legacy sr25519 DA byte equality (bytes not printed).
7. Actual encrypted ed25519 keystore parity.
8. Actual encrypted sr25519 keystore parity.
9. No-signer routing parity.

The reconstructed complete bundle also passed `node --check`. The full CLI executable was not run. No claim is made that these are the original nine tests' exact bytes; they are the explicitly supplied new runner.

## Provenance and hashes

Base tarball: https://registry.npmjs.org/@flop-labs/cli/-/cli-0.5.0.tgz

SHA-512 integrity (base64):
`zFLbjNdWHgc6IGO0kqwtU57dNsX29XYDWaxhbe0DtRw4QPekRpvz0yb2m/1q6dtzfTFyGz+1RBK4ll4iDnpW3w==`

Base `dist/cli.js` SHA-256:
`c94d7d6bdfee094c401aa5accd04faf19e6d48fd925ffd934f962c2ceca1de40`

`SHA256SUMS` pins the supplied patch, runner, rebuild script, SDK stub, dependency manifest/lock, and this README. `GENERATED-SHA256SUMS` pins the regenerated helper artifacts and modified full bundle, relative to this directory. Run `sha256sum -c GENERATED-SHA256SUMS` after rebuilding.

Prepared with AI assistance. Public patches and harness are intended for review, not operational wallet use.
