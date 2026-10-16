"""Check actionable transport diagnostics without exposing exception contents."""

import errno
import socket
import ssl
import unittest
from unittest.mock import patch
from urllib.error import URLError

from wiremock_benchmark_cli.api import AdminError, WireMockAdmin
from wiremock_benchmark_cli.http_errors import transport_failure
from wiremock_benchmark_cli.verify import probe


class TransportErrorsTest(unittest.TestCase):
    def test_classifies_direct_and_wrapped_errors_without_raw_messages(self):
        cases = [
            (OSError(errno.ECONNREFUSED, "SECRET"), "connection refused"),
            (OSError(errno.ECONNRESET, "SECRET"), "connection reset by peer"),
            (OSError(errno.ENETUNREACH, "SECRET"), "network unreachable"),
            (OSError(errno.EHOSTUNREACH, "SECRET"), "host unreachable"),
            (OSError(errno.EACCES, "SECRET"), "connection denied by local permissions"),
            (OSError(errno.EPIPE, "SECRET"), "connection closed (broken pipe)"),
            (socket.gaierror(-2, "SECRET"), "DNS resolution failed"),
            (TimeoutError("SECRET"), "connection/read timed out"),
            (ssl.SSLCertVerificationError(1, "SECRET"), "TLS certificate verification failed"),
            (ssl.SSLError(1, "SECRET"), "TLS connection failed"),
            (ValueError("SECRET"), "ValueError"),
        ]
        for error, expected in cases:
            for candidate in (error, URLError(error)):
                with self.subTest(expected=expected, wrapped=isinstance(candidate, URLError)):
                    self.assertEqual(transport_failure(candidate), expected)
        self.assertEqual(transport_failure(URLError("SECRET")), "unclassified transport error")

    def test_admin_and_public_probe_share_safe_connection_reason(self):
        failure = URLError(OSError(errno.ECONNREFUSED, "SECRET"))
        admin = WireMockAdmin("http://unused.test", 1)
        with patch.object(admin.opener, "open", side_effect=failure):
            with self.assertRaises(AdminError) as caught:
                admin.request("GET", "/__admin/mappings/test")
        self.assertEqual(str(caught.exception), "GET /__admin/mappings/test: connection refused")
        mapping = {"request": {"method": "POST"}, "response": {
            "status": 200, "body": "", "headers": {}, "fixedDelayMilliseconds": 0}}
        with patch("wiremock_benchmark_cli.verify.build_opener") as opener:
            opener.return_value.open.side_effect = failure
            self.assertEqual(probe("http://unused.test", mapping, 50, 1000, request_settings={"probe_body": {"type": "json", "value": {}}}),
                             (False, "probe transport failure: connection refused"))


if __name__ == "__main__":
    unittest.main()
