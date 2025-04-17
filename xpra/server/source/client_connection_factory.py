# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

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
    from xpra.server.source.clientinfo import ClientInfoMixin
    mixins: list[type] = [ClientInfoMixin]
    if features.notifications:
        from xpra.server.source.notification import NotificationMixin
        mixins.append(NotificationMixin)
    if features.clipboard:
        from xpra.server.source.clipboard import ClipboardConnection
        mixins.append(ClipboardConnection)
    if features.audio:
        from xpra.server.source.audio import AudioMixin
        mixins.append(AudioMixin)
    if features.webcam:
        from xpra.server.source.webcam import WebcamMixin
        mixins.append(WebcamMixin)
    if features.fileprint:
        from xpra.server.source.fileprint import FilePrintMixin
        mixins.append(FilePrintMixin)
    if features.mmap:
        from xpra.server.source.mmap import MMAP_Connection
        mixins.append(MMAP_Connection)
    if features.input_devices:
        from xpra.server.source.input import InputMixin
        mixins.append(InputMixin)
    if features.dbus:
        from xpra.server.source.dbus import DBUS_Mixin
        mixins.append(DBUS_Mixin)
    if features.network_state:
        from xpra.server.source.networkstate import NetworkStateMixin
        mixins.append(NetworkStateMixin)
    if features.shell:
        from xpra.server.source.shell import ShellMixin
        mixins.append(ShellMixin)
    if features.display:
        from xpra.server.source.display import ClientDisplayMixin
        mixins.append(ClientDisplayMixin)
    if features.cursors:
        from xpra.server.source.cursors import CursorsMixin
        mixins.append(CursorsMixin)
    if features.windows:
        from xpra.server.source.windows import WindowsMixin
        mixins.append(WindowsMixin)
    # must be after windows mixin, so that it can assume "self.send_windows" is set
    if features.encoding:
        from xpra.server.source.encodings import EncodingsMixin
        mixins.append(EncodingsMixin)
    if features.audio and features.av_sync:
        from xpra.server.source.avsync import AVSyncMixin
        mixins.append(AVSyncMixin)
    from xpra.server.source.idle_mixin import IdleMixin
    mixins.append(IdleMixin)
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
            self.hello_sent = False
            from xpra.server.source.client_connection import ClientConnection
            for bc in CC_BASES:
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
                merge_dicts(capabilities, caps)
            if LOG_HELLO:
                netlog = Logger("network")
                netlog.info(f"sending hello to {self}:")
                print_nested_dict(capabilities, print_fn=netlog.info)
            self.send("hello", capabilities)
            self.hello_sent = True

        def threaded_init_complete(self, server) -> None:
            log("threaded_init_complete(%s) calling base classes %s", server, CC_BASES)
            for bc in CC_BASES:
                log("calling %s.threaded_init_complete(%s, %s)", bc, self, server)
                bc.threaded_init_complete(self, server)

        def suspend(self) -> None:
            log("suspend()")
            for bc in CC_BASES:
                bc.suspend(self)

        def resume(self) -> None:
            log("resume()")
            for bc in CC_BASES:
                bc.resume(self)

        def get_info(self) -> dict[str, Any]:
            def module_name(m) -> str:
                name = str(m.__name__.split(".")[-1])
                return name.replace("Mixin", "").replace("Connection", "").rstrip("_")

            info = {
                "modules": tuple(module_name(x) for x in CC_BASES),
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
