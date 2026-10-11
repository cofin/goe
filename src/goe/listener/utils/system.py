# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Utility library."""

import fcntl
import os
import socket
import struct


def get_interface_ip(ifname):
    """Resolve IPv4 address for a named network interface using SIOCGIFADDR (0x8915)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(
        fcntl.ioctl(
            s.fileno(),
            0x8915,
            struct.pack("256s", bytes(ifname[:15], "utf-8")),
        )[20:24]
    )


def get_lan_ip():
    ip = socket.gethostbyname(socket.gethostname())
    if ip.startswith("127.") and os.name != "nt":
        interfaces = [
            "eth0",
            "eth1",
            "eth2",
            "wlan0",
            "wlan1",
            "wifi0",
            "ath0",
            "ath1",
            "ppp0",
        ]
        for ifname in interfaces:
            try:
                ip = get_interface_ip(ifname)
                break
            except OSError:
                pass
    return ip


def get_ip_address():
    """Get IP address of the local host via a non-blocking UDP socket."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        s.connect(("10.0.0.0", 1))
        ip_address = s.getsockname()[0]
    except Exception:
        ip_address = "127.0.0.1"
    finally:
        s.close()
    return ip_address


def get_host_name():
    """Get host name of the local host."""
    return socket.gethostbyname(socket.gethostname())
