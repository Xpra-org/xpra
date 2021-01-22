# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

from xpra.server.mixins.stub_server_mixin import StubServerMixin

"""
Mixin for adding shell support
"""
class ShellServer(StubServerMixin):

    def get_info(self, _source=None) -> dict:
        return {
            "shell" : True,
            }

    def get_server_features(self, _source) -> dict:
        return {
            "shell" : True,
            }

    def _process_shell_exec(self, proto, packet):
        code = packet[1]
        ss = self.get_server_source(proto)
        if ss:
            ss.shell_exec(code)


    def init_packet_handlers(self):
        self.add_packet_handlers({
            "shell-exec" : self._process_shell_exec,
          }, False)
