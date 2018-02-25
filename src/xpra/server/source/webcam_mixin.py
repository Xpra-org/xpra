# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger
log = Logger("webcam")

from xpra.os_util import BytesIOClass, POSIX, OSX
from xpra.util import envint, csv
from xpra.server.source.stub_source_mixin import StubSourceMixin


MAX_WEBCAM_DEVICES = envint("XPRA_MAX_WEBCAM_DEVICES", 1)


"""
Handle webcam forwarding.
"""
class WebcamMixin(StubSourceMixin):

    def __init__(self, webcam_enabled, webcam_device, webcam_encodings):
        self.webcam_enabled = webcam_enabled
        self.webcam_device = webcam_device
        self.webcam_encodings = webcam_encodings
        #for each webcam device_id, the actual device used
        self.webcam_forwarding_devices = {}

    def cleanup(self):
        self.stop_all_virtual_webcams()


    def get_info(self, _proto):
        return {
            "webcam" : {
                "encodings"         : self.webcam_encodings,
                "active-devices"    : len(self.webcam_forwarding_devices),
                }
            }


    def get_device_options(self, device_id):
        if not POSIX or OSX or not self.webcam_enabled:
            return {}
        if self.webcam_device:
            #use the device specified:
            return {
                0 : {
                    "device" : self.webcam_device,
                    },
                   }
        from xpra.platform.xposix.webcam import get_virtual_video_devices
        return get_virtual_video_devices()


    def send_webcam_ack(self, device, frame, *args):
        if self.hello_sent:
            self.send_async("webcam-ack", device, frame, *args)

    def send_webcam_stop(self, device, message):
        if self.hello_sent:
            self.send_async("webcam-stop", device, message)


    def start_virtual_webcam(self, device_id, w, h):
        log("start_virtual_webcam%s", (device_id, w, h))
        assert w>0 and h>0
        webcam = self.webcam_forwarding_devices.get(device_id)
        if webcam:
            log.warn("Warning: virtual webcam device %s already in use,", device_id)
            log.warn(" stopping it first")
            self.stop_virtual_webcam(device_id)
        def fail(msg):
            log.error("Error: cannot start webcam forwarding")
            log.error(" %s", msg)
            self.send_webcam_stop(device_id, msg)
        if not self.webcam_enabled:
            fail("webcam forwarding is disabled")
            return
        devices = self.get_device_options(device_id)
        if len(devices)==0:
            fail("no virtual devices found")
            return
        if len(self.webcam_forwarding_devices)>MAX_WEBCAM_DEVICES:
            fail("too many virtual devices are already in use: %i" % len(self.webcam_forwarding_devices))
            return
        errs = {}
        for vid, device_info in devices.items():
            log("trying device %s: %s", vid, device_info)
            device_str = device_info.get("device")
            try:
                from xpra.codecs.v4l2.pusher import Pusher, get_input_colorspaces    #@UnresolvedImport
                in_cs = get_input_colorspaces()
                p = Pusher()
                src_format = in_cs[0]
                p.init_context(w, h, w, src_format, device_str)
                self.webcam_forwarding_devices[device_id] = p
                log.info("webcam forwarding using %s", device_str)
                #this tell the client to start sending, and the size to use - which may have changed:
                self.send_webcam_ack(device_id, 0, p.get_width(), p.get_height())
                return
            except Exception as e:
                errs[device_str] = str(e)
                del e
        fail("all devices failed")
        if len(errs)>1:
            log.error(" tried %i devices:", len(errs))
        for device_str, err in errs.items():
            log.error(" %s : %s", device_str, err)


    def stop_all_virtual_webcams(self):
        log("stop_all_virtual_webcams() stopping: %s", self.webcam_forwarding_devices)
        for device_id in tuple(self.webcam_forwarding_devices.keys()):
            self.stop_virtual_webcam(device_id)

    def stop_virtual_webcam(self, device_id, message=""):
        webcam = self.webcam_forwarding_devices.get(device_id)
        log("stop_virtual_webcam(%s, %s) webcam=%s", device_id, message, webcam)
        if not webcam:
            log.warn("Warning: cannot stop webcam device %s: no such context!", device_id)
            return
        try:
            del self.webcam_forwarding_devices[device_id]
        except KeyError:
            pass
        try:
            webcam.clean()
        except Exception as e:
            log.error("Error stopping virtual webcam device: %s", e)
            log("%s.clean()", exc_info=True)

    def process_webcam_frame(self, device_id, frame_no, encoding, w, h, data):
        webcam = self.webcam_forwarding_devices.get(device_id)
        log("process_webcam_frame: device %s, frame no %i: %s %ix%i, %i bytes, webcam=%s", device_id, frame_no, encoding, w, h, len(data), webcam)
        assert encoding and w and h and data
        if not webcam:
            log.error("Error: webcam forwarding is not active, dropping frame")
            self.send_webcam_stop(device_id, "not started")
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
            src_format = webcam.get_src_format()
            if not src_format:
                #closed / closing
                return
            #one of those two should be present
            try:
                csc_mod = "csc_swscale"
                from xpra.codecs.csc_swscale.colorspace_converter import get_input_colorspaces, get_output_colorspaces, ColorspaceConverter        #@UnresolvedImport
            except ImportError:
                self.send_webcam_stop(device_id, "no csc module")
                return
            try:
                assert rgb_pixel_format in get_input_colorspaces(), "unsupported RGB pixel format %s" % rgb_pixel_format
                assert src_format in get_output_colorspaces(rgb_pixel_format), "unsupported output colourspace format %s" % src_format
            except Exception as e:
                log.error("Error: cannot convert %s to %s using %s:", rgb_pixel_format, src_format, csc_mod)
                log.error(" input-colorspaces: %s", csv(get_input_colorspaces()))
                log.error(" output-colorspaces: %s", csv(get_output_colorspaces(rgb_pixel_format)))
                self.send_webcam_stop(device_id, "csc format error")
                return
            tw = webcam.get_width()
            th = webcam.get_height()
            csc = ColorspaceConverter()
            csc.init_context(w, h, rgb_pixel_format, tw, th, src_format)
            image = csc.convert_image(bgrx_image)
            webcam.push_image(image)
            #tell the client all is good:
            self.send_webcam_ack(device_id, frame_no)
        except Exception as e:
            log("error on %ix%i frame %i using encoding %s", w, h, frame_no, encoding, exc_info=True)
            log.error("Error processing webcam frame:")
            msg = str(e)
            if not msg:
                msg = "unknown error"
                log.error(" %s error" % webcam, exc_info=True)
            log.error(" %s", msg)
            self.send_webcam_stop(device_id, msg)
            self.stop_virtual_webcam()
