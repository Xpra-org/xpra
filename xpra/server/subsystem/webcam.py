# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os.path
from typing import Any
from collections.abc import Sequence

from xpra.os_util import OSX, POSIX
from xpra.net.common import Packet
from xpra.util.parsing import FALSE_OPTIONS
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("webcam")


class WebcamServer(StubServerMixin):
    """
    Mixin for servers that handle webcam forwarding,
    it just delegates to the webcam source mixin,
    so each user can have its own webcam device(s).
    """
    PREFIX = "webcam"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.webcam_device = ""
        self.webcam_encodings: Sequence[str] = ()
        self.webcam_enabled: bool = False
        self.webcam_virtual_video_devices: int = 0

    def init(self, opts) -> None:
        self.webcam_enabled = opts.webcam.lower() not in FALSE_OPTIONS
        if os.path.isabs(opts.webcam):
            self.webcam_device = opts.webcam

    def init_state(self) -> None:
        # duplicated
        self.readonly = False

    def threaded_setup(self) -> None:
        self.init_webcam()

    def get_server_features(self, _source) -> dict[str, Any]:
        return {
            WebcamServer.PREFIX: {
                "enabled": self.webcam_enabled,
                "encodings": self.webcam_encodings,
                "devices": self.webcam_virtual_video_devices,
            },
        }

    def get_info(self, _proto) -> dict[str, Any]:
        info: dict[str, Any] = {
            "enabled": self.webcam_enabled,
        }
        if self.webcam_enabled:
            info.update({
                "encodings": self.webcam_encodings,
                "devices": self.webcam_virtual_video_devices,
            })
        if self.webcam_device:
            info["device"] = self.webcam_device
        return {WebcamServer.PREFIX: info}

    def init_webcam(self) -> None:
        if not self.webcam_enabled:
            return
        try:
            # pylint: disable=import-outside-toplevel
            from xpra.codecs.pillow.decoder import get_encodings
        except ImportError:
            log("init_webcam()", exc_info=True)
            log.info("webcam forwarding cannot be enabled without the pillow decoder")
            self.webcam_enabled = False
            return
        try:
            self.webcam_encodings = tuple(x for x in ("png", "jpeg", "webp") if x in get_encodings())
        except Exception as e:
            log("init_webcam()", exc_info=True)
            log.error("Error: webcam forwarding disabled:")
            log.estr(e)
            self.webcam_enabled = False
        if self.webcam_device:
            self.webcam_virtual_video_devices = 1
        else:
            self.webcam_virtual_video_devices = self.init_virtual_video_devices()
            if self.webcam_virtual_video_devices == 0:
                self.webcam_enabled = False

    def init_virtual_video_devices(self) -> int:
        log("init_virtual_video_devices")
        if not POSIX or OSX:
            return 0
        # pylint: disable=import-outside-toplevel
        try:
            from xpra.codecs.v4l2.virtual import VirtualWebcam
            assert VirtualWebcam
        except ImportError:
            log("failed to import the virtual video module", exc_info=True)
            log.info("webcam forwarding requires the v4l2 virtual video module")
            return 0
        try:
            from xpra.platform.posix.webcam import get_virtual_video_devices, check_virtual_dir
        except ImportError as e:
            log.warn("Warning: cannot load webcam components")
            log.warn(" %s", e)
            log.warn(" webcam forwarding disabled")
            return 0
        check_virtual_dir()
        devices = get_virtual_video_devices()
        log.info("found %i virtual video devices for webcam forwarding", len(devices))
        return len(devices)

    def _process_webcam_start(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        assert self.webcam_enabled
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for webcam start")
            return
        device_id = packet.get_i64(1)
        w = packet.get_u16(2)
        h = packet.get_u16(3)
        ss.start_virtual_webcam(device_id, w, h)

    def _process_webcam_stop(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for webcam start")
            return
        device_id = packet.get_i64(1)
        message = ""
        if len(packet) >= 3:
            message = packet.get_str(2)
        ss.stop_virtual_webcam(device_id, message)

    def _process_webcam_frame(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for webcam frame")
            return
        device_id = packet.get_i64(1)
        frame_no = packet.get_u64(2)
        encoding = packet.get_str(3)
        w = packet.get_u16(4)
        h = packet.get_u16(5)
        data = packet.get_buffer(6)
        options = {}
        if len(packet) >= 8:
            options = packet.get_dict(7)
        ss.process_webcam_frame(device_id, frame_no, encoding, w, h, data, options)

    def init_packet_handlers(self) -> None:
        if self.webcam_enabled:
            self.add_packets("webcam-start", "webcam-stop", "webcam-frame")
