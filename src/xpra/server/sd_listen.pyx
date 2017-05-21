# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket

from xpra.log import Logger
log = Logger("util")

from libc.stdint cimport uint64_t, uint16_t


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


def get_sd_listen_sockets():
    cdef int fd, n, i
    n = sd_listen_fds(0)
    log("sd_listen_fds(0)=%i", n)
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

def get_sd_listen_socket(int fd):
    if sd_is_socket_unix(fd, socket.SOCK_STREAM, 1, NULL, 0)>0:
        sock = socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM)
        sockpath = sock.getsockname()
        return "unix-domain", sock, sockpath
    for family in (socket.AF_INET, socket.AF_INET6):
        if sd_is_socket_inet(fd, family, socket.SOCK_STREAM, 1, 0)>0:
            sock = socket.fromfd(fd, family, socket.SOCK_STREAM)
            host, port = sock.getsockname()[:2]
            return "tcp", sock, (host, port)
    #TODO: handle vsock
    return None
