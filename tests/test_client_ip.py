"""Rate-limit client addresses honor X-Forwarded-For only from trusted proxies."""

import ipaddress
import tempfile
import threading
import unittest
from email.message import Message
from pathlib import Path

from backend.config import load_config
from backend.http_api.auth import SessionAuthService, resolve_client_ip
from backend.http_api.rate_limit import RateLimiter

PROXY = (ipaddress.ip_network("192.168.1.6/32"),)


class ResolveClientIpTests(unittest.TestCase):
    def test_untrusted_peer_ignores_forwarded_header(self):
        self.assertEqual(
            resolve_client_ip("192.168.1.20", ["203.0.113.9"], PROXY), "192.168.1.20"
        )

    def test_without_trusted_proxies_the_socket_peer_is_used(self):
        self.assertEqual(
            resolve_client_ip("192.168.1.6", ["203.0.113.9"], ()), "192.168.1.6"
        )

    def test_trusted_proxy_uses_the_rightmost_untrusted_hop(self):
        self.assertEqual(
            resolve_client_ip("192.168.1.6", ["203.0.113.9"], PROXY), "203.0.113.9"
        )
        # A client-supplied entry left of the real address cannot pick a bucket.
        self.assertEqual(
            resolve_client_ip("192.168.1.6", ["1.2.3.4, 203.0.113.9"], PROXY),
            "203.0.113.9",
        )
        self.assertEqual(
            resolve_client_ip("192.168.1.6", ["1.2.3.4", "203.0.113.9"], PROXY),
            "203.0.113.9",
        )

    def test_chained_trusted_proxies_are_skipped(self):
        networks = (ipaddress.ip_network("192.168.1.0/24"),)
        self.assertEqual(
            resolve_client_ip("192.168.1.6", ["203.0.113.9, 192.168.1.7"], networks),
            "203.0.113.9",
        )

    def test_missing_or_malformed_header_falls_back_to_a_known_hop(self):
        self.assertEqual(resolve_client_ip("192.168.1.6", [], PROXY), "192.168.1.6")
        self.assertEqual(
            resolve_client_ip("192.168.1.6", ["unknown"], PROXY), "192.168.1.6"
        )
        self.assertEqual(
            resolve_client_ip("192.168.1.6", ["203.0.113.9, garbage"], PROXY),
            "192.168.1.6",
        )
        self.assertEqual(
            resolve_client_ip("192.168.1.6", ["203.0.113.9", ""], PROXY),
            "192.168.1.6",
        )

    def test_hops_left_of_the_client_are_not_parsed(self):
        self.assertEqual(
            resolve_client_ip(
                "192.168.1.6", ["garbage", "1.2.3.4, 203.0.113.9"], PROXY
            ),
            "203.0.113.9",
        )

    def test_ipv4_mapped_proxy_peer_is_trusted(self):
        self.assertEqual(
            resolve_client_ip("::ffff:192.168.1.6", ["203.0.113.9"], PROXY),
            "203.0.113.9",
        )


class _Handler:
    def __init__(self, peer: str, forwarded: list[str]) -> None:
        self.client_address = (peer, 50000)
        self.headers = Message()
        for value in forwarded:
            self.headers["X-Forwarded-For"] = value


class SessionAuthClientIpTests(unittest.TestCase):
    def service(self, trusted_proxy_ips):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = load_config(
                root,
                root,
                {
                    "APP_PASSWORD": "synthetic-password",
                    "TRUSTED_PROXY_IPS": trusted_proxy_ips,
                },
            )
        return SessionAuthService(
            object(), threading.RLock(), config, True, RateLimiter()
        )

    def test_login_rate_limit_buckets_follow_the_forwarded_client(self):
        service = self.service("192.168.1.6")
        self.assertEqual(
            service.client_ip(_Handler("192.168.1.6", ["203.0.113.9"])), "203.0.113.9"
        )
        self.assertEqual(
            service.client_ip(_Handler("192.168.1.20", ["203.0.113.9"])),
            "192.168.1.20",
        )
        self.assertEqual(
            self.service("").client_ip(_Handler("192.168.1.6", ["203.0.113.9"])),
            "192.168.1.6",
        )


if __name__ == "__main__":
    unittest.main()
