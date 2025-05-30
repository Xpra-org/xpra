# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

import os
import socket
from typing import Any
from collections.abc import Sequence

from xpra.log import Logger

from libc.stdint cimport uint64_t, uint16_t   # pylint: disable=syntax-error

log = Logger("util", "network")


DEF SD_LISTEN_FDS_START=3


cdef extern from "systemd/sd-daemon.h":
    int sd_listen_fds(int unset_environment);
    int sd_listen_fds_with_names(int unset_environment, char ***names);

    int sd_is_fifo(int fd, const char *path)
    int sd_is_special(int fd, const char *path)
    int sd_is_socket(int fd, int family, int type, int listening)
    int sd_is_socket_inet(int fd, int family, int type, int listening, uint16_t port)
    #int sd_is_socket_sockaddr(int fd, int type, const struct sockaddr* addr, unsigned addr_len, int listening)
    int sd_is_socket_unix(int fd, int type, int listening, const char *path, size_t length)
    int sd_is_mq(int fd, const char *path)
    int sd_notify(int unset_environment, const char *state)
    int sd_booted()
    int sd_watchdog_enabled(int unset_environment, uint64_t *usec)


def get_sd_listen_sockets() -> Sequence[Tuple[str, Any, Tuple[str, int]]]:
    cdef int fd, i
    cdef int n = sd_listen_fds(0)
    log("sd_listen_fds(0)=%i", n)
    if n:
        log("REMOTE_ADDR=%s, REMOTE_PORT=%s", os.environ.get("REMOTE_ADDR", ""), os.environ.get("REMOTE_PORT", ""))
    sockets = []
    for i in range(n):
        fd = SD_LISTEN_FDS_START + i
        socket = get_sd_listen_socket(fd)
        if not socket:
            log.warn("Warning: unknown systemd socket type for fd=%i", fd)
        else:
            sockets.append(socket)
    log("get_sd_listen_sockets()=%s", sockets)
    return sockets


def get_sd_socket_type(fd) -> str:
    from xpra.net.common import TCP_SOCKTYPES
    socktype = os.environ.get("XPRA_SD%i_SOCKET_TYPE" % fd)
    if not socktype:
        socktype = os.environ.get("XPRA_SD_SOCKET_TYPE", "tcp")
    if socktype not in TCP_SOCKTYPES:
        log.warning("Warning: invalid sd socket type '%s', using 'tcp'", socktype)
        socktype = "tcp"
    return socktype


def get_sd_listen_socket(int fd) -> Tuple[str, Any, Tuple[str, int]]:
    #re-wrapping the socket gives us a more proper socket object,
    #so we can then wrap it with ssl
    def fromfd(family, stype, proto=0):
        #python3 does not need re-wrapping?
        return socket.socket(family, stype, 0, fd)
    if sd_is_socket_unix(fd, socket.SOCK_STREAM, 1, NULL, 0)>0:
        sock = fromfd(socket.AF_UNIX, socket.SOCK_STREAM)
        sockpath = sock.getsockname()
        return "socket", sock, sockpath
    for family in (socket.AF_INET, socket.AF_INET6):
        if sd_is_socket_inet(fd, family, socket.SOCK_STREAM, 1, 0)>0:
            sock = fromfd(family, socket.SOCK_STREAM)
            host, port = sock.getsockname()[:2]
            socktype = get_sd_socket_type(fd)
            return socktype, sock, (host, port)
    #TODO: handle vsock
    return None
