# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, cdivision=True

import socket as pysocket
import struct
from xpra.log import Logger
log = Logger("network")


cdef extern from "string.h":
    void *memset(void * ptr, int value, size_t num) nogil

cdef extern from "unistd.h":
    int close(int fd)

cdef extern from "sys/socket.h":
    int AF_VSOCK
    int SOCK_DGRAM
    int SOCK_STREAM
    cdef struct sockaddr:
        pass
    ctypedef int socklen_t
    int socket(int socket_family, int socket_type, int protocol)
    int bind(int sockfd, const sockaddr *addr, socklen_t addrlen)
    int getsockname(int sockfd, sockaddr *addr, socklen_t *addrlen)
    int accept(int sockfd, sockaddr *addr, socklen_t *addrlen)
    int connect(int sockfd, const sockaddr *addr, socklen_t addrlen)


cdef extern from "linux/vm_sockets.h":
    unsigned int VMADDR_CID_ANY
    unsigned int VMADDR_CID_HYPERVISOR
    unsigned int VMADDR_CID_HOST
    unsigned int VMADDR_PORT_ANY


    unsigned int SO_VM_SOCKETS_BUFFER_SIZE
    unsigned int SO_VM_SOCKETS_BUFFER_MIN_SIZE
    unsigned int SO_VM_SOCKETS_BUFFER_MAX_SIZE
    unsigned int SO_VM_SOCKETS_PEER_HOST_VM_ID
    unsigned int SO_VM_SOCKETS_TRUSTED
    unsigned int SO_VM_SOCKETS_CONNECT_TIMEOUT
    unsigned int SO_VM_SOCKETS_NONBLOCK_TXRX

    ctypedef unsigned short __kernel_sa_family_t
    cdef struct sockaddr_vm:
        __kernel_sa_family_t svm_family
        unsigned short svm_reserved1
        unsigned int svm_port
        unsigned int svm_cid

CID_ANY = VMADDR_CID_ANY
CID_HYPERVISOR = VMADDR_CID_HYPERVISOR
CID_HOST = VMADDR_CID_HOST
PORT_ANY = VMADDR_PORT_ANY

CID_TYPES = {
             CID_ANY        : "ANY",
             CID_HYPERVISOR : "HYPERVISOR",
             CID_HOST       : "HOST",
             }
STR_TO_CID = {
              "ANY"         : CID_ANY,
              "HYPERVISOR"  : CID_HYPERVISOR,
              "HOST"        : CID_HOST,
              }

SOCK_TYPES = {
              SOCK_STREAM   : "STREAM",
              SOCK_DGRAM    : "DGRAM",
              }


def bind_vsocket(sock_type=SOCK_STREAM, cid=VMADDR_CID_HOST, port=VMADDR_PORT_ANY):
    log("server_socket(%s)", (SOCK_TYPES.get(sock_type, sock_type), CID_TYPES.get(cid, cid), port))
    assert sock_type in (SOCK_STREAM, SOCK_DGRAM), "invalid socket type %s" % sock_type
    #assert cid in (VMADDR_CID_ANY, VMADDR_CID_HYPERVISOR, VMADDR_CID_HOST), "invalid cid %s" % cid
    assert port==VMADDR_PORT_ANY or (port>0 and port<65536)
    log("socket(AF_VSOCK, %s, 0)", SOCK_TYPES.get(sock_type, sock_type))
    cdef int sockfd = socket(AF_VSOCK, sock_type, 0)
    log("socket(..)=%i", sockfd)
    if sockfd<0:
        raise Exception("AF_VSOCK not supported")
    cdef sockaddr_vm vmsock
    memset(&vmsock, 0, sizeof(sockaddr_vm))
    vmsock.svm_family = AF_VSOCK
    vmsock.svm_cid = cid    #VMADDR_CID_HOST
    vmsock.svm_port = port

    if bind(sockfd, <sockaddr*> &vmsock, sizeof(sockaddr_vm)):
        close(sockfd)
        raise Exception("failed to bind to AF_VSOCK socket %i:%i", cid, port)

    cdef socklen_t socklen = sizeof(sockaddr_vm)
    if getsockname(sockfd, <sockaddr *> &vmsock, &socklen):
        close(sockfd)
        raise Exception("getsockname failed")
    log("cid=%s, port=%i", CID_TYPES.get(vmsock.svm_cid, vmsock.svm_cid), vmsock.svm_port)
    vsock = VSocket(sockfd)
    return vsock

class VSocket(object):
    def __init__(self, sockfd):
        self.sockfd = sockfd
        self.sock = pysocket.fromfd(sockfd, AF_VSOCK, 0)
        self.address = None

    def __getattr__(self, attr):
        return getattr(self.sock, attr)

    def accept(self):
        cdef sockaddr_vm vmsock
        cdef socklen_t socklen = sizeof(sockaddr_vm)
        memset(&vmsock, 0, socklen)
        cdef int fd = accept(self.sockfd, <sockaddr*> &vmsock, &socklen)
        if fd<0:
            raise Exception("accept failed: %s" % fd)
        self.address = (vmsock.svm_cid, vmsock.svm_port)
        conn = pysocket.fromfd(fd, AF_VSOCK, 0)
        return VSocket(conn.fileno()), self.address

    def getsockname(self):
        return self.address

    def __repr__(self):
        return "VSocket(%s)" % self.sockfd


def connect_vsocket(sock_type=SOCK_STREAM, cid=VMADDR_CID_ANY, port=VMADDR_PORT_ANY):
    log("connect_vsocket(%s)", (cid, port, sock_type))
    assert sock_type in (SOCK_STREAM, SOCK_DGRAM), "invalid socket type %s" % sock_type
    #assert cid in (VMADDR_CID_ANY, VMADDR_CID_HYPERVISOR, VMADDR_CID_HOST), "invalid cid %s" % cid
    assert port==VMADDR_PORT_ANY or (port>0 and port<65536)
    log("socket(%i, %i, 0)", AF_VSOCK, sock_type)
    cdef int sockfd = socket(AF_VSOCK, sock_type, 0)
    log("socket(AF_VSOCK, SOCK_DGRAM, 0)=%i", sockfd)
    if sockfd<0:
        raise Exception("AF_VSOCK not supported")

    cdef sockaddr_vm vmsock
    memset(&vmsock, 0, sizeof(sockaddr_vm))
    vmsock.svm_family = AF_VSOCK
    vmsock.svm_cid = cid
    vmsock.svm_port = port

    if connect(sockfd, <sockaddr *> &vmsock, sizeof(sockaddr_vm)):
        raise Exception("failed to connect to server vsock %i:%i" % (cid, port))

    vsock = VSocket(sockfd)
    return vsock
