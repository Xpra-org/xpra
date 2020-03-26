# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server import server_features
from xpra.util import merge_dicts, typedict
from xpra.log import Logger

log = Logger("server")


def get_client_connection_class(caps):
    from xpra.server.source.clientinfo_mixin import ClientInfoMixin
    CC = [ClientInfoMixin]
    #TODO: notifications mixin
    if server_features.clipboard:
        from xpra.server.source.clipboard_connection import ClipboardConnection
        CC.append(ClipboardConnection)
    if server_features.audio:
        from xpra.server.source.audio_mixin import AudioMixin
        CC.append(AudioMixin)
    if server_features.webcam:
        from xpra.server.source.webcam_mixin import WebcamMixin
        CC.append(WebcamMixin)
    if server_features.fileprint:
        from xpra.server.source.fileprint_mixin import FilePrintMixin
        CC.append(FilePrintMixin)
    if server_features.mmap:
        from xpra.server.source.mmap_connection import MMAP_Connection
        CC.append(MMAP_Connection)
    if server_features.input_devices:
        from xpra.server.source.input_mixin import InputMixin
        CC.append(InputMixin)
    if server_features.dbus:
        from xpra.server.source.dbus_mixin import DBUS_Mixin
        CC.append(DBUS_Mixin)
    if server_features.network_state:
        from xpra.server.source.networkstate_mixin import NetworkStateMixin
        CC.append(NetworkStateMixin)
    if server_features.display:
        from xpra.server.source.clientdisplay_mixin import ClientDisplayMixin
        CC.append(ClientDisplayMixin)
    if server_features.windows:
        from xpra.server.source.windows_mixin import WindowsMixin
        CC.append(WindowsMixin)
        #must be after windows mixin so it can assume "self.send_windows" is set
        if server_features.encoding:
            from xpra.server.source.encodings_mixin import EncodingsMixin
            CC.append(EncodingsMixin)
        if server_features.audio and server_features.av_sync:
            from xpra.server.source.avsync_mixin import AVSyncMixin
            CC.append(AVSyncMixin)
    from xpra.server.source.idle_mixin import IdleMixin
    CC.append(IdleMixin)
    CC_BASES = []
    for c in CC:
        r = c.is_needed(caps)
        log("get_client_connection_class(..) %s enabled=%s", c.__name__.split(".")[-1], r)
        if r:
            CC_BASES.append(c)
    from xpra.server.source.client_connection import ClientConnection
    CC_BASES = tuple([ClientConnection]+list(CC_BASES))
    ClientConnectionClass  = type('ClientConnectionClass', CC_BASES, {})
    log("ClientConnectionClass%s", CC_BASES)

    class ClientConnectionMuxer(ClientConnectionClass):

        def __init__(self, protocol, disconnect_cb, session_name, server,
                     idle_add, timeout_add, source_remove,
                     *args):
            self.idle_add = idle_add
            self.timeout_add = timeout_add
            self.source_remove = source_remove
            for bc in CC_BASES:
                try:
                    if bc==ClientConnection:
                        initargs = [protocol, disconnect_cb, session_name]+list(args)
                    else:
                        initargs = ()
                    bc.__init__(self, *initargs)
                    bc.init_from(self, protocol, server)
                except Exception as e:
                    log("%s.__init__(..)", bc, exc_info=True)
                    raise Exception("failed to initialize %s: %s" % (bc, e)) from None

            for c in CC_BASES:
                c.init_state(self)
            self.run()

        def close(self):
            log("%s.close()", self)
            for bc in reversed(CC_BASES):
                log("%s.cleanup()", bc)
                try:
                    bc.cleanup(self)
                except Exception as e:
                    log("%s.cleanup()", bc, exc_info=True)
                    log.error("Error closing connection")
                    log.error(" %s", e)
                    raise Exception("failed to initialize %s: %s" % (bc, e)) from None

        def send_hello(self, server_capabilities):
            capabilities = server_capabilities.copy()
            for bc in CC_BASES:
                log("%s.get_caps()", bc)
                merge_dicts(capabilities, bc.get_caps(self))
            self.send("hello", capabilities)
            self.hello_sent = True

        def get_info(self) -> dict:
            def module_name(m):
                name = str(m.__name__.split(".")[-1])
                return name.replace("Mixin", "").replace("Connection", "").rstrip("_")
            info = {
                "modules"   : tuple(module_name(x) for x in CC_BASES),
                }
            for bc in CC_BASES:
                log("%s.get_info()", bc)
                try:
                    merge_dicts(info, bc.get_info(self))
                except Exception as e:
                    log("merge_dicts on %s", bc, exc_info=True)
                    log.error("Error: cannot add information from %s:", bc)
                    log.error(" %s", e)
            return info

        def parse_hello(self, c : typedict):
            self.ui_client = c.boolget("ui_client", True)
            self.wants_encodings = c.boolget("wants_encodings", self.ui_client)
            self.wants_display = c.boolget("wants_display", self.ui_client)
            self.wants_events = c.boolget("wants_events", False)
            self.wants_aliases = c.boolget("wants_aliases", True)
            self.wants_versions = c.boolget("wants_versions", True)
            self.wants_features = c.boolget("wants_features", True)
            self.wants_default_cursor = c.boolget("wants_default_cursor", False)
            for bc in CC_BASES:
                log("%s.parse_client_caps(..)", bc)
                bc.parse_client_caps(self, c)
            #log client info:
            cinfo = self.get_connect_info()
            for i,ci in enumerate(cinfo):
                log.info("%s%s", ["", " "][int(i>0)], ci)
            if self.client_proxy:
                from xpra.version_util import version_compat_check
                msg = version_compat_check(self.proxy_version)
                if msg:
                    proxylog = Logger("proxy")
                    proxylog.warn("Warning: proxy version may not be compatible: %s", msg)

    return ClientConnectionMuxer
