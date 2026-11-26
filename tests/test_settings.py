import contextlib
import io
import unittest
from unittest.mock import patch

import get_info as app


class SettingsTests(unittest.TestCase):
    def test_target_normalization(self):
        self.assertEqual(app.normalize_target(" EXAMPLE.COM. "), "example.com")
        self.assertEqual(app.normalize_target("пример.рф"), "xn--e1afmkfd.xn--p1ai")
        self.assertEqual(app.normalize_target("127.0.0.1"), "127.0.0.1")

    def test_invalid_targets(self):
        for value in ("", "https://example.com", "a..com", "-a.com", "a_.com",
                      "999.1.1.1", "::1", "a\r\nHost:evil", ".", "a..", "a" * 64 + ".com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.normalize_target(value)

    def test_request_path_rejects_header_injection(self):
        for path in ("/\r\nHost:evil", "/has space", "relative", "/#fragment", "/\x7f"):
            self.assertFalse(app.valid_path(path))
        self.assertTrue(app.valid_path("/search?q=a%20b"))

    def test_prompt_retries_nan_and_out_of_range(self):
        with patch("builtins.input", side_effect=["nan", "inf", "0", "2.5"]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.ask_number("timeout", 3, float, 0.1, 60), 2.5)

    def test_socket_permissions_not_uid(self):
        with patch.object(app.socket, "socket", side_effect=PermissionError):
            self.assertFalse(app.raw_probes_available())

    def test_nonroot_can_finish_http_diagnostics(self):
        with patch.object(app, "raw_probes_available", return_value=False), \
                patch.object(app, "ask_settings", return_value=("example.com", "http", 80, "/", 1, 1)), \
                patch.object(app, "resolve_target", return_value="192.0.2.1"), \
                patch.object(app, "show_route"), \
                patch.object(app, "trace_route") as trace, \
                patch.object(app, "request_site", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(app.main(), 0)
        trace.assert_not_called()
        self.assertNotIn("HTTP → TLS", output.getvalue())


class DnsTests(unittest.TestCase):
    def test_ipv4_skips_resolver(self):
        with patch.object(app.dns.resolver, "Resolver") as resolver, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.resolve_target("192.0.2.1", 1), "192.0.2.1")
        resolver.assert_not_called()

    def test_nxdomain_is_explained(self):
        with patch.object(app.dns.resolver, "Resolver") as resolver, \
                contextlib.redirect_stdout(io.StringIO()):
            resolver.return_value.resolve.side_effect = app.dns.resolver.NXDOMAIN
            with self.assertRaisesRegex(RuntimeError, "NXDOMAIN"):
                app.resolve_target("missing.example", 1)
