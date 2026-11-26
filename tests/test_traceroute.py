import contextlib
import io
import unittest
from unittest.mock import patch

from scapy.all import ICMP, IP, TCP

import get_info as app


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.probe = IP(dst="192.0.2.1") / TCP(sport=40000, dport=443, seq=17, flags="S")

    def tcp_reply(self, **overrides):
        fields = dict(sport=443, dport=40000, seq=80, ack=18, flags="SA")
        fields.update(overrides)
        return IP(src="192.0.2.1") / TCP(**fields)

    def test_open_closed_and_unrelated_tcp(self):
        self.assertEqual(app.trace_reply_kind(self.tcp_reply(), self.probe), "open")
        self.assertEqual(app.trace_reply_kind(self.tcp_reply(flags="RA"), self.probe), "closed")
        self.assertIsNone(app.trace_reply_kind(self.tcp_reply(ack=999), self.probe))
        self.assertIsNone(app.trace_reply_kind(self.tcp_reply(dport=40001), self.probe))

    def test_icmp_quote_is_not_a_tcp_response(self):
        # Serialize and parse to reproduce Scapy's actual IPerror/TCPerror layers.
        reply = IP(bytes(IP(src="192.0.2.254") / ICMP(type=11, code=0) / self.probe))
        self.assertEqual(app.trace_reply_kind(reply, self.probe), "hop")
        next_probe = self.probe.copy()
        next_probe[TCP].seq += 1
        self.assertIsNone(app.trace_reply_kind(reply, next_probe))

    def test_unreachable_is_reported_separately(self):
        reply = IP(bytes(IP(src="192.0.2.254") / ICMP(type=3, code=13) / self.probe))
        self.assertEqual(app.trace_reply_kind(reply, self.probe), "unreachable")

    def test_ack_sequence_wraparound(self):
        self.probe[TCP].seq = 2**32 - 1
        self.assertEqual(app.trace_reply_kind(self.tcp_reply(ack=0), self.probe), "open")

    def test_synack_closes_probe_and_ends_trace(self):
        def answer(probe, **kwargs):
            return IP(src=probe.dst) / TCP(
                sport=probe[TCP].dport, dport=probe[TCP].sport,
                flags="SA", ack=(probe[TCP].seq + 1) % 2**32,
            )
        with patch.object(app, "sr1", side_effect=answer) as receive, \
                patch.object(app, "send") as send, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(app.trace_route("192.0.2.1", 443, 5, 1))
        self.assertEqual(receive.call_count, 1)
        rst = send.call_args.args[0]
        self.assertEqual(str(rst[TCP].flags), "R")

    def test_timeout_is_not_called_a_site_failure(self):
        with patch.object(app, "sr1", return_value=None) as receive, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(app.trace_route("192.0.2.1", 443, 2, 1))
        self.assertEqual(receive.call_count, 2)
        self.assertIn("не означает, что сайт недоступен", output.getvalue())
