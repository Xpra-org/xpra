# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

import os.path

from xpra.os_util import OSX, POSIX
from xpra.util import engs
from xpra.scripts.config import FALSE_OPTIONS
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("webcam")


"""
Mixin for servers that handle webcam forwarding,
it just delegates to the webcam source mixin,
so each user can have its own webcam device(s).
"""
class WebcamServer(StubServerMixin):

    def __init__(self):
        self.webcam_device = ""
        self.webcam_encodings = []
        self.webcam_enabled = False
        self.webcam_virtual_video_devices = 0

    def init(self, opts):
        self.webcam_enabled = opts.webcam.lower() not in FALSE_OPTIONS
        if os.path.isabs(opts.webcam):
            self.webcam_device = opts.webcam

    def init_state(self):
        #duplicated
        self.readonly = False

    def threaded_setup(self):
        self.init_webcam()


    def get_server_features(self, _source) -> dict:
        return {
            "webcam"                       : self.webcam_enabled,
            "webcam.encodings"             : self.webcam_encodings,
            "virtual-video-devices"        : self.webcam_virtual_video_devices,
            }


    def get_info(self, _proto) -> dict:
        info = {
                ""                      : self.webcam_enabled,
                }
        if self.webcam_enabled:
            info.update({
                "encodings"             : self.webcam_encodings,
                "virtual-video-devices" : self.webcam_virtual_video_devices,
                })
        if self.webcam_device:
            info["device"] = self.webcam_device
        return {"webcam" : info}


    def init_webcam(self):
        if not self.webcam_enabled:
            return
        try:
            from xpra.codecs.pillow.decoder import get_encodings
            self.webcam_encodings = tuple(x for x in ("png", "jpeg", "webp") if x in get_encodings())
        except Exception as e:
            log.error("Error: webcam forwarding disabled:")
            log.error(" %s", e)
            self.webcam_enabled = False
        if self.webcam_device:
            self.webcam_virtual_video_devices = 1
        else:
            self.webcam_virtual_video_devices = self.init_virtual_video_devices()
            if self.webcam_virtual_video_devices==0:
                self.webcam_enabled = False

    def init_virtual_video_devices(self):
        log("init_virtual_video_devices")
        if not POSIX or OSX:
            return 0
        try:
            from xpra.codecs.v4l2.pusher import Pusher
            assert Pusher
        except ImportError as e:
            log.error("Error: failed to import the virtual video module:")
            log.error(" %s", e)
            return 0
        try:
            from xpra.platform.xposix.webcam import get_virtual_video_devices, check_virtual_dir
        except ImportError as e:
            log.warn("Warning: cannot load webcam components")
            log.warn(" %s", e)
            log.warn(" webcam forwarding disabled")
            return 0
        check_virtual_dir()
        devices = get_virtual_video_devices()
        log.info("found %i virtual video device%s for webcam forwarding", len(devices), engs(devices))
        return len(devices)

    def _process_webcam_start(self, proto, packet):
        if self.readonly:
            return
        assert self.webcam_enabled
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for webcam start")
            return
        device_id, w, h = packet[1:4]
        ss.start_virtual_webcam(device_id, w, h)

    def _process_webcam_stop(self, proto, packet):
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for webcam start")
            return
        device_id, message = (list(packet)+[""])[1:3]
        ss.stop_virtual_webcam(device_id, message)

    def _process_webcam_frame(self, proto, packet):
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for webcam frame")
            return
        device_id, frame_no, encoding, w, h, data = packet[1:7]
        ss.process_webcam_frame(device_id, frame_no, encoding, w, h, data)

    def init_packet_handlers(self):
        if self.webcam_enabled:
            self.add_packet_handlers({
                "webcam-start"  : self._process_webcam_start,
                "webcam-stop"   : self._process_webcam_stop,
                "webcam-frame"  : self._process_webcam_frame,
              }, False)
