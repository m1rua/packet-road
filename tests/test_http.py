import contextlib
import io
from pathlib import Path
import shutil
import socketserver
import ssl
import subprocess
import tempfile
import threading
import unittest
import sys
from unittest.mock import patch

import get_info as app


@contextlib.contextmanager
def endpoint(payload, tls_context=None, delay=0):
    requests = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            request = b""
            while b"\r\n\r\n" not in request:
                part = self.request.recv(4096)
                if not part:
                    return
                request += part
                if len(request) > 16384:
                    return
            requests.append(request)
            if delay:
                threading.Event().wait(delay)
            self.request.sendall(payload)

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(2)
            if tls_context:
                try:
                    connection = tls_context.wrap_socket(connection, server_side=True)
                except Exception:
                    connection.close()
                    raise
            return connection, address

        def handle_error(self, request, client_address):
            # A client rejecting the test certificate closes its connection.
            pass

    with Server(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield server.server_address[1], requests
        finally:
            server.shutdown()
            thread.join(timeout=3)


def diagnose(port, scheme="http", timeout=1, host="localhost"):
    with contextlib.redirect_stdout(io.StringIO()):
        return app.request_site(host, "127.0.0.1", scheme, port, "/test?q=1", timeout)


class HttpTests(unittest.TestCase):
    def test_interactive_script_end_to_end(self):
        with endpoint(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n") as (port, _):
            completed = subprocess.run(
                [sys.executable, str(Path(app.__file__))],
                input=f"127.0.0.1\nhttp\n{port}\n/\n1\n0.1\n",
                capture_output=True, text=True, timeout=15,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("получен статус 200", completed.stdout)
        self.assertNotIn("HTTP → TLS", completed.stdout)

    def test_real_http_request_and_nonstandard_host_port(self):
        with endpoint(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n") as (port, requests):
            result = diagnose(port)
        self.assertTrue(result.tcp_connected)
        self.assertFalse(result.tls_established)
        self.assertTrue(result.successful)
        self.assertIn(b"GET /test?q=1 HTTP/1.1\r\n", requests[0])
        self.assertIn(f"Host: localhost:{port}\r\n".encode(), requests[0])

    def test_informational_and_final_headers_in_same_tcp_write(self):
        payload = (
            b"HTTP/1.1 103 Early Hints\r\nLink: </style.css>; rel=preload\r\n\r\n"
            b"HTTP/1.1 100 Continue\r\n\r\n"
            b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nbody"
        )
        with endpoint(payload) as (port, _):
            result = diagnose(port)
        self.assertEqual(result.http_status, 200)
        self.assertTrue(result.successful)

    def test_http_error_is_a_response_but_not_a_success(self):
        with endpoint(b"HTTP/1.1 503 Unavailable\r\nContent-Length: 0\r\n\r\n") as (port, _):
            result = diagnose(port)
        self.assertTrue(result.received)
        self.assertFalse(result.successful)
        self.assertEqual(result.failed_stage, "HTTP")

    def test_redirect_is_reported_without_following_it(self):
        with endpoint(b"HTTP/1.1 301 Moved\r\nLocation: https://missing.invalid/\r\nContent-Length: 0\r\n\r\n") as (port, requests):
            result = diagnose(port)
        self.assertTrue(result.successful)
        self.assertEqual(len(requests), 1)

    def test_too_many_interim_responses_are_bounded(self):
        with endpoint(b"HTTP/1.1 103 Early Hints\r\n\r\n" * 11) as (port, _):
            result = diagnose(port)
        self.assertFalse(result.received)
        self.assertEqual(result.failed_stage, "HTTP")
        self.assertIn("промежуточных", result.error)

    def test_malformed_status(self):
        with endpoint(b"not an HTTP response\r\n\r\n") as (port, _):
            result = diagnose(port)
        self.assertFalse(result.received)
        self.assertEqual(result.failed_stage, "HTTP")

    def test_http_timeout_preserves_tcp_result(self):
        with endpoint(b"HTTP/1.1 200 OK\r\n\r\n", delay=0.2) as (port, _):
            result = diagnose(port, timeout=0.05)
        self.assertTrue(result.tcp_connected)
        self.assertFalse(result.received)
        self.assertEqual(result.failed_stage, "HTTP")
        self.assertIn("Таймаут", result.error)

    def test_connection_refused_is_a_tcp_failure(self):
        with patch.object(app.socket, "create_connection", side_effect=ConnectionRefusedError):
            result = diagnose(1)
        self.assertFalse(result.tcp_connected)
        self.assertEqual(result.failed_stage, "TCP")


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL executable is needed for local TLS tests")
class TlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.cert = Path(cls.directory.name) / "cert.pem"
        cls.key = Path(cls.directory.name) / "key.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(cls.key), "-out", str(cls.cert), "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.server_context.load_cert_chain(cls.cert, cls.key)

    def test_trusted_certificate_and_hostname(self):
        context = ssl.create_default_context(cafile=str(self.cert))
        with endpoint(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", self.server_context) as (port, _), \
                patch.object(app.ssl, "create_default_context", return_value=context):
            result = diagnose(port, scheme="https")
        self.assertTrue(result.tcp_connected)
        self.assertTrue(result.tls_established)
        self.assertTrue(result.successful)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_untrusted_certificate_stops_before_http(self):
        with endpoint(b"", self.server_context) as (port, requests):
            result = diagnose(port, scheme="https")
        self.assertTrue(result.tcp_connected)
        self.assertFalse(result.tls_established)
        self.assertFalse(result.received)
        self.assertEqual(result.failed_stage, "TLS")
        self.assertEqual(requests, [])

    def test_hostname_mismatch_is_not_ignored(self):
        context = ssl.create_default_context(cafile=str(self.cert))
        with endpoint(b"", self.server_context) as (port, _), \
                patch.object(app.ssl, "create_default_context", return_value=context):
            result = diagnose(port, scheme="https", host="wrong.example")
        self.assertFalse(result.tls_established)
        self.assertEqual(result.failed_stage, "TLS")
