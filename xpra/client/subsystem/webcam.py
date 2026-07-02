# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from time import monotonic
from threading import RLock
from typing import Any
from collections.abc import Sequence

from xpra.codecs.constants import PREFERRED_ENCODING_ORDER
from xpra.util.parsing import FALSE_OPTIONS
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import envint, OSEnvContext
from xpra.util.thread import start_thread
from xpra.net import compression
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.os_util import WIN32, OSX, POSIX
from xpra.common import may_notify_client
from xpra.constants import NotificationID
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("webcam")

WEBCAM_TARGET_FPS = max(1, min(50, envint("XPRA_WEBCAM_FPS", 20)))
PIL_FORMATS = ("RGB", "RGBX", "RGBA", "BGRX")


def is_available() -> bool:
    with OSEnvContext(LANG="C", LC_ALL="C"):
        if WIN32:
            try:
                from xpra.platform.win32.webcam import get_directshow_devices
                return bool(get_directshow_devices())
            except ImportError as e:
                log("is_available() no DirectShow: %s", e)
        elif OSX:
            try:
                from xpra.platform.darwin.webcam import get_avfoundation_devices
                return bool(get_avfoundation_devices())
            except ImportError as e:
                log("is_available() no AVFoundation: %s", e)
        elif POSIX:
            try:
                import libcamera  # noqa: F401
                return True
            except ImportError as e:
                log("is_available() no libcamera: %s", e)
        return False


