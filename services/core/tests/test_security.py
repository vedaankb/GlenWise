# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

import ipaddress

import pytest

from gleanwise.errors import FetchBlocked
from gleanwise.security.ssrf import is_public_ip, resolve_public, validate_url


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "2002:7f00:1::1",
        "ff02::1",
    ],
)
def test_private_and_reserved_ips_rejected(ip):
    assert not is_public_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_ips_allowed(ip):
    assert is_public_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://x",
        "http://user:pw@example.com/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://localhost/",
        "http://foo.localhost/",
        "http://metadata.google.internal/",
        "http://printer.local/",
        "http://169.254.169.254/latest/meta-data/",
        "http://example.com:22/",
        "http:///nohost",
        "http://100.64.1.1/",
        "http://2130706433/",  # decimal 127.0.0.1 resolves at DNS layer
    ],
)
async def test_urls_blocked(url):
    with pytest.raises(FetchBlocked):
        validate_url(url)
        # numeric-host forms only surface at resolution time
        await resolve_public(url.split("//")[1].split("/")[0].split(":")[0], 80)


async def test_allow_private_flag_is_explicit():
    assert validate_url("http://127.0.0.1:8080/", allow_private=True)
    with pytest.raises(FetchBlocked):
        await resolve_public("127.0.0.1", 80)
    assert await resolve_public("127.0.0.1", 80, allow_private=True) == ["127.0.0.1"]
