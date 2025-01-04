# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from enum import IntEnum
from typing import TypeAlias


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
    OPENGL_UNSAFE = 30
    COMPONENT_MISSING = 31


ExitValue: TypeAlias = ExitCode | int


def exit_str(code) -> str:
    try:
        return ExitCode(code).name
    except ValueError:
        return f"unknown error {code}"


RETRY_EXIT_CODES: list[ExitCode] = [
    ExitCode.CONNECTION_LOST,
    ExitCode.PACKET_FAILURE,
    ExitCode.UPGRADE,
]
