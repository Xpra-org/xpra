# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Any
from collections.abc import Sequence, Callable

from xpra.server import features
from xpra.util.str_fn import print_nested_dict
from xpra.util.objects import typedict, merge_dicts
from xpra.common import LOG_HELLO
from xpra.log import Logger

log = Logger("server")


def get_enabled_mixins() -> Sequence[type]:
    # pylint: disable=import-outside-toplevel
    from xpra.server.source.clientinfo import ClientInfoConnection
    mixins: list[type] = [ClientInfoConnection]
    if features.notification:
        from xpra.server.source.notification import NotificationConnection
        mixins.append(NotificationConnection)
    if features.clipboard:
        from xpra.server.source.clipboard import ClipboardConnection
        mixins.append(ClipboardConnection)
    if features.audio:
        from xpra.server.source.audio import AudioConnection
        mixins.append(AudioConnection)
    if features.webcam:
        from xpra.server.source.webcam import WebcamConnection
        mixins.append(WebcamConnection)
    if features.file:
        from xpra.server.source.file import FileConnection
        mixins.append(FileConnection)
    if features.printer:
        from xpra.server.source.printer import PrinterConnection
        mixins.append(PrinterConnection)
    if features.mmap:
        from xpra.server.source.mmap import MMAP_Connection
        mixins.append(MMAP_Connection)
    if features.keyboard:
        from xpra.server.source.keyboard import KeyboardConnection
        mixins.append(KeyboardConnection)
    if features.pointer:
        from xpra.server.source.pointer import PointerConnection
        mixins.append(PointerConnection)
    if features.dbus:
        from xpra.server.source.dbus import DBUS_Connection
        mixins.append(DBUS_Connection)
    if features.bandwidth:
        from xpra.server.source.bandwidth import BandwidthConnection
        mixins.append(BandwidthConnection)
    if features.ping:
        from xpra.server.source.ping import PingConnection
        mixins.append(PingConnection)
    if features.shell:
        from xpra.server.source.shell import ShellConnection
        mixins.append(ShellConnection)
    if features.display:
        from xpra.server.source.display import DisplayConnection
        mixins.append(DisplayConnection)
    if features.cursor:
        from xpra.server.source.cursor import CursorsConnection
        mixins.append(CursorsConnection)
    if features.window:
        from xpra.server.source.window import WindowsConnection
        mixins.append(WindowsConnection)
    # must be after windows mixin, so that it can assume "self.send_windows" is set
    if features.encoding:
        from xpra.server.source.encoding import EncodingsConnection
        mixins.append(EncodingsConnection)
    if features.audio and features.av_sync:
        from xpra.server.source.avsync import AVSyncConnection
        mixins.append(AVSyncConnection)
    from xpra.server.source.idle_mixin import IdleConnection
    mixins.append(IdleConnection)
    return tuple(mixins)


def get_needed_based_classes(caps: typedict) -> tuple[type, ...]:
    from xpra.server.source.client_connection import ClientConnection
    classes: list[type] = [ClientConnection]
    mixins = get_enabled_mixins()
    for c in mixins:
        r = c.is_needed(caps)
        log("get_client_connection_class(..) %s enabled=%s", c.__name__.split(".")[-1], r)
        if r:
            classes.append(c)
    return tuple(classes)


def get_client_connection_class(caps: typedict):
    CC_BASES = get_needed_based_classes(caps)
    ClientConnectionClass = type('ClientConnectionClass', CC_BASES, {})
    log("ClientConnectionClass%s", CC_BASES)

    class ClientConnectionMuxer(ClientConnectionClass):

        def __init__(self, protocol, disconnect_cb: Callable, server, setting_changed: Callable):
            self.hello_sent = 0.0
            from xpra.server.source.client_connection import ClientConnection
            for bc in CC_BASES:
                log("ClientConnectionMuxer: initializing %s", bc.__name__)
                try:
                    if bc == ClientConnection:
                        initargs = (protocol, disconnect_cb, setting_changed)
                    else:
                        initargs = ()
                    bc.__init__(self, *initargs)
                    bc.init_from(self, protocol, server)
                except Exception as e:
                    log.error("%s.__init__(..)", bc, exc_info=True)
                    raise RuntimeError(f"failed to initialize {bc}: {e}") from None

            for c in CC_BASES:
                c.init_state(self)
            self.run()

        def close(self) -> None:
            log("%s.close()", self)
            for bc in reversed(CC_BASES):
                log("%s.cleanup()", bc)
                try:
                    bc.cleanup(self)
                except Exception as e:
                    log("%s.cleanup()", bc, exc_info=True)
                    log.error("Error closing connection,")
                    log.error(" %s in %s module:", type(e).__name__, bc.__name__)
                    log.estr(e)
                    raise RuntimeError(f"failed to close {bc}: {e}") from None

        def send_hello(self, server_capabilities: dict) -> None:
            capabilities = server_capabilities.copy()
            for bc in CC_BASES:
                caps = bc.get_caps(self)
                log("%s.get_caps()=%s", bc, caps)
                try:
                    merge_dicts(capabilities, caps)
                except ValueError:
                    log.error("Error merging capabilities from %s", bc)
                    log.error(" %s", caps)
                    raise
            if LOG_HELLO:
                netlog = Logger("network")
                netlog.info(f"sending hello to {self}:")
                print_nested_dict(capabilities, print_fn=netlog.info)
            self.send("hello", capabilities)
            self.hello_sent = monotonic()

        def get_info(self) -> dict[str, Any]:
            def module_name(m) -> str:
                name = str(m.__name__.split(".")[-1])
                return name.replace("Mixin", "").replace("Connection", "").rstrip("_")

            info = {
                "subsystems": tuple(module_name(x) for x in CC_BASES),
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

        def parse_hello(self, c: typedict) -> None:
            self.ui_client = c.boolget("ui_client", True)
            self.wants: list[str] = list(c.strtupleget("wants", self.wants))
            for x, enabled in {
                "encodings": self.ui_client,
                "display": self.ui_client,
                "versions": True,
                "features": True,
            }.items():
                if enabled:
                    self.wants.append(x)
            for bc in CC_BASES:
                log("%s.parse_client_caps(..)", bc)
                bc.parse_client_caps(self, c)
            # log client info:
            cinfo = self.get_connect_info()
            for i, ci in enumerate(cinfo):
                log.info("%s%s", ["", " "][int(i > 0)], ci)
            if self.client_proxy:
                from xpra.util.version import version_compat_check
                msg = version_compat_check(self.proxy_version)
                if msg:
                    proxylog = Logger("proxy")
                    proxylog.warn("Warning: proxy version may not be compatible: %s", msg)

    return ClientConnectionMuxer