class WebcamForwarder(StubClientMixin):
    """
    Mixin for clients that forward webcams
    """
    PACKET_TYPES = ("webcam-ack", "webcam-stop")
    PREFIX = "webcam"
    __signals__ = ["webcam-changed"]

    def __init__(self, client=None):
        StubClientMixin.__init__(self, client)
        # webcam:
        self.option = ""
        self.forwarding = False
        self.device = None
        self.device_no = -1
        self.frame_no = 0
        self.last_ack = -1
        self.ack_check_timer = 0
        self.send_timer = 0
        self.lock = RLock()
        self.resume_restart = ()
        self.csc = None
        self.encoding = ""
        self.server_enabled = False
        self.server_client_mode = False
        self.server_encodings: Sequence[str] = ()
        self.server_rgb_formats: Sequence[str] = ()

    def cleanup(self) -> None:
        self.stop_sending_webcam()

    def init(self, opts) -> None:
        self.option = opts.webcam
        self.forwarding = self.option.lower() not in FALSE_OPTIONS
        self.server_enabled = False
        log("webcam forwarding: %s", self.forwarding)

    def load(self) -> None:
        if power := self.get_subsystem("power"):
            power.connect("suspend", self.suspend_webcam)
            power.connect("resume", self.resume_webcam)

    def get_caps(self) -> dict[str, Any]:
        if not self.forwarding:
            return {}
        return {"webcam": True}

    def parse_server_capabilities(self, c: typedict) -> bool:
        v = c.get("webcam")
        log("parse_server_capabilities(..) webcam=%s", v)
        if isinstance(v, dict):
            cdict = typedict(v)
            self.server_enabled = cdict.boolget("enabled")
            self.server_encodings = cdict.strtupleget("encodings", ("png", "jpeg"))
            self.server_rgb_formats = cdict.strtupleget("rgb-formats", ("BGRX", ))
            self.server_client_mode = cdict.boolget("client_mode", False)
        elif BACKWARDS_COMPATIBLE:
            # pre v6 / 5.0.2
            self.server_enabled = c.boolget("webcam")
            if self.server_enabled:
                self.server_encodings = c.strtupleget("webcam.encodings", ("png", "jpeg"))
        log("webcam server support: %s (encodings: %s, rgb-formats=%s, client_mode: %s)",
            self.server_enabled, csv(self.server_encodings), csv(self.server_rgb_formats),
            self.server_client_mode)
        # In client_mode the server may report devices=1 without v4l2, honour that
        if self.forwarding and self.server_enabled:
            device = self.option
            if device == "on" or device.find("/dev/video") >= 0:
                try:
                    device_no = int(device.removeprefix("/dev/video"))
                except ValueError:
                    device_no = 0
                self.client.after_handshake(self.start_sending_webcam, device_no, device)
        return True

    def suspend_webcam(self, _client) -> None:
        self.resume_restart = (self.device_no, self.device)
        self.stop_sending_webcam()

    def resume_webcam(self, _client) -> None:
        if restart := self.resume_restart:
            self.resume_restart = ()
            self.start_sending_webcam(*restart)

    def webcam_state_changed(self) -> None:
        self.idle_add(self.emit, "webcam-changed")

    ######################################################################
    def start_sending_webcam(self, device_no: int, device: str) -> None:
        if not self.forwarding:
            return
        with self.lock:
            if not is_available():
                log("init webcam failure: no webcam capture backend found")
                log.info("no webcam capture backend available, webcam forwarding is not available")
                self.forwarding = False
                return
            if not self.send_timer:
                start_thread(self.do_start_sending_webcam, "start-sending-webcam",
                             daemon=True, args=(device_no, device, ))

    def do_start_sending_webcam(self, device_no: int, device: str) -> None:
        log("do_start_sending_webcam(%s, %s)", device_no, device)
        assert self.server_enabled
        from xpra.webcam import open_camera
        try:
            webcam_device = open_camera(device)
        except Exception as e:
            log("open_camera(%s)", device, exc_info=True)
            log.error("Error: failed to open webcam device %r: %s", device, e)
            return
        if webcam_device is None:
            return

        self.frame_no = 0
        try:
            # Test capture
            image = webcam_device.read()
            log("test capture using %s: %s", webcam_device, image)
            assert image is not None, "no device, no permission, or no data"
            w, h = image.get_width(), image.get_height()
            pixel_format = webcam_device.pixel_format

            mmap_sub = self.get_subsystem("mmap")
            mmap_write_area = mmap_sub.mmap_write_area if mmap_sub else None
            if mmap_write_area and mmap_write_area.enabled:
                target_formats = self.server_rgb_formats
            else:
                target_formats = PIL_FORMATS

            if pixel_format not in target_formats:
                from xpra.webcam import make_csc
                self.csc = make_csc(pixel_format, w, h, target_formats)

            if mmap_write_area and mmap_write_area.enabled:
                self.encoding = "mmap"
            else:
                from xpra.codecs.pillow.encoder import get_encodings
                client_encodings = get_encodings()
                common = [x for x in PREFERRED_ENCODING_ORDER
                          if x in self.server_encodings and x in client_encodings]
                if not common:
                    log.error("Error: no common webcam encodings")
                    log.error(" server supports: %s", csv(self.server_encodings))
                    log.error(" client supports: %s", csv(client_encodings))
                    webcam_device.release()
                    return
                log("webcam common encodings=%s", common)
                self.encoding = common[0]
            log("webcam encoding: %s", self.encoding)

            self.device_no = device_no
            self.device = webcam_device
            self.send("webcam-start", self.device_no, w, h)
            self.webcam_state_changed()
            log("webcam started")
            if self.send_webcam_frame():
                delay = 1000 // WEBCAM_TARGET_FPS
                log("webcam timer with delay=%ims for %i fps target)", delay, WEBCAM_TARGET_FPS)
                self.cancel_webcam_send_timer()
                self.send_timer = self.timeout_add(delay, self.may_send_webcam_frame)
        except Exception as e:
            log.warn("webcam test capture failed: %s", e)
            webcam_device.release()

    def cancel_webcam_send_timer(self) -> None:
        if wst := self.send_timer:
            self.send_timer = 0
            self.source_remove(wst)

    def cancel_webcam_check_ack_timer(self) -> None:
        if wact := self.ack_check_timer:
            self.ack_check_timer = 0
            self.source_remove(wact)

    def webcam_check_acks(self, ack=0) -> None:
        self.ack_check_timer = 0
        log("check_acks: webcam_last_ack=%s", self.last_ack)
        if self.last_ack < ack:
            log.warn("Warning: no acknowledgements received from the server for frame %i, stopping webcam", ack)
            self.stop_sending_webcam()

    def stop_sending_webcam(self) -> None:
        log("stop_sending_webcam()")
        with self.lock:
            self.do_stop_sending_webcam()

    def do_stop_sending_webcam(self) -> None:
        self.cancel_webcam_send_timer()
        self.cancel_webcam_check_ack_timer()
        wd = self.device
        log("do_stop_sending_webcam() device=%s", wd)
        if not wd:
            return
        self.send("webcam-stop", self.device_no)
        assert self.server_enabled
        self.device = None
        self.device_no = -1
        self.frame_no = 0
        self.last_ack = -1
        try:
            wd.release()
        except Exception as e:
            log.error("Error closing webcam device %s: %s", wd, e)
        csc = self.csc
        if csc is not None:
            self.csc = None
            try:
                csc.clean()
            except Exception as e:
                log("error cleaning webcam CSC: %s", e)
        self.webcam_state_changed()

    def may_send_webcam_frame(self) -> bool:
        self.send_timer = 0
        if self.device_no < 0 or not self.device:
            return False
        not_acked = self.frame_no - 1 - self.last_ack
        # not all frames have been acked
        latency = 100
        ping = self.get_subsystem("ping")
        spl = tuple(x for _, x in ping.server_latency) if ping else ()
        if spl:
            latency = int(1000 * sum(spl) / len(spl))
        # how many frames should be in flight
        n = max(1, latency // (1000 // WEBCAM_TARGET_FPS))  # 20fps -> 50ms target between frames
        if not_acked > 0 and not_acked > n:
            log("may_send_webcam_frame() latency=%i, not acked=%i, target=%i - will wait for next ack",
                latency, not_acked, n)
            return False
        log("may_send_webcam_frame() latency=%i, not acked=%i, target=%i - trying to send now", latency, not_acked, n)
        return self.send_webcam_frame()

    def send_webcam_frame(self) -> bool:
        if not self.lock.acquire(False):
            return False
        log("send_webcam_frame() webcam_device=%s", self.device)
        try:
            assert self.device_no >= 0, "device number is not set"
            assert self.device, "no webcam device to capture from"
            encoding = self.encoding
            start = monotonic()
            image = self.device.read()
            assert image is not None, "capture failed"

            # Apply CSC when the device format is not directly usable by the server
            csc = self.csc
            if csc is not None:
                image = csc.convert_image(image)

            pixel_format = image.get_pixel_format()
            w, h = image.get_width(), image.get_height()
            end = monotonic()
            log("webcam frame capture took %ims", (end - start) * 1000)

            options: dict[str, Any] = {}
            if encoding == "mmap":
                mmap_write_area = self.get_subsystem("mmap").mmap_write_area
                options["pixel-format"] = pixel_format
                mmap_data = mmap_write_area.write_data(image.get_pixels())
                log("mmap_write_area=%s, mmap_data=%s", mmap_write_area.get_info(), mmap_data)
                img_data = b""
                options["chunks"] = mmap_data
            else:
                from xpra.codecs.image import to_pil_encoding
                start = monotonic()
                data = to_pil_encoding(image, encoding, True)
                end = monotonic()
                log("webcam frame compression to %s took %ims", encoding, (end - start) * 1000)
                img_data = compression.Compressed(encoding, data)

            frame_no = self.frame_no
            self.frame_no += 1
            self.send("webcam-frame", self.device_no, frame_no, encoding, w, h, img_data, options)
            self.cancel_webcam_check_ack_timer()
            self.ack_check_timer = self.timeout_add(10 * 1000, self.webcam_check_acks)
            return True
        except Exception as e:
            log.error("webcam frame %i failed", self.frame_no, exc_info=True)
            log.error("Error sending webcam frame: %s", e)
            self.stop_sending_webcam()
            summary = "Webcam forwarding has failed"
            body = "The system encountered the following error:\n" + \
                   ("%s\n" % e)
            may_notify_client(self.client, NotificationID.WEBCAM,
                              summary, body, expire_timeout=10 * 1000, icon_name="webcam")
            return False
        finally:
            self.lock.release()

    ######################################################################
    # packet handlers
    def _process_webcam_stop(self, packet: Packet) -> None:
        device_no = packet.get_u64(1)
        log("webcam-stop for device %i", device_no)
        if device_no != self.device_no:
            return
        self.stop_sending_webcam()

    def _process_webcam_ack(self, packet: Packet) -> None:
        log("process_webcam_ack: %s", packet)
        with self.lock:
            if self.device:
                frame_no = packet.get_u64(2)
                self.last_ack = frame_no
                if self.may_send_webcam_frame():
                    self.cancel_webcam_send_timer()
                    delay = 1000 // WEBCAM_TARGET_FPS
                    log("new webcam timer with delay=%ims for %i fps target)", delay, WEBCAM_TARGET_FPS)
                    self.send_timer = self.timeout_add(delay, self.may_send_webcam_frame)

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(*WebcamForwarder.PACKET_TYPES)
