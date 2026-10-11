# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
SSH agent forwarding for paramiko clients,
replacing `paramiko.agent.AgentRequestHandler` which cannot work on MS Windows:
its `AgentProxyThread` requires the agent connection to have a `fileno`,
and it uses `fcntl` and `select`. (see #4353)

The agent protocol is strictly request / response:
each length prefixed request gets exactly one length prefixed reply,
so we can just relay each request with blocking calls.
"""

import struct
from collections.abc import Callable

from xpra.util.env import first_time
from xpra.util.thread import start_thread
from xpra.log import Logger

log = Logger("network", "ssh")

SSH_AGENT_FAILURE = 5
# same as OpenSSH's `AGENT_MAX_LEN`:
MAX_MESSAGE_SIZE = 256 * 1024


def recv_exact(recv: Callable[[int], bytes], size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = recv(size - len(data))
        if not chunk:
            return b""
        data += chunk
    return data


def recv_message(recv: Callable[[int], bytes]) -> bytes:
    header = recv_exact(recv, 4)
    if not header:
        return b""
    size = struct.unpack(">I", header)[0]
    if size > MAX_MESSAGE_SIZE:
        raise ValueError(f"agent message too large: {size} bytes")
    body = recv_exact(recv, size)
    if len(body) != size:
        return b""
    return header + body


def send_all(conn, data: bytes) -> None:
    if hasattr(conn, "sendall"):
        conn.sendall(data)
        return
    while data:
        sent = conn.send(data)
        if not isinstance(sent, int):
            # `PageantConnection.send` processes the whole query and returns `None`
            return
        data = data[sent:]


def failure_reply() -> bytes:
    return struct.pack(">IB", 1, SSH_AGENT_FAILURE)


def get_agent_connection():
    from paramiko.agent import get_agent_connection as paramiko_get_agent_connection
    return paramiko_get_agent_connection()


def forward_agent_channel(chan) -> None:
    """
    Relays the agent requests received on `chan` to the local ssh agent,
    until the channel is closed.
    Requests are answered with `SSH_AGENT_FAILURE` if the local agent is not available.
    """
    log(f"forward_agent_channel({chan})")
    conn = None
    try:
        conn = get_agent_connection()
        log(f"local agent connection: {conn}")
        if not conn and first_time("paramiko-no-ssh-agent"):
            log.warn("Warning: no local SSH agent found, cannot handle forwarded agent requests")
        while request := recv_message(chan.recv):
            reply = b""
            if conn:
                try:
                    send_all(conn, request)
                    reply = recv_message(conn.recv)
                except OSError as e:
                    log(f"agent request on {conn}", exc_info=True)
                    log.warn(f"Warning: SSH agent request failed: {e}")
                if not reply:
                    log.warn("Warning: lost connection to the local SSH agent")
                    close_agent(conn)
                    conn = None
            chan.sendall(reply or failure_reply())
    except Exception as e:
        log(f"forward_agent_channel({chan})", exc_info=True)
        log.error(f"Error forwarding SSH agent requests: {e}")
    finally:
        log(f"forward_agent_channel({chan}) ended")
        if conn:
            close_agent(conn)
        chan.close()


def close_agent(conn) -> None:
    try:
        conn.close()
    except OSError as e:
        log(f"error closing agent connection {conn}: {e}")


def forward_agent(chan) -> None:
    """
    Request agent forwarding on this session channel.
    Each agent connection made by the remote end is handled by its own thread.
    """
    def new_agent_channel(agent_chan) -> None:
        agent_chan.set_name("auth-agent")
        start_thread(forward_agent_channel, "ssh-agent-forward", daemon=True, args=(agent_chan, ))

    chan.request_forward_agent(new_agent_channel)
