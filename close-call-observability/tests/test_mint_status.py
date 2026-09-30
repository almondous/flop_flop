"""Synthetic fixtures only. No network calls or participant keys."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from http.client import IncompleteRead
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SPEC = importlib.util.spec_from_file_location('mint_status', Path(__file__).resolve().parents[1] / 'tools' / 'mint_status.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def did(key):
    raw = b'\xed\x01' + key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    n, result = int.from_bytes(raw, 'big'), ''
    while n:
        n, r = divmod(n, 58)
        result = m.B58[r] + result
    return 'did:key:z' + result


REF_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
REF = did(REF_KEY)
OWNER = did(Ed25519PrivateKey.from_private_bytes(bytes([100]) * 32))
OTHER = did(Ed25519PrivateKey.from_private_bytes(bytes([101]) * 32))


def enc(value):
    return json.dumps(value, separators=(',', ':')).encode()


def envelope(post, nonce=18446744073709551615):
    text = enc(post).decode()
    sig = REF_KEY.sign(f'{m.ROOM}|{nonce}|{text}'.encode())
    return {'from': REF, 'nonce': nonce, 'text': text,
            'sig': base64.urlsafe_b64encode(sig).decode().rstrip('=')}


def flow(n=12, mints=None, file='1' * 64, omitted=0, **fields):
    return dict(t='flow', n=n, file=file, mints=[] if mints is None else mints,
                omitted={'mints': omitted}, **fields)


def record(n=12, owners=None, redacted=False):
    owners = [OWNER] if owners is None else owners
    obj = {'input': {'t': 'sweep', 'n': n, 'owners': owners, 'trades': []},
           'output': {'sweep': n, 'minted': owners, 'trades': []}}
    if redacted:
        obj['input']['trades'] = [{'redacted': 'private room'}]
        obj['output']['trades'] = [{'redacted': 'private room'}]
    raw = enc(obj)
    digest = hashlib.sha256(raw).hexdigest()
    original = '1' * 64 if redacted else digest
    entry = {'n': n, 'status': 'redacted' if redacted else 'full', 'bytes': len(raw),
             'file': original, 'sha256': digest,
             'path': ('redacted/' if redacted else 'sweeps/') + original + '.json'}
    return raw, entry


class FakeGetter:
    def __init__(self, flow_bytes=b'', entries=(), records=None, flow_error=None):
        self.responses = {m.FLOW_URL: flow_error if flow_error is not None else flow_bytes,
                          m.ARCHIVE + 'index.json': enc({'sweeps': list(entries)})}
        self.responses.update(records or {})
        self.calls = []
        self.total = 0

    def get(self, url, limit):
        self.calls.append(url)
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        if len(value) > limit:
            raise ValueError('too large')
        self.total += len(value)
        return value


def run(getter, start=12, count=1):
    with tempfile.TemporaryDirectory() as root:
        result = m.check(OWNER, REF, start, count, getter, Path(root))
        files = sorted(p.name for p in Path(root).iterdir())
    return result, files


class ParsingTests(unittest.TestCase):
    def test_duplicate_json_keys(self):
        with self.assertRaises(ValueError):
            m.loads('{"n":1,"n":2}')

    def test_nonfinite_json(self):
        for value in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.loads('{"x":' + value + '}')

    def test_invalid_did(self):
        for value in ('did:web:example.org', '', None, 'did:key:z' + '1' * 47):
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.public_key(value)

    def test_signature_and_large_nonce(self):
        by, bad, conflicts = m.verified_flows(enc(envelope(flow(mints=[OWNER]))), REF)
        self.assertEqual((bad, conflicts), (0, []))
        self.assertEqual(by[12][0][0]['mints'], [OWNER])

    def test_string_nonce(self):
        _, bad, _ = m.verified_flows(enc(envelope(flow(), nonce='1790392083896')), REF)
        self.assertEqual(bad, 0)

    def test_tampered_signature(self):
        row = envelope(flow())
        row['text'] = enc(flow(mints=[OWNER])).decode()
        by, bad, _ = m.verified_flows(enc(row), REF)
        self.assertEqual((by, bad), ({}, 1))

    def test_wrong_referee_ignored(self):
        by, bad, _ = m.verified_flows(enc(envelope(flow())), OTHER)
        self.assertEqual((by, bad), ({}, 0))

    def test_wrong_season_ignored(self):
        by, bad, _ = m.verified_flows(enc(envelope(flow(season='other'))), REF)
        self.assertEqual((by, bad), ({}, 0))

    def test_boolean_sweep_and_nonce_rejected(self):
        for post, nonce in ((flow(n=True), 1), (flow(), True)):
            _, bad, _ = m.verified_flows(enc(envelope(post, nonce)), REF)
            self.assertEqual(bad, 1)

    def test_negative_omission_rejected(self):
        _, bad, _ = m.verified_flows(enc(envelope(flow(omitted=-1))), REF)
        self.assertEqual(bad, 1)

    def test_conflicting_signed_posts(self):
        raw = enc(envelope(flow(file='1' * 64))) + b'\n' + enc(envelope(flow(file='2' * 64)))
        _, bad, conflicts = m.verified_flows(raw, REF)
        self.assertEqual((bad, conflicts), (0, [12]))

    def test_republished_identical_payload_not_conflict(self):
        post = flow()
        raw = enc(envelope(post, 1)) + b'\n' + enc(envelope(post, 2))
        self.assertEqual(m.verified_flows(raw, REF)[2], [])

    def test_duplicate_index_sweeps(self):
        with self.assertRaises(ValueError):
            m.index_entries(enc({'sweeps': [{'n': 1}, {'n': 1}]}))

    def test_bad_index_schema(self):
        for obj in ([], {'sweeps': {}}, {'sweeps': [{'n': True}]}):
            with self.subTest(obj=obj), self.assertRaises(ValueError):
                m.index_entries(enc(obj))


class RecordTests(unittest.TestCase):
    def test_full_record_authenticated(self):
        raw, entry = record()
        f = flow(mints=[OWNER], file=entry['file'])
        found = m.inspect_record(raw, entry, OWNER, {12: [(f, {})]})
        self.assertEqual(found['verification'], 'referee_signature')

    def test_redacted_record_index_only_even_with_signed_original(self):
        raw, entry = record(redacted=True)
        found = m.inspect_record(raw, entry, OWNER, {12: [(flow(file=entry['file'], omitted=1), {})]})
        self.assertEqual(found['verification'], 'unsigned_index_only')

    def test_full_record_without_signed_anchor_index_only(self):
        raw, entry = record()
        self.assertEqual(m.inspect_record(raw, entry, OWNER, {})['verification'], 'unsigned_index_only')

    def test_hash_mismatch(self):
        raw, entry = record()
        with self.assertRaises(ValueError):
            m.inspect_record(raw + b' ', entry, OWNER, {})

    def test_signed_original_conflict_not_downgraded(self):
        raw, entry = record(redacted=True)
        with self.assertRaises(m.EvidenceConflict):
            m.inspect_record(raw, entry, OWNER, {12: [(flow(file='2' * 64), {})]})

    def test_unlisted_with_omissions_is_not_conflict(self):
        raw, entry = record()
        found = m.inspect_record(raw, entry, OWNER, {12: [(flow(file=entry['file'], omitted=100), {})]})
        self.assertEqual(found['verification'], 'referee_signature')

    def test_disagreement_with_complete_signed_list(self):
        raw, entry = record(redacted=True)
        with self.assertRaises(m.EvidenceConflict):
            m.inspect_record(raw, entry, OWNER, {12: [(flow(file=entry['file']), {})]})

    def test_owners_input_alone_not_mint_evidence(self):
        raw, entry = record(owners=[])
        obj = json.loads(raw)
        obj['input']['owners'] = [OWNER]
        raw = enc(obj)
        entry.update(bytes=len(raw), file=hashlib.sha256(raw).hexdigest())
        self.assertIsNone(m.inspect_record(raw, entry, OWNER, {}))

    def test_input_output_sweep_binding(self):
        raw, entry = record()
        entry['n'] = 13
        with self.assertRaises(ValueError):
            m.inspect_record(raw, entry, OWNER, {})

    def test_path_traversal_refused(self):
        _, entry = record()
        for path in ('../identity.pem', 'https://example.org/file', 'sweeps/abc.json'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                m.validate_entry({**entry, 'path': path})

    def test_oversized_and_mislabelled_records(self):
        _, entry = record()
        for update in ({'bytes': 25 * m.MIB}, {'bytes': True}, {'status': 'redacted'}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                m.validate_entry({**entry, **update})


class LookupTests(unittest.TestCase):
    def test_signed_mint_is_not_current_balance_or_request_receipt(self):
        getter = FakeGetter(enc(envelope(flow(mints=[OWNER]))))
        result, files = run(getter)
        self.assertEqual(result['mint_status'], 'minted')
        self.assertEqual(result['request_status'], 'not_checked')
        self.assertIsNone(result['current_balance'])
        self.assertNotIn('trading_authorized_by_this_check', result)
        self.assertIn('flow-export.jsonl', files)
        self.assertEqual(result['checked_archive_sweeps'], [])

    def test_reported_mint_and_archive_lag_are_separate(self):
        raw, entry = record(redacted=True)
        f = enc(envelope(flow(n=24, omitted=100)))
        getter = FakeGetter(f, [entry], {m.ARCHIVE + entry['path']: raw})
        result, files = run(getter, count=5)
        self.assertEqual(result['mint_status'], 'reported_minted')
        self.assertEqual(result['archive_lag_sweeps'], 12)
        self.assertEqual(result['not_checked_archive_sweeps'], [13, 14, 15, 16])
        self.assertIn('archive-12.json', files)

    def test_omitted_mints_do_not_prove_rejection_or_pending(self):
        result, _ = run(FakeGetter(enc(envelope(flow(omitted=9000)))))
        self.assertEqual(result['mint_status'], 'unknown')
        self.assertEqual(result['request_status'], 'not_checked')

    def test_missing_archive_not_unminted(self):
        _, entry = record(n=1)
        result, _ = run(FakeGetter(enc(envelope(flow(n=24))), [entry]))
        self.assertEqual(result['mint_status'], 'unknown')
        self.assertEqual(result['archive_lag_sweeps'], 23)
        self.assertEqual(result['missing_archive_sweeps'], [12])

    def test_empty_index_is_gap_not_complete(self):
        result, _ = run(FakeGetter())
        self.assertEqual(result['lookup_status'], 'archive_gap')

    def test_network_failure_preserves_unknown(self):
        result, _ = run(FakeGetter(flow_error=OSError('connection failed')))
        self.assertEqual(result['lookup_status'], 'incomplete')
        self.assertEqual(result['mint_status'], 'unknown')

    def test_network_failure_does_not_hide_unsigned_evidence(self):
        raw, entry = record(redacted=True)
        getter = FakeGetter(entries=[entry], records={m.ARCHIVE + entry['path']: raw}, flow_error=OSError('offline'))
        result, _ = run(getter)
        self.assertEqual(result['mint_status'], 'reported_minted')
        self.assertEqual(result['lookup_status'], 'incomplete')

    def test_stop_on_record_failure_preserves_unchecked(self):
        _, e1 = record(n=12)
        _, e2 = record(n=13)
        getter = FakeGetter(entries=[e1, e2], records={m.ARCHIVE + e1['path']: OSError('429')})
        result, _ = run(getter, count=2)
        self.assertEqual(result['not_checked_archive_sweeps'], [12, 13])
        self.assertEqual(len(getter.calls), 3)

    def test_positive_signed_conflict_is_not_success(self):
        f = enc(envelope(flow(mints=[OWNER]))) + b'\n' + enc(envelope(flow(file='2' * 64)))
        result, _ = run(FakeGetter(f))
        self.assertEqual(result['mint_status'], 'conflicting_evidence')

    def test_multiple_signed_mint_sweeps_flagged(self):
        f = enc(envelope(flow(n=12, mints=[OWNER]))) + b'\n' + enc(envelope(flow(n=13, mints=[OWNER])))
        result, _ = run(FakeGetter(f))
        self.assertEqual(result['mint_status'], 'conflicting_evidence')

    def test_archive_conflict_evidence_preserved(self):
        raw, entry = record(redacted=True)
        getter = FakeGetter(enc(envelope(flow(file='2' * 64))), [entry], {m.ARCHIVE + entry['path']: raw})
        result, files = run(getter)
        self.assertEqual(result['mint_status'], 'conflicting_evidence')
        self.assertIn('archive-12.json', files)

    def test_signed_mint_survives_index_fetch_failure(self):
        getter = FakeGetter(enc(envelope(flow(mints=[OWNER]))))
        getter.responses[m.ARCHIVE + 'index.json'] = OSError('offline')
        result, _ = run(getter)
        self.assertEqual(result['mint_status'], 'minted')
        self.assertEqual(result['lookup_status'], 'incomplete')

    def test_no_positive_in_checked_range_stays_unknown(self):
        raw, entry = record(owners=[])
        getter = FakeGetter(enc(envelope(flow(file=entry['file']))), [entry], {m.ARCHIVE + entry['path']: raw})
        result, _ = run(getter)
        self.assertEqual(result['mint_status'], 'unknown')
        self.assertEqual(result['lookup_status'], 'searched_range_no_positive_evidence')

    def test_invalid_arguments_before_network(self):
        getter = FakeGetter()
        for start, count in ((0, 1), (1, 0), (1, 97), (True, 1)):
            with self.subTest(start=start, count=count), tempfile.TemporaryDirectory() as root, self.assertRaises(ValueError):
                m.check(OWNER, REF, start, count, getter, Path(root))
        self.assertEqual(getter.calls, [])

    def test_foreign_urls_refused(self):
        getter = m.Getter()
        for url in ('http://technocore.chat/', 'file:///identity.pem', 'https://evil.test/',
                    'https://user:password@technocore.chat/', 'https://technocore.chat:8443/'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                getter.get(url, 100)

    def test_redirect_refused(self):
        with self.assertRaises(ValueError):
            m.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')


class UsabilityAndTransportTests(unittest.TestCase):
    def test_timestamp_utc_and_local_are_same_candidate(self):
        self.assertEqual(m.sweep_for_timestamp('2026-09-26T03:08:04.162798Z'), 182)
        self.assertEqual(m.sweep_for_timestamp('2026-09-26T12:08:04.162798+09:00'), 182)

    def test_boundary_is_included_as_candidate(self):
        self.assertEqual(m.sweep_for_timestamp('2026-09-26T03:10:00Z'), 182)
        self.assertEqual(m.sweep_for_timestamp('2026-09-26T03:10:00.000001Z'), 183)

    def test_opening_and_preopening_start_at_first_sweep(self):
        self.assertEqual(m.sweep_for_timestamp('2026-09-25T12:00:00Z'), 1)
        self.assertEqual(m.sweep_for_timestamp('2026-09-25T11:59:00Z'), 1)

    def test_naive_and_invalid_timestamps_rejected(self):
        for text in ('2026-09-26T03:08:04', '2026-09-26', 'not-a-time'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                m.sweep_for_timestamp(text)

    def test_out_of_range_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            m.sweep_for_timestamp('2030-01-01T00:00:00Z')

    def test_duplicate_signed_mints_rejected(self):
        by, bad, _ = m.verified_flows(enc(envelope(flow(mints=[OWNER, OWNER]))), REF)
        self.assertEqual((by, bad), ({}, 1))

    def test_truncated_flow_response_is_reported_not_raised(self):
        result, _ = run(FakeGetter(flow_error=IncompleteRead(b'partial', 100)))
        self.assertEqual(result['mint_status'], 'unknown')
        self.assertEqual(result['lookup_status'], 'incomplete')
        self.assertEqual(result['flow_verification_status'], 'unavailable')

    def test_truncated_archive_response_is_reported(self):
        _, entry = record()
        getter = FakeGetter(entries=[entry], records={m.ARCHIVE + entry['path']: IncompleteRead(b'x', 100)})
        result, _ = run(getter)
        self.assertEqual(result['lookup_status'], 'incomplete')
        self.assertEqual(result['not_checked_archive_sweeps'], [12])

    def test_no_matching_referee_posts_are_explicit(self):
        result, _ = run(FakeGetter())
        self.assertEqual(result['flow_verification_status'], 'no_matching_verified_posts')
        self.assertIsNone(result['latest_observed_signed_flow_sweep'])

    def test_unsigned_index_maximum_is_not_contiguous_coverage(self):
        _, first = record(n=1)
        _, gap = record(n=3)
        result, _ = run(FakeGetter(entries=[first, gap]))
        self.assertEqual(result['archive_latest_sweep'], 3)
        self.assertEqual(result['archive_index_contiguous_through'], 1)

    def test_signed_flow_presence_is_explicit(self):
        result, _ = run(FakeGetter(enc(envelope(flow(mints=[OWNER])))))
        self.assertEqual(result['flow_verification_status'], 'verified_posts_found')

if __name__ == '__main__':
    unittest.main()
