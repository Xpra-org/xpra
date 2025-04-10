# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.scripts.config import InitExit
from xpra.exit_codes import ExitCode
from xpra.x11.server.shadow import ShadowX11Server
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.gtk.util import get_default_root_window
from xpra.codecs.image import ImageWrapper
from xpra.codecs.evdi.capture import EvdiDevice, find_evdi_devices, add_evdi_device  # pylint: disable=no-name-in-module
from xpra.log import Logger

GObject = gi_import("GObject")
GLib = gi_import("GLib")

log = Logger("server")
log.enable_debug()


class EVDIModel(RootWindowModel):
    def __repr__(self):
        return f"EVDIModel({self.capture} : {self.geometry})"

    def get_image(self, x, y, width, height) -> ImageWrapper | None:
        dev = self.capture.evdi_device
        log.warn(f"get_image({x}, {y}, {width}, {height}) using {self.capture}, device={dev}")
        if not dev:
            return None
        # r = dev.refresh()
        # log.warn(f"refresh()={r}")
        ld = self.capture.last_damage
        if not ld:
            return None
        bw, bh, buf = ld[:3]
        if bw != width or bh != height:
            return None
        return ImageWrapper(0, 0, width, height, buf, "BGRX", 24, width * 4, )


class ExpandServer(GObject.GObject, ShadowX11Server):

    def __init__(self, attrs: dict[str, str]):
        GObject.GObject.__init__(self)
        ShadowX11Server.__init__(self, attrs)
        self.session_type = "expand"
        self.evdi_device = None
        self.evdi_channel = None
        self.fd_source = None
        self.fd_watch = None
        self.last_damage: tuple = ()

    def init(self, opts) -> None:
        ShadowX11Server.init(self, opts)
        # pylint: disable=import-outside-toplevel
        from xpra.codecs.evdi.load import load_evdi_module
        if not load_evdi_module():
            log.warn("Warning: ensure that the 'evdi' kernel module is loaded")
        devices = find_evdi_devices()
        if not devices:
            raise InitExit(ExitCode.DEVICE_NOT_FOUND, "no evdi devices found")

    def no_windows(self) -> None:
        pass
        # self.cancel_refresh_timer()
        # self.cancel_poll_pointer()

    def refresh(self) -> bool:
        # we have to continue to call the device refresh,
        # otherwise the UI hangs completely!
        dev = self.evdi_device
        log(f"refresh() using device {dev}")
        if dev:
            dev.refresh()
        # return dev is None
        return True

    def evdi_io_event(self, channel, condition) -> bool:
        log.warn(f"io_event({channel}, {condition})")
        self.evdi_device.handle_events()
        # self.evdi_device.refresh()
        return True

    def evdi_setup(self) -> None:
        # import time
        # time.sleep(2)
        log("evdi_setup()")
        devices = find_evdi_devices()
        if not devices:
            # try to add one:
            add_evdi_device()
            devices = find_evdi_devices()
        device = -1 if not devices else devices[0]
        log("devices=%s, device=%i", devices, device)
        dev = EvdiDevice(device, self.evdi_damage)
        self.evdi_device = dev
        log(f"evdi_setup() {dev=}")
        dev.open()
        dev.connect()
        dev.enable_cursor_events()
        log("evdi_setup() done")

    def start_evdi_watch(self) -> bool:
        self.evdi_setup()
        # self.evdi_device.handle_all_events()
        self.fd_source = self.evdi_device.get_event_fd()
        self.evdi_channel = GLib.IOChannel.unix_new(fd=self.fd_source)
        self.evdi_channel.set_encoding(None)
        self.evdi_channel.set_buffered(False)
        self.evdi_channel.set_close_on_unref(True)
        self.fd_watch = GLib.io_add_watch(self.evdi_channel, GLib.PRIORITY_LOW, GLib.IO_IN, self.evdi_io_event)
        return False

    def do_run(self) -> None:
        self.start_refresh_timer()
        # GLib.timeout_add(1*1000, self.start_evdi_watch)
        self.start_evdi_watch()
        super().do_run()

    def evdi_damage(self, width, height, buf, rects) -> None:
        log("evdi_damage(%s)", (width, height, buf, rects))
        self.last_damage = width, height, buf, rects
        self.refresh_windows()

    def cleanup(self) -> None:
        fdw = self.fd_watch
        if fdw:
            self.fd_watch = None
            GLib.source_remove(fdw)
        c = self.evdi_channel
        if c:
            self.evdi_channel = None
            c.shutdown(False)
        ed = self.evdi_device
        if ed:
            self.evdi_device = None
            ed.cleanup()
        super().cleanup()

    def sanity_checks(self, _proto, c) -> bool:
        return True

    def start_poll_pointer(self) -> None:
        """ not needed """

    def get_server_mode(self) -> str:
        return "X11 expand"

    def set_refresh_delay(self, v: int) -> None:
        assert 0 < v < 10000
        self.refresh_delay = v

    def setup_capture(self):
        return None

    def get_root_window_model_class(self) -> type:
        return EVDIModel

    def verify_capture(self, ss) -> None:
        pass

    def makeRootWindowModels(self) -> list[EVDIModel]:
        # TODO: remove root window
        root = get_default_root_window()
        geom = (0, 0, 800, 600)
        model = EVDIModel(root, self, "evdi", geom)
        return [model]

    def do_make_screenshot_packet(self):
        raise NotImplementedError()


GObject.type_register(ExpandServer)
