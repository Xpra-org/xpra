# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.net.packet_type import WINDOW_CLOSE
from xpra.util.objects import typedict
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("window")

WM_CLASS_CLOSEEXIT: list[str] = os.environ.get("XPRA_WM_CLASS_CLOSEEXIT", "Xephyr").split(",")
TITLE_CLOSEEXIT: list[str] = os.environ.get("XPRA_TITLE_CLOSEEXIT", "Xnest").split(",")


class WindowClose(StubClientMixin):

    def __init__(self):
        self.window_close_action: str = "forward"

    def init(self, opts) -> None:
        if opts.window_close in ("forward", "ignore", "disconnect", "shutdown", "auto"):
            self.window_close_action = opts.window_close
            return
        self.window_close_action = "forward"
        log.warn("Warning: invalid 'window-close' option: %r", opts.window_close)
        log.warn(" using %r", self.window_close_action)

    # noinspection PyUnreachableCode
    def window_close_event(self, wid: int) -> None:
        log("window_close_event(%s) close window action=%s", wid, self.window_close_action)
        if self.window_close_action == "forward":
            self.send(WINDOW_CLOSE, wid)
        elif self.window_close_action == "ignore":
            log("close event for window %#x ignored", wid)
        elif self.window_close_action == "disconnect":
            log.info("window-close set to disconnect, exiting (window %#x)", wid)
            self.quit(0)
        elif self.window_close_action == "shutdown":
            self.send("shutdown-server", "shutdown on window close")
        elif self.window_close_action == "auto":
            # forward unless this looks like a desktop,
            # this allows us to behave more like VNC:
            window = self.get_window(wid)
            log("window_close_event(%#x) window=%s", wid, window)
            if self.server_is_desktop:
                log.info("window-close event on desktop or shadow window, disconnecting")
                self.quit(0)
                return
            if window:
                metadata = typedict(getattr(window, "_metadata", {}))
                log("window_close_event(%#x) metadata=%s", wid, metadata)
                class_instance = metadata.strtupleget("class-instance", ("", ""))
                title = metadata.strget("title")
                log("window_close_event(%#x) title=%r, class-instance=%s", wid, title, class_instance)
                matching_title_close = [x for x in TITLE_CLOSEEXIT if x and title.startswith(x)]
                close = None
                if matching_title_close:
                    close = "window-close event on %s window" % title
                elif len(class_instance) == 2 and class_instance[1] in WM_CLASS_CLOSEEXIT:
                    close = "window-close event on %s window" % class_instance[0]
                if close:
                    # honour this close request if there are no other windows:
                    if len(self._id_to_window) == 1:
                        log.info("%s, disconnecting", close)
                        self.quit(0)
                        return
                    log("there are %i windows, so forwarding %s", len(self._id_to_window), close)
            # default to forward:
            self.send(WINDOW_CLOSE, wid)
        else:
            log.warn("unknown close-window action: %s", self.window_close_action)
