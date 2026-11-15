#!/usr/bin/env python3
# Usage: python3 dump-cert.py HOST PORT (server must support YAML)

import socket
import sys
import yaml

hello = yaml.safe_dump(['hello', {'encoders': ['yaml'], "protocol-version": (7, ), "ssl-upgrade": True}]).encode()

with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=10) as sock:
    sock.sendall(b'P\x04\0\0' + len(hello).to_bytes(4, 'big') + hello)
    with sock.makefile('rb') as stream:
        header = stream.read(8)
        response = yaml.safe_load(stream.read(int.from_bytes(header[4:8], 'big')))
        if response[0] == "ssl-upgrade":
            if cert := response[1].get("cert-data", ""):
                print(cert.decode("latin1"))
