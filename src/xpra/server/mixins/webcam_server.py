# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger
log = Logger("webcam")

from xpra.os_util import BytesIOClass, OSX, POSIX
from xpra.util import engs, csv
from xpra.scripts.config import FALSE_OPTIONS


"""
Mixin for servers that handle webcam forwarding,
currently requires v4loopback.
"""
class WebcamServer(object):

    def __init__(self):
        self.webcam_option = ""
        self.webcam = False
        self.webcam_encodings = []
        self.webcam_forwarding_device = None
        self.webcam_virtual_video_devices = 0

    def init(self, opts):
        self.webcam_option = opts.webcam
        self.webcam = opts.webcam.lower() not in FALSE_OPTIONS

    def setup(self, _opts):
        self.init_webcam()

    def threaded_setup(self):
        pass

    def cleanup(self):
        self.stop_virtual_webcam()


    def get_caps(self):
        return {}

    def get_server_features(self, _source):
        return {
            "webcam"                       : self.webcam,
            "webcam.encodings"             : self.webcam_encodings,
            "virtual-video-devices"        : self.webcam_virtual_video_devices,
            }


    def get_info(self):
        webcam_info = {
            ""  : self.webcam,
            }
        if self.webcam_option.startswith("/dev/video"):
            webcam_info["device"] = self.webcam_option
        webcam_info["virtual-video-devices"] = self.webcam_virtual_video_devices
        d = self.webcam_forwarding_device
        if d:
            webcam_info.update(d.get_info())
        return webcam_info


    def init_webcam(self):
        if not self.webcam:
            return
        try:
            from xpra.codecs.pillow.decode import get_encodings
            self.webcam_encodings = get_encodings()
        except Exception as e:
            log.error("Error: webcam forwarding disabled:")
            log.error(" %s", e)
            self.webcam = False
        if self.webcam_option.startswith("/dev/video"):
            self.webcam_virtual_video_devices = 1
        else:
            self.webcam_virtual_video_devices = self.init_virtual_video_devices()
            if self.webcam_virtual_video_devices==0:
                self.webcam = False

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
        assert self.webcam
        ss = self._server_sources.get(proto)
        if not ss:
            log.warn("Warning: invalid client source for webcam start")
            return
        device, w, h = packet[1:4]
        log("starting webcam %sx%s", w, h)
        self.start_virtual_webcam(ss, device, w, h)

    def start_virtual_webcam(self, ss, device, w, h):
        assert w>0 and h>0
        if self.webcam_option.startswith("/dev/video"):
            #use the device specified:
            devices = {
                0 : {
                    "device" : self.webcam_option,
                    }
                       }
        else:
            from xpra.platform.xposix.webcam import get_virtual_video_devices
            devices = get_virtual_video_devices()
            if len(devices)==0:
                log.warn("Warning: cannot start webcam forwarding, no virtual devices found")
                ss.send_webcam_stop(device)
                return
            if self.webcam_forwarding_device:
                self.stop_virtual_webcam()
            log("start_virtual_webcam%s virtual video devices=%s", (ss, device, w, h), devices)
        errs = {}
        for device_id, device_info in devices.items():
            log("trying device %s: %s", device_id, device_info)
            device_str = device_info.get("device")
            try:
                from xpra.codecs.v4l2.pusher import Pusher, get_input_colorspaces    #@UnresolvedImport
                in_cs = get_input_colorspaces()
                p = Pusher()
                src_format = in_cs[0]
                p.init_context(w, h, w, src_format, device_str)
                self.webcam_forwarding_device = p
                log.info("webcam forwarding using %s", device_str)
                #this tell the client to start sending, and the size to use - which may have changed:
                ss.send_webcam_ack(device, 0, p.get_width(), p.get_height())
                return
            except Exception as e:
                errs[device_str] = str(e)
                del e
        #all have failed!
        #cannot start webcam..
        ss.send_webcam_stop(device, str(e))
        log.error("Error setting up webcam forwarding:")
        if len(errs)>1:
            log.error(" tried %i devices:", len(errs))
        for device_str, err in errs.items():
            log.error(" %s : %s", device_str, err)

    def _process_webcam_stop(self, proto, packet):
        assert proto in self._server_sources
        if self.readonly:
            return
        device, message = (packet+[""])[1:3]
        log("stopping webcam device %s", ": ".join([str(x) for x in (device, message)]))
        if not self.webcam_forwarding_device:
            log.warn("Warning: cannot stop webcam device %s: no such context!", device)
            return
        self.stop_virtual_webcam()

    def stop_virtual_webcam(self):
        log("stop_virtual_webcam() webcam_forwarding_device=%s", self.webcam_forwarding_device)
        vfd = self.webcam_forwarding_device
        if vfd:
            self.webcam_forwarding_device = None
            vfd.clean()

    def _process_webcam_frame(self, proto, packet):
        if self.readonly:
            return
        device, frame_no, encoding, w, h, data = packet[1:7]
        log("webcam-frame no %i: %s %ix%i", frame_no, encoding, w, h)
        assert encoding and w and h and data
        ss = self._server_sources.get(proto)
        if not ss:
            log.warn("Warning: invalid client source for webcam frame")
            return
        vfd = self.webcam_forwarding_device
        if not self.webcam_forwarding_device:
            log.warn("Warning: webcam forwarding is not active, dropping frame")
            ss.send_webcam_stop(device, "not started")
            return
        try:
            from xpra.codecs.pillow.decode import get_encodings
            assert encoding in get_encodings(), "invalid encoding specified: %s (must be one of %s)" % (encoding, get_encodings())
            rgb_pixel_format = "BGRX"       #BGRX
            from PIL import Image
            buf = BytesIOClass(data)
            img = Image.open(buf)
            pixels = img.tobytes('raw', rgb_pixel_format)
            from xpra.codecs.image_wrapper import ImageWrapper
            bgrx_image = ImageWrapper(0, 0, w, h, pixels, rgb_pixel_format, 32, w*4, planes=ImageWrapper.PACKED)
            src_format = vfd.get_src_format()
            if not src_format:
                #closed / closing
                return
            #one of those two should be present
            try:
                csc_mod = "csc_swscale"
                from xpra.codecs.csc_swscale.colorspace_converter import get_input_colorspaces, get_output_colorspaces, ColorspaceConverter        #@UnresolvedImport
            except ImportError:
                ss.send_webcam_stop(device, "no csc module")
                return
            try:
                assert rgb_pixel_format in get_input_colorspaces(), "unsupported RGB pixel format %s" % rgb_pixel_format
                assert src_format in get_output_colorspaces(rgb_pixel_format), "unsupported output colourspace format %s" % src_format
            except Exception as e:
                log.error("Error: cannot convert %s to %s using %s:", rgb_pixel_format, src_format, csc_mod)
                log.error(" input-colorspaces: %s", csv(get_input_colorspaces()))
                log.error(" output-colorspaces: %s", csv(get_output_colorspaces(rgb_pixel_format)))
                ss.send_webcam_stop(device, "csc format error")
                return
            tw = vfd.get_width()
            th = vfd.get_height()
            csc = ColorspaceConverter()
            csc.init_context(w, h, rgb_pixel_format, tw, th, src_format)
            image = csc.convert_image(bgrx_image)
            vfd.push_image(image)
            #tell the client all is good:
            ss.send_webcam_ack(device, frame_no)
        except Exception as e:
            log("error on %ix%i frame %i using encoding %s", w, h, frame_no, encoding, exc_info=True)
            log.error("Error processing webcam frame:")
            if str(e):
                log.error(" %s", e)
            else:
                log.error("unknown error", exc_info=True)
            ss.send_webcam_stop(device, str(e))
            self.stop_virtual_webcam()


    def init_packet_handlers(self):
        self._authenticated_packet_handlers.update({
            "webcam-start":                         self._process_webcam_start,
            "webcam-stop":                          self._process_webcam_stop,
            "webcam-frame":                         self._process_webcam_frame,
          })
