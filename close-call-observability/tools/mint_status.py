#!/usr/bin/env python3
"""Read-only close-1 mint lookup for any owner; see docs/mint-status.md.

Python 3.10+; optional tool dependency: cryptography. No signing, private keys,
registration, transactions, or trading authorization. The caller supplies the
referee DID from an independently authenticated launch record.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ARCHIVE = 'https://challenges.technocore.chat/close-1/'
FLOW_URL = 'https://technocore.chat/r/d-close1-flow/export'
ROOM = 'd-close1-flow'
DID_RE = re.compile(r'did:key:z6Mk[1-9A-HJ-NP-Za-km-z]{44}')
PATH_RE = re.compile(r'(sweeps|redacted)/[0-9a-f]{64}\.json')
HEX_RE = re.compile(r'[0-9a-f]{64}')
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
MIB = 1024 * 1024
OPENING = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
SWEEP_MICROSECONDS = 300 * 1_000_000


class EvidenceConflict(ValueError):
    """Observed records disagree; never downgrade a conflict to mere absence."""


def loads(raw: bytes | str):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('duplicate JSON key')
            obj[key] = value
        return obj

    def invalid(value):
        raise ValueError('non-finite JSON number')

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def sweep_for_timestamp(value: str) -> int:
    """First scheduled sweep at or after a timezone-aware receipt timestamp.

    A boundary timestamp includes that sweep as a search candidate, not as an
    assertion about when ingestion happened. Uses close-1's published schedule.
    """
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('registration timestamp requires Z or a UTC offset')
    delta = stamp.astimezone(timezone.utc) - OPENING
    micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    n = max(1, (micros + SWEEP_MICROSECONDS - 1) // SWEEP_MICROSECONDS)
    if n > 100000:
        raise ValueError('registration timestamp is outside the supported range')
    return n


def public_key(did: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if not isinstance(did, str) or not DID_RE.fullmatch(did):
        raise ValueError('expected an Ed25519 did:key')
    number = 0
    for char in did[9:]:
        number = number * 58 + B58.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, 'big')
    if len(raw) != 34 or raw[:2] != b'\xed\x01':
        raise ValueError('wrong DID codec')
    return Ed25519PublicKey.from_public_bytes(raw[2:])


def verified_flows(raw: bytes, referee: str) -> tuple[dict, int, list[int]]:
    key = public_key(referee)
    by_sweep, bad = {}, 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = loads(line)
            if not isinstance(row, dict):
                raise ValueError('invalid export row')
            if row.get('from', row.get('did')) != referee:
                continue
            nonce, text, sig = row.get('nonce'), row.get('text'), row.get('sig')
            if type(nonce) not in (int, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,19})', str(nonce)):
                raise ValueError('invalid nonce')
            if not isinstance(text, str) or not isinstance(sig, str) or not re.fullmatch(r'[A-Za-z0-9_-]{86}', sig):
                raise ValueError('missing text/signature')
            decoded = base64.urlsafe_b64decode(sig + '==')
            if base64.urlsafe_b64encode(decoded).decode().rstrip('=') != sig:
                raise ValueError('noncanonical signature')
            key.verify(decoded, f'{ROOM}|{nonce}|{text}'.encode('utf-8'))
            post = loads(text)
            if not isinstance(post, dict) or post.get('t') != 'flow':
                continue
            # Older close-1 posts omit season; the signed room supplies that context.
            if post.get('season', 'close-1') != 'close-1':
                continue
            n = post.get('n')
            if type(n) is not int or n < 1:
                raise ValueError('invalid sweep')
            if not isinstance(post.get('file'), str) or not HEX_RE.fullmatch(post['file']):
                raise ValueError('invalid signed file hash')
            if not isinstance(post.get('mints'), list) or any(not isinstance(d, str) or not DID_RE.fullmatch(d) for d in post['mints']):
                raise ValueError('invalid signed mints list')
            if len(post['mints']) != len(set(post['mints'])):
                raise ValueError('duplicate DID in signed mints list')
            omitted = post.get('omitted', {})
            if not isinstance(omitted, dict) or type(omitted.get('mints', 0)) is not int or omitted.get('mints', 0) < 0:
                raise ValueError('invalid omitted mint count')
            by_sweep.setdefault(n, []).append((post, row))
        except (ValueError, TypeError, KeyError, OverflowError):
            bad += 1
        except Exception as exc:
            # InvalidSignature is imported here so importing this module needs no dependency.
            from cryptography.exceptions import InvalidSignature
            if not isinstance(exc, InvalidSignature):
                raise
            bad += 1
    conflicts = []
    for n, variants in by_sweep.items():
        if len({json.dumps(post, sort_keys=True, separators=(',', ':')) for post, _ in variants}) > 1:
            conflicts.append(n)
    return by_sweep, bad, sorted(conflicts)


def index_entries(raw: bytes) -> dict:
    obj = loads(raw)
    if not isinstance(obj, dict) or not isinstance(obj.get('sweeps'), list):
        raise ValueError('unexpected index schema')
    entries = {}
    for entry in obj['sweeps']:
        if not isinstance(entry, dict) or type(entry.get('n')) is not int or entry['n'] < 1:
            raise ValueError('invalid index sweep')
        if entry['n'] in entries:
            raise ValueError('duplicate index sweep')
        entries[entry['n']] = entry
    return entries


def validate_entry(entry: dict) -> str:
    path, status = entry.get('path'), entry.get('status')
    if not isinstance(path, str) or not PATH_RE.fullmatch(path):
        raise ValueError('unrecognized record path')
    if status not in ('full', 'redacted'):
        raise ValueError('unrecognized record status')
    if (status == 'full') != path.startswith('sweeps/'):
        raise ValueError('record path/status mismatch')
    if type(entry.get('bytes')) is not int or not 0 < entry['bytes'] <= 24 * MIB:
        raise ValueError('invalid/oversized record')
    original = entry.get('file')
    expected = original if status == 'full' else entry.get('sha256')
    if not isinstance(original, str) or not HEX_RE.fullmatch(original):
        raise ValueError('missing original hash')
    if not isinstance(expected, str) or not HEX_RE.fullmatch(expected):
        raise ValueError('missing served-record hash')
    return expected


def inspect_record(raw: bytes, entry: dict, owner: str, flows: dict) -> dict | None:
    expected = validate_entry(entry)
    actual = hashlib.sha256(raw).hexdigest()
    if len(raw) != entry['bytes'] or actual != expected:
        raise ValueError('record size/hash mismatch')
    n = entry['n']
    variants = flows.get(n, [])
    signed_hashes = {post['file'] for post, _ in variants}
    if signed_hashes and signed_hashes != {entry['file']}:
        raise EvidenceConflict('index original hash disagrees with signed flow')
    rec = loads(raw)
    if not isinstance(rec, dict):
        raise ValueError('invalid record')
    inp, out = rec.get('input'), rec.get('output')
    if not isinstance(inp, dict) or not isinstance(out, dict):
        raise ValueError('unexpected record structure')
    if inp.get('t') != 'sweep' or type(inp.get('n')) is not int or inp['n'] != n:
        raise ValueError('input sweep mismatch')
    if type(out.get('sweep')) is not int or out['sweep'] != n:
        raise ValueError('output sweep mismatch')
    minted = out.get('minted')
    if not isinstance(minted, list) or any(not isinstance(d, str) or not DID_RE.fullmatch(d) for d in minted):
        raise ValueError('unexpected minted list')
    if len(minted) != len(set(minted)):
        raise ValueError('duplicate minted DID')
    owners = inp.get('owners')
    if not isinstance(owners, list) or any(not isinstance(d, str) for d in owners):
        raise ValueError('unexpected owner input list')
    minted_set = set(minted)
    if not minted_set.issubset(set(owners)):
        raise ValueError('mint output has no corresponding owner input')
    for post, _ in variants:
        omitted = post.get('omitted', {}).get('mints', 0)
        if len(minted) != len(post['mints']) + omitted:
            raise EvidenceConflict('archive mint count disagrees with signed flow')
        if not set(post['mints']).issubset(minted_set):
            raise EvidenceConflict('archive and signed mint list disagree')
    if owner not in minted_set:
        return None
    authenticated = entry['status'] == 'full' and signed_hashes == {actual}
    return {'sweep': n, 'source': 'archive.output.minted',
            'verification': 'referee_signature' if authenticated else 'unsigned_index_only',
            'record_sha256': actual, 'record_url': ARCHIVE + entry['path'],
            'archive_status': entry['status']}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect refused')


class Getter:
    """Fixed HTTPS endpoints, GET only, sequential, bounded, no automatic retries."""
    def __init__(self):
        self.opener = build_opener(NoRedirect())
        self.last, self.total = 0.0, 0

    def get(self, url: str, limit: int) -> bytes:
        p = urlparse(url)
        if p.scheme != 'https' or p.hostname not in ('technocore.chat', 'challenges.technocore.chat') or p.username or p.password or p.port not in (None, 443):
            raise ValueError('URL refused')
        if self.total + limit > 192 * MIB:
            raise ValueError('download budget reached')
        time.sleep(max(0.0, self.last + 0.6 - time.monotonic()))
        self.last = time.monotonic()
        req = Request(url, method='GET', headers={'User-Agent': 'Close1MintStatus/1.0 (read-only)', 'Accept-Encoding': 'identity'})
        with self.opener.open(req, timeout=20) as response:
            if response.status != 200:
                raise ValueError(f'HTTP {response.status}')
            raw = response.read(limit + 1)
        self.total += len(raw)
        if len(raw) > limit:
            raise ValueError('response exceeds size limit')
        return raw


def finish(report: dict) -> dict:
    evidence = report['evidence']
    signed = [e for e in evidence if e['verification'] == 'referee_signature']
    if len({e['sweep'] for e in signed}) > 1:
        report['conflicts'].append('owner appears minted in multiple signed sweeps')
    relevant = set(report['requested_archive_sweeps']) | {e['sweep'] for e in evidence}
    if relevant.intersection(report['signed_conflicting_sweeps']):
        report['conflicts'].append('conflicting signed posts in relevant sweeps')
    report['mint_status'] = ('conflicting_evidence' if report['conflicts'] else
                             'minted' if signed else 'reported_minted' if evidence else 'unknown')
    report['verification'] = ('conflicting' if report['conflicts'] else
                              'referee_signature' if signed else 'unsigned_index_only' if evidence else 'none')
    latest, archived = report['latest_observed_signed_flow_sweep'], report['archive_latest_sweep']
    report['archive_lag_sweeps'] = None if latest is None or archived is None else max(0, latest - archived)
    report['lookup_status'] = ('conflict' if report['conflicts'] else 'incomplete' if report['errors'] else
                               'archive_behind_observed_flow' if report['archive_lag_sweeps'] else
                               'archive_gap' if report['missing_archive_sweeps'] else
                               'evidence_found' if evidence else 'searched_range_no_positive_evidence')
    seen = set(report['checked_archive_sweeps']) | set(report['missing_archive_sweeps'])
    report['not_checked_archive_sweeps'] = [n for n in report['requested_archive_sweeps'] if n not in seen]
    report['next_step'] = {
        'minted': 'Initial mint found. No recovery registration is indicated by this lookup. Current account state is a separate check.',
        'reported_minted': 'Archive reports an initial mint. Request a signed mint receipt to upgrade authentication; do not treat this as a missing mint.',
        'unknown': 'No positive mint evidence obtained. Do not infer rejection or queue status. Consult coverage, archive lag, and errors.',
        'conflicting_evidence': 'Preserve the evidence and ask the operator to reconcile the conflict; do not select one version silently.',
    }[report['mint_status']]
    return report


def check(owner: str, referee: str, start: int, count: int, getter, root: Path) -> dict:
    public_key(owner)
    public_key(referee)
    if type(start) is not int or type(count) is not int or not 1 <= start <= 100000 or not 1 <= count <= 96:
        raise ValueError('invalid sweep range')
    report = {'schema_version': 1, 'season': 'close-1', 'did': owner,
              'checked_at': datetime.now(timezone.utc).isoformat(), 'read_only': True,
              'referee_pin': referee, 'launch_authentication': 'caller_responsibility',
              'scope': 'initial_mint_only', 'request_status': 'not_checked', 'current_balance': None,
              'latest_observed_signed_flow_sweep': None, 'archive_latest_sweep': None,
              'flow_verification_status': 'unavailable', 'archive_index_contiguous_through': None,
              'requested_archive_sweeps': list(range(start, start + count)),
              'checked_archive_sweeps': [], 'missing_archive_sweeps': [],
              'signed_conflicting_sweeps': [], 'invalid_export_rows': 0,
              'evidence': [], 'errors': [], 'conflicts': []}
    flows = {}
    try:
        raw = getter.get(FLOW_URL, 32 * MIB)
        (root / 'flow-export.jsonl').write_bytes(raw)
        flows, bad, conflicts = verified_flows(raw, referee)
        report['invalid_export_rows'], report['signed_conflicting_sweeps'] = bad, conflicts
        report['latest_observed_signed_flow_sweep'] = max(flows, default=None)
        report['flow_verification_status'] = 'verified_posts_found' if flows else 'no_matching_verified_posts'
        if bad:
            report['errors'].append({'source': 'flow', 'error': f'{bad} invalid/unverifiable rows'})
        for n, variants in sorted(flows.items()):
            if any(owner in post['mints'] for post, _ in variants):
                report['evidence'].append({'sweep': n, 'source': 'signed_flow.mints',
                                           'verification': 'referee_signature', 'evidence_file': 'flow-export.jsonl'})
    except (OSError, HTTPException, ValueError, TypeError) as exc:
        report['errors'].append({'source': 'flow', 'error': str(exc)})
    # Even when a signed mint is found, fetch the small index to expose publication lag.
    try:
        raw = getter.get(ARCHIVE + 'index.json', 4 * MIB)
        (root / 'index.json').write_bytes(raw)
        entries = index_entries(raw)
        report['archive_latest_sweep'] = max(entries, default=None)
        contiguous = 0
        while contiguous + 1 in entries:
            contiguous += 1
        report['archive_index_contiguous_through'] = contiguous
        if not report['evidence']:
            for n in report['requested_archive_sweeps']:
                if n not in entries:
                    report['missing_archive_sweeps'].append(n)
                    continue
                entry = entries[n]
                try:
                    validate_entry(entry)
                    body = getter.get(ARCHIVE + entry['path'], entry['bytes'])
                    # Preserve bytes even when validation later finds a disagreement.
                    name = f'archive-{n}.json'
                    (root / name).write_bytes(body)
                    found = inspect_record(body, entry, owner, flows)
                    report['checked_archive_sweeps'].append(n)
                    if found:
                        found['evidence_file'] = name
                        report['evidence'].append(found)
                        break
                except EvidenceConflict as exc:
                    report['conflicts'].append(f'sweep {n}: {exc}')
                    break
                except (OSError, HTTPException, ValueError, TypeError) as exc:
                    report['errors'].append({'sweep': n, 'error': str(exc)})
                    break
    except (OSError, HTTPException, ValueError, TypeError) as exc:
        report['errors'].append({'source': 'archive_index', 'error': str(exc)})
    report['bytes_downloaded'] = getter.total
    return finish(report)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--did', required=True, help='Owner DID to look up; no private key required')
    parser.add_argument('--referee', required=True, help='Referee DID authenticated independently by the caller')
    start = parser.add_mutually_exclusive_group(required=True)
    start.add_argument('--from-sweep', type=int, help='First archive sweep to inspect')
    start.add_argument('--registered-at', help='Registration receipt timestamp with Z or UTC offset; computes the first candidate sweep')
    parser.add_argument('--count', type=int, default=24, help='Consecutive sweeps, 1 to 96 (default 24)')
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 96:
        parser.error('invalid sweep count')
    try:
        first = sweep_for_timestamp(args.registered_at) if args.registered_at else args.from_sweep
        if not 1 <= first <= 100000:
            raise ValueError('invalid first sweep')
        public_key(args.did)
        public_key(args.referee)
        root = Path(tempfile.mkdtemp(prefix='close1-mint-status-', dir=str(Path.cwd())))
        report = check(args.did, args.referee, first, args.count, Getter(), root)
        with (root / 'result.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
        print(f"Mint: {report['mint_status']} | Verification: {report['verification']}")
        print(f"Lookup: {report['lookup_status']} | Archive lag: {report['archive_lag_sweeps']} sweeps")
        print(report['next_step'])
        print(f'Report and evidence: {root / "result.json"}')
        return {'minted': 0, 'reported_minted': 3, 'unknown': 2, 'conflicting_evidence': 4}[report['mint_status']]
    except ImportError:
        print('Install cryptography in your Python environment; no network check was performed.', file=sys.stderr)
        return 2
    except (OSError, HTTPException, ValueError, TypeError) as exc:
        print(f'Check incomplete: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Cancelled. No registrations, signatures, or trades were sent.', file=sys.stderr)
        raise SystemExit(130)
