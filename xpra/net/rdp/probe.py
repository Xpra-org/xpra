# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
A minimal RDP client probe: it performs the X.224 negotiation against an RDP
server and reports which security protocols the server offers (or why it
refused). It does not establish an RDP session.
"""

import sys
import socket

from xpra.net.constants import DEFAULT_PORTS
from xpra.net.rdp.const import SecurityProtocol, RDPNeg, RDPNegFailure, protocols_str
from xpra.net.rdp.protocol import (
    build_connection_request, parse_tpkt, parse_x224_connection_confirm,
    NegotiationResponse,
)

DEFAULT_RDP_PORT = DEFAULT_PORTS.get("rdp", 3389)
MAX_RESPONSE_SIZE = 4096

# protocols we advertise when probing (RDP is implicit / 0):
PROBE_PROTOCOLS = SecurityProtocol.SSL | SecurityProtocol.HYBRID | SecurityProtocol.HYBRID_EX


def rdp_probe(host: str, port: int = DEFAULT_RDP_PORT, timeout: float = 5,
              requested: int = PROBE_PROTOCOLS) -> NegotiationResponse | None:
    """
    Connect to an RDP server, perform the X.224 negotiation and return the
    parsed negotiation response (or None if the server did not negotiate).
    """
    with socket.create_connection((host, port), timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(build_connection_request(requested))
        buf = b""
        while True:
            payload, consumed = parse_tpkt(buf)
            if consumed:
                return parse_x224_connection_confirm(payload)
            if len(buf) > MAX_RESPONSE_SIZE:
                raise ValueError("RDP negotiation response is too large")
            chunk = sock.recv(MAX_RESPONSE_SIZE)
            if not chunk:
                raise ConnectionError("connection closed before negotiation response")
            buf += chunk


def main(argv) -> int:
    if len(argv) < 2:
        print(f"usage: {argv[0]} HOST[:PORT]")
        return 1
    host = argv[1]
    port = DEFAULT_RDP_PORT
    if host.rfind(":") > host.rfind("]"):  # ignore ':' inside an IPv6 literal
        host, sport = host.rsplit(":", 1)
        port = int(sport)
    host = host.strip("[]")
    try:
        response = rdp_probe(host, port)
    except OSError as e:
        print(f"error probing {host}:{port}: {e}")
        return 1
    if response is None:
        print(f"{host}:{port} is an RDP server (no security negotiation, standard RDP only)")
        return 0
    if response.type == RDPNeg.RESPONSE:
        print(f"{host}:{port} offers RDP security: {protocols_str(response.selected_protocol)}")
        return 0
    if response.type == RDPNeg.FAILURE:
        try:
            reason = RDPNegFailure(response.failure_code).name
        except ValueError:
            reason = f"code {response.failure_code}"
        print(f"{host}:{port} refused negotiation: {reason}")
        return 0
    print(f"{host}:{port} returned unknown negotiation type {response.type}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
