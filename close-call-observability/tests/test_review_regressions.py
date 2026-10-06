"""Transport regressions with real HTTPResponse parsing; synthetic fixtures only."""
import io
from http.client import HTTPResponse
from unittest.mock import patch
import unittest
from test_mint_status import m, run, enc, envelope, flow, record, FakeGetter, OWNER


class Socket:
    def __init__(self, raw):
        self.raw = raw

    def makefile(self, *args):
        return io.BytesIO(self.raw)


class WireOpener:
    def __init__(self, responses):
        self.responses = responses

    def open(self, req, timeout):
        body, missing_bytes = self.responses[req.full_url]
        wire = (b'HTTP/1.1 200 OK\r\nContent-Length: ' +
                str(len(body) + missing_bytes).encode() +
                b'\r\nConnection: close\r\n\r\n' + body)
        response = HTTPResponse(Socket(wire))
        response.begin()
        return response


class ReviewRegressions(unittest.TestCase):
    def getter(self, body, missing_bytes):
        getter = m.Getter()
        getter.opener = WireOpener({
            m.FLOW_URL: (body, missing_bytes),
            m.ARCHIVE + 'index.json': (enc({'sweeps': []}), 0),
        })
        return getter

    @patch.object(m.time, 'sleep')
    def test_real_http_short_content_length_must_be_reported(self, _):
        getter = self.getter(b'', 100)
        result, _ = run(getter)
        self.assertEqual(result['mint_status'], 'unknown')
        self.assertEqual(result['lookup_status'], 'incomplete')
        self.assertTrue(any(e.get('source') == 'flow' for e in result['errors']))

    @patch.object(m.time, 'sleep')
    def test_real_http_valid_jsonl_prefix_is_still_truncated(self, _):
        body = enc(envelope(flow(n=12))) + b'\n'
        result, _ = run(self.getter(body, 100))
        self.assertEqual(result['lookup_status'], 'incomplete')
        self.assertTrue(any(e.get('source') == 'flow' for e in result['errors']))

    @patch.object(m.time, 'sleep')
    def test_truncated_signed_positive_preserved_with_incomplete_lookup(self, _):
        body = enc(envelope(flow(n=12, mints=[OWNER]))) + b'\n'
        result, files = run(self.getter(body, 100))
        self.assertEqual(result['mint_status'], 'minted')
        self.assertEqual(result['lookup_status'], 'incomplete')
        self.assertEqual(result['flow_verification_status'], 'partial_verified_posts_found')
        self.assertIn('flow-export.jsonl', files)
        self.assertEqual(result['bytes_downloaded'], len(body) + len(enc({'sweeps': []})))

    @patch.object(m.time, 'sleep')
    def test_truncated_flow_does_not_erase_archive_positive(self, _):
        body, entry = record(redacted=True)
        getter = self.getter(b'', 100)
        getter.opener.responses[m.ARCHIVE + 'index.json'] = (enc({'sweeps': [entry]}), 0)
        getter.opener.responses[m.ARCHIVE + entry['path']] = (body, 0)
        result, _ = run(getter)
        self.assertEqual(result['mint_status'], 'reported_minted')
        self.assertEqual(result['lookup_status'], 'incomplete')

    @patch.object(m.time, 'sleep')
    def test_truncated_prefix_conflict_takes_precedence(self, _):
        body = (enc(envelope(flow(n=12, mints=[OWNER]))) + b'\n' +
                enc(envelope(flow(n=12, file='2' * 64))) + b'\n')
        result, _ = run(self.getter(body, 100))
        self.assertEqual(result['mint_status'], 'conflicting_evidence')
        self.assertEqual(result['lookup_status'], 'conflict')
        self.assertTrue(result['errors'])

    @patch.object(m.time, 'sleep')
    def test_content_length_over_limit_rejected_before_read(self, _):
        getter = self.getter(b'', 101)
        with self.assertRaisesRegex(ValueError, 'size limit'):
            getter.get(m.FLOW_URL, 100)
        self.assertEqual(getter.total, 0)

    @patch.object(m.time, 'sleep')
    def test_real_chunked_truncation_detected(self, _):
        body = enc(envelope(flow(n=12, mints=[OWNER]))) + b'\n'
        wire = (b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n' +
                format(len(body), 'x').encode() + b'\r\n' + body + b'\r\n')
        response = HTTPResponse(Socket(wire))
        response.begin()
        getter = self.getter(b'', 0)
        original = getter.opener.open
        getter.opener.open = lambda req, timeout: response if req.full_url == m.FLOW_URL else original(req, timeout)
        result, _ = run(getter)
        self.assertEqual(result['mint_status'], 'minted')
        self.assertEqual(result['lookup_status'], 'incomplete')

    @patch.object(m.time, 'sleep')
    def test_eof_framed_response_without_content_length_supported(self, _):
        response = HTTPResponse(Socket(b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nbody'))
        response.begin()
        getter = self.getter(b'', 0)
        getter.opener.open = lambda req, timeout: response
        self.assertEqual(getter.get(m.FLOW_URL, 100), b'body')

    @patch.object(m.time, 'sleep')
    def test_real_http_complete_content_length_control(self, _):
        body = enc(envelope(flow(n=12, mints=[OWNER]))) + b'\n'
        result, _ = run(self.getter(body, 0))
        self.assertEqual(result['mint_status'], 'minted')
        self.assertEqual(result['errors'], [])

    def test_late_candidates_beyond_archive_watermark_stay_unknown(self):
        _, entry = record(n=1119)
        result, _ = run(FakeGetter(enc(envelope(flow(n=1525))), [entry]), start=1502, count=24)
        self.assertEqual(result['mint_status'], 'unknown')
        self.assertEqual(result['lookup_status'], 'archive_behind_observed_flow')
        self.assertEqual(result['missing_archive_sweeps'], list(range(1502, 1526)))
        self.assertEqual(result['archive_lag_sweeps'], 406)
        self.assertEqual(result['request_status'], 'not_checked')

    def test_communication_error_matrix_remains_structured(self):
        from urllib.error import HTTPError, URLError
        from http.client import RemoteDisconnected, IncompleteRead
        errors = [TimeoutError('timeout'), ConnectionResetError('reset'),
                  URLError('DNS lookup failed'), RemoteDisconnected('EOF'),
                  IncompleteRead(b'prefix', 100),
                  HTTPError(m.FLOW_URL, 429, 'rate limited', {}, None),
                  HTTPError(m.FLOW_URL, 503, 'unavailable', {}, None)]
        for error in errors:
            with self.subTest(error=repr(error)):
                result, _ = run(FakeGetter(flow_error=error))
                self.assertEqual(result['mint_status'], 'unknown')
                self.assertEqual(result['lookup_status'], 'incomplete')
                self.assertTrue(result['errors'])


if __name__ == '__main__':
    unittest.main()
