# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict, Any, Tuple, Type, List

from xpra.server import server_features
from xpra.util import merge_dicts, typedict, print_nested_dict
from xpra.common import LOG_HELLO
from xpra.log import Logger

log = Logger("server")


def get_enabled_mixins() -> Tuple[Type,...]:
    # pylint: disable=import-outside-toplevel
    from xpra.server.source.clientinfo import ClientInfoMixin
    mixins : List[Type] = [ClientInfoMixin]
    if server_features.notifications:
        from xpra.server.source.notification import NotificationMixin
        mixins.append(NotificationMixin)
    if server_features.clipboard:
        from xpra.server.source.clipboard import ClipboardConnection
        mixins.append(ClipboardConnection)
    if server_features.audio:
        from xpra.server.source.audio import AudioMixin
        mixins.append(AudioMixin)
    if server_features.webcam:
        from xpra.server.source.webcam import WebcamMixin
        mixins.append(WebcamMixin)
    if server_features.fileprint:
        from xpra.server.source.fileprint import FilePrintMixin
        mixins.append(FilePrintMixin)
    if server_features.mmap:
        from xpra.server.source.mmap import MMAP_Connection
        mixins.append(MMAP_Connection)
    if server_features.input_devices:
        from xpra.server.source.input import InputMixin
        mixins.append(InputMixin)
    if server_features.dbus:
        from xpra.server.source.dbus import DBUS_Mixin
        mixins.append(DBUS_Mixin)
    if server_features.network_state:
        from xpra.server.source.networkstate import NetworkStateMixin
        mixins.append(NetworkStateMixin)
    if server_features.shell:
        from xpra.server.source.shell import ShellMixin
        mixins.append(ShellMixin)
    if server_features.display:
        from xpra.server.source.display import ClientDisplayMixin
        mixins.append(ClientDisplayMixin)
    if server_features.windows:
        from xpra.server.source.windows import WindowsMixin
        mixins.append(WindowsMixin)
        #must be after windows mixin so it can assume "self.send_windows" is set
        if server_features.encoding:
            from xpra.server.source.encodings import EncodingsMixin
            mixins.append(EncodingsMixin)
        if server_features.audio and server_features.av_sync:
            from xpra.server.source.avsync import AVSyncMixin
            mixins.append(AVSyncMixin)
    from xpra.server.source.idle_mixin import IdleMixin
    mixins.append(IdleMixin)
    return tuple(mixins)


def get_needed_based_classes(caps:typedict) -> Tuple[Type,...]:
    from xpra.server.source.client_connection import ClientConnection
    classes = [ClientConnection]
    mixins = get_enabled_mixins()
    for c in mixins:
        r = c.is_needed(caps)
        log("get_client_connection_class(..) %s enabled=%s", c.__name__.split(".")[-1], r)
        if r:
            classes.append(c)
    return tuple(classes)

def get_client_connection_class(caps):

    CC_BASES = get_needed_based_classes(caps)
    ClientConnectionClass  = type('ClientConnectionClass', CC_BASES, {})
    log("ClientConnectionClass%s", CC_BASES)

    class ClientConnectionMuxer(ClientConnectionClass):

        def __init__(self, protocol, disconnect_cb, session_name, server,
                     idle_add, timeout_add, source_remove,
                     *args):
            self.idle_add = idle_add
            self.timeout_add = timeout_add
            self.source_remove = source_remove
            from xpra.server.source.client_connection import ClientConnection
            for bc in CC_BASES:
                try:
                    if bc==ClientConnection:
                        initargs = [protocol, disconnect_cb, session_name]+list(args)
                    else:
                        initargs = []
                    bc.__init__(self, *initargs)
                    bc.init_from(self, protocol, server)
                except Exception as e:
                    log.error("%s.__init__(..)", bc, exc_info=True)
                    raise RuntimeError(f"failed to initialize {bc}: {e}") from None

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
                    log.estr(e)
                    raise RuntimeError(f"failed to close {bc}: {e}") from None

        def send_hello(self, server_capabilities):
            capabilities = server_capabilities.copy()
            for bc in CC_BASES:
                log("%s.get_caps()", bc)
                merge_dicts(capabilities, bc.get_caps(self))
            if LOG_HELLO:
                netlog = Logger("network")
                netlog.info(f"sending hello to {self}:")
                print_nested_dict(capabilities, print_fn=netlog.info)
            self.send("hello", capabilities)
            self.hello_sent = True

        def get_info(self) -> Dict[str,Any]:
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
                    log.estr(e)
            return info

        def parse_hello(self, c : typedict):
            self.ui_client = c.boolget("ui_client", True)
            self.wants : List[str] = list(c.strtupleget("wants", self.wants))
            for x, default_value in {
                "encodings" : self.ui_client,
                "display"   : self.ui_client,
                "events"    : False,
                "aliases"   : True,
                "versions"  : True,
                "features"  : True,
                "default_cursor"    : False,
                }.items():
                if c.boolget(f"wants_{x}", default_value):
                    self.wants.append(x)
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
