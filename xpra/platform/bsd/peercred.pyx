# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False

from libc.string cimport memset

cdef extern from "unistd.h":
    ctypedef unsigned int uid_t
    ctypedef unsigned int gid_t
    int getpeereid(int s, uid_t *euid, gid_t *egid)


def get_peer_cred(sock: int) -> Tuple[int ,int]:
    """
    Get the effective user and group ID of the peer connected to the given
    socket.

    Args:
        sock (int): The socket file descriptor.

    Returns:
        dict: the paid 'euid' and 'egid'
    """
    cdef uid_t euid
    cdef gid_t egid
    cdef int ret

    memset(&euid, 0, sizeof(euid))
    memset(&egid, 0, sizeof(egid))

    ret = getpeereid(sock, &euid, &egid)
    if ret != 0:
        from xpra.log import Logger
        log = Logger("auth")
        log.error("Error: getpeereid failed on socket %d: %i", sock, ret)
        raise OSError("getpeereid failed")

    return euid, egid
