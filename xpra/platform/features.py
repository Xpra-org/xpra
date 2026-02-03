#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.platform import platform_import

# defaults which may be overridden by platform_import:
AUTOSTART: bool = False

INPUT_DEVICES: Sequence[str] = ("auto",)

SOURCE: Sequence[str] = ()

EXECUTABLE_EXTENSION: str = ""

OPEN_COMMAND: Sequence[str] = ()

DEFAULT_START_ENV: Sequence[str] = ()
DEFAULT_ENV: Sequence[str] = ()

DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS: Sequence[tuple[str, str, str]] = (
    ("pactl", "set-default-sink", "Xpra-Speaker"),
    ("pactl", "set-default-source", "Xpra-Mic-Source"),
)

SOCKET_OPTIONS: Sequence[str] = (
    "SO_BROADCAST", "SO_RCVLOWAT",
    "SO_DONTROUTE", "SO_ERROR", "SO_EXCLUSIVEADDRUSE",
    "SO_KEEPALIVE", "SO_LINGER", "SO_OOBINLINE", "SO_RCVBUF",
    "SO_RCVTIMEO", "SO_REUSEADDR", "SO_REUSEPORT",
    "SO_SNDBUF", "SO_SNDTIMEO", "SO_TIMEOUT", "SO_TYPE",
)
IP_OPTIONS: Sequence[str] = (
    # "IP_MULTICAST_IF", "IP_MULTICAST_LOOP", "IP_MULTICAST_TTL",
    "IP_DONTFRAG", "IP_OPTIONS", "IP_RECVLCLIFADDR",
    "IP_RECVPKTINFO", "IP_TOS", "IP_TTL",
)
TCP_OPTIONS: Sequence[str] = ("TCP_NODELAY", "TCP_MAXSEG", "TCP_KEEPALIVE")

_features_list_: Sequence[str] = (
    "AUTOSTART",
    "SOURCE",
    "DEFAULT_ENV",
    "DEFAULT_START_ENV",
    "DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS",
    "EXECUTABLE_EXTENSION",
    "INPUT_DEVICES",
    "OPEN_COMMAND",
    "SOCKET_OPTIONS",
    "IP_OPTIONS",
    "TCP_OPTIONS",
)

platform_import(globals(), "features", False,
                *_features_list_)


def main() -> None:
    from xpra.util.str_fn import print_nested_dict
    from xpra.platform import program_context
    with program_context("Features-Info", "Features Info"):
        d = {}
        for k in _features_list_:
            d[k] = globals()[k]
        print_nested_dict(d)


if __name__ == "__main__":  # pragma: no cover
    main()
