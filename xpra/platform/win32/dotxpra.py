# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Sequence

from xpra.util.env import osexpand
from xpra.util.io import get_util_logger
from xpra.common import SocketState

DISPLAY_PREFIX = ""

PIPE_PREFIX = "Xpra\\"
PIPE_ROOT = "\\\\"
PIPE_PATH = "%s.\\pipe\\" % PIPE_ROOT


def norm_makepath(dirpath: str, name: str):
    return PIPE_PATH + PIPE_PREFIX + name.lstrip(":")


class DotXpra:
    def __init__(self, sockdir=None, sockdirs=(), actual_username="", *_args, **_kwargs):
        self.username = actual_username

    def __repr__(self):
        return f"DotXpra({self.username})"

    def osexpand(self, v: str) -> str:
        return osexpand(v, self.username)

    def mksockdir(self, d: str) -> None:
        # socket-dir is not used by the win32 shadow server
        pass

    def displays(self, check_uid=0, matching_state=None) -> Sequence[str]:
        return tuple(self.get_all_namedpipes().keys())

    def norm_socket_paths(self, local_display_name: str) -> list[str]:
        return [self.socket_path(local_display_name)]

    def socket_path(self, local_display_name: str) -> str:
        return norm_makepath("", local_display_name)

    def get_display_state(self, display: str) -> SocketState:
        return self.get_server_state(PIPE_PREFIX + display)

    def get_server_state(self, sockpath: str, _timeout=5) -> SocketState:
        if sockpath in os.listdir(PIPE_PATH):
            return SocketState.LIVE
        return SocketState.DEAD

    def socket_paths(self, check_uid=0, matching_state=None, matching_display=None) -> list[str]:
        return list(self.get_all_namedpipes().values())

    def sockets(self, check_uid=0, matching_state=None):
        # flatten the dictionary into a list:
        return self.get_all_namedpipes().items()

    # find the matching sockets, and return:
    # (state, local_display, sockpath)
    def socket_details(self, check_uid=-1, matching_state=None, matching_display=None) -> dict[str, list]:
        np = self.get_all_namedpipes()
        if not np:
            return {}
        return {
            PIPE_PREFIX.rstrip("\\"): [
                (SocketState.LIVE, display, pipe_name) for display, pipe_name in np.items() if (
                    matching_display is None or display in matching_display
                )
            ]
        }

    def get_all_namedpipes(self) -> dict[str, str]:
        log = get_util_logger()
        xpra_pipes: dict[str, str] = {}
        non_xpra: list[str] = []
        for pipe_name in os.listdir(PIPE_PATH):
            if not pipe_name.startswith(PIPE_PREFIX):
                non_xpra.append(pipe_name)
                continue
            name = pipe_name[len(PIPE_PREFIX):]
            # found an xpra pipe
            # FIXME: filter using matching_display?
            xpra_pipes[name] = pipe_name
            log("found xpra pipe: %s", pipe_name)
        log("found %i non-xpra pipes: %s", len(non_xpra), non_xpra)
        log("get_all_namedpipes()=%s", xpra_pipes)
        return xpra_pipes
