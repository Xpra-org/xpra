# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from enum import IntEnum

class ExitCode(IntEnum):
    OK = 0
    CONNECTION_LOST = 1
    TIMEOUT = 2
    PASSWORD_REQUIRED = 3
    PASSWORD_FILE_ERROR = 4
    INCOMPATIBLE_VERSION = 5
    ENCRYPTION = 6
    FAILURE = 7
    SSH_FAILURE = 8
    PACKET_FAILURE = 9
    MMAP_TOKEN_FAILURE = 10
    NO_AUTHENTICATION = 11
    UNSUPPORTED = 12
    REMOTE_ERROR = 13
    INTERNAL_ERROR = 14
    FILE_TOO_BIG = 15
    SSL_FAILURE = 16
    SSH_KEY_FAILURE = 17
    CONNECTION_FAILED = 18
    SSL_CERTIFICATE_VERIFY_FAILURE = 19
    NO_DISPLAY = 20
    SERVER_ALREADY_EXISTS = 21
    SOCKET_CREATION_ERROR = 22
    VFB_ERROR = 23
    FILE_NOT_FOUND = 24
    UPGRADE = 25
    IO_ERROR = 26
    NO_DATA = 27
    AUTHENTICATION_FAILED = 28
    DEVICE_NOT_FOUND = 29


EXIT_STR = {
    ExitCode.OK                     : "OK",
    ExitCode.CONNECTION_LOST        : "CONNECTION_LOST",
    ExitCode.TIMEOUT                : "TIMEOUT",
    ExitCode.PASSWORD_REQUIRED      : "PASSWORD_REQUIRED",
    ExitCode.PASSWORD_FILE_ERROR    : "PASSWORD_FILE_ERROR",
    ExitCode.INCOMPATIBLE_VERSION   : "INCOMPATIBLE_VERSION",
    ExitCode.ENCRYPTION             : "ENCRYPTION",
    ExitCode.FAILURE                : "FAILURE",
    ExitCode.SSH_FAILURE            : "SSH_FAILURE",
    ExitCode.PACKET_FAILURE         : "PACKET_FAILURE",
    ExitCode.MMAP_TOKEN_FAILURE     : "MMAP_TOKEN_FAILURE",
    ExitCode.NO_AUTHENTICATION      : "NO_AUTHENTICATION",
    ExitCode.UNSUPPORTED            : "UNSUPPORTED",
    ExitCode.REMOTE_ERROR           : "REMOTE_ERROR",
    ExitCode.INTERNAL_ERROR         : "INTERNAL_ERROR",
    ExitCode.FILE_TOO_BIG           : "FILE_TOO_BIG",
    ExitCode.SSL_FAILURE            : "SSL_FAILURE",
    ExitCode.SSH_KEY_FAILURE        : "SSH_KEY_FAILURE",
    ExitCode.CONNECTION_FAILED      : "CONNECTION_FAILED",
    ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE : "SSL_CERTIFICATE_VERIFY_FAILURE",
    ExitCode.NO_DISPLAY             : "NO_DISPLAY",
    ExitCode.SERVER_ALREADY_EXISTS  : "SERVER_ALREADY_EXISTS",
    ExitCode.SOCKET_CREATION_ERROR  : "SOCKET_CREATION_ERROR",
    ExitCode.VFB_ERROR              : "VFB_ERROR",
    ExitCode.FILE_NOT_FOUND         : "FILE_NOT_FOUND",
    ExitCode.UPGRADE                : "UPGRADE",
    ExitCode.IO_ERROR               : "IO_ERROR",
    ExitCode.NO_DATA                : "NO_DATA",
    ExitCode.AUTHENTICATION_FAILED  : "AUTHENTICATION_FAILED",
    ExitCode.DEVICE_NOT_FOUND       : "DEVICE_NOT_FOUND",
    }

RETRY_EXIT_CODES = [
    ExitCode.CONNECTION_LOST,
    ExitCode.PACKET_FAILURE,
    ExitCode.UPGRADE,
    ]
