# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

from collections import deque
from typing import Dict, Any, Deque

from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.net.common import PacketType


class ShellServer(StubServerMixin):
    """
    Mixin for adding `shell` support
    """
    def init(self, _opts) -> None:
        self.counter = 0
        self.commands : Deque[str] = deque(maxlen=10)

    def get_info(self, _source=None) -> Dict[str,Any]:
        return {
            "shell" : {
                "counter" : self.counter,
                "last-commands" : list(self.commands),
                },
            }

    def get_server_features(self, _source) -> Dict[str,Any]:
        return {
            "shell" : True,
            }

    def _process_shell_exec(self, proto, packet : PacketType) -> None:
        code = str(packet[1])
        ss = self.get_server_source(proto)
        if ss:
            self.counter += 1
            self.commands.append(code)
            ss.shell_exec(code)


    def init_packet_handlers(self) -> None:
        self.add_packet_handlers({
            "shell-exec" : self._process_shell_exec,
          }, False)
