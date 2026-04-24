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
from xpra.codecs.image import ImageWrapper
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


def save_to_buffer(image: ImageWrapper, encoding: str) -> bytes:
    # Encode via Pillow.
    # webcam_csc guarantees pixel_format is one of PIL_FORMATS.
    pixel_format = image.get_pixel_format()
    w = image.get_width()
    h = image.get_height()
    pixels = image.get_pixels()
    if not isinstance(pixels, bytes):
        pixels = bytes(pixels)
    from PIL import Image
    from io import BytesIO
    if pixel_format == "RGB":
        pil_image = Image.frombytes("RGB", (w, h), pixels)
    elif pixel_format in ("RGBX", "RGBA"):
        pil_image = Image.frombytes("RGBA", (w, h), pixels).convert("RGB")
    elif pixel_format == "BGRX":
        # Pillow can decode BGRX natively via the raw decoder (mode="RGB", rawmode="BGRX")
        pil_image = Image.frombuffer("RGB", (w, h), pixels, "raw", "BGRX", 0, 1)
    else:
        raise ValueError(f"unsupported pixel format for Pillow encoding: {pixel_format!r}")
    start = monotonic()
    buf = BytesIO()
    pil_image.save(buf, format=encoding)
    data = buf.getvalue()
    buf.close()
    end = monotonic()
    log("webcam frame compression to %s took %ims", encoding, (end - start) * 1000)
    return data


def is_available() -> bool:
    with OSEnvContext(LANG="C", LC_ALL="C"):
        if POSIX and not OSX:
            try:
                import libcamera  # noqa: F401
                return True
            except ImportError as e:
                log("is_available() no libcamera: %s", e)
        try:
            import cv2  # noqa: F401
            return True
        except ImportError as e:
            log("is_available() no opencv: %s", e)
        return False


class WebcamForwarder(StubClientMixin):
    """
    Mixin for clients that forward webcams
    """
    PACKET_TYPES = ("webcam-ack", "webcam-stop")
    PREFIX = "webcam"
    __signals__ = ["webcam-changed"]

    def __init__(self):
        # webcam:
        self.webcam_option = ""
        self.webcam_forwarding = False
        self.webcam_device = None
        self.webcam_device_no = -1
        self.webcam_frame_no = 0
        self.webcam_last_ack = -1
        self.webcam_ack_check_timer = 0
        self.webcam_send_timer = 0
        self.webcam_lock = RLock()
        self.webcam_resume_restart = ()
        self.webcam_csc = None
        self.webcam_encoding = ""
        self.server_webcam = False
        self.server_webcam_client_mode = False
        self.server_webcam_encodings: Sequence[str] = ()
        self.server_webcam_rgb_formats: Sequence[str] = ()
        # duplicated from encodings mixin:
        self.server_encodings: Sequence[str] = ()
        if not hasattr(self, "server_ping_latency"):
            from collections import deque
            self.server_ping_latency: deque[tuple[float, float]] = deque(maxlen=1000)

    def cleanup(self) -> None:
        self.stop_sending_webcam()

    def init(self, opts) -> None:
        self.webcam_option = opts.webcam
        self.webcam_forwarding = self.webcam_option.lower() not in FALSE_OPTIONS
        self.server_webcam = False
        log("webcam forwarding: %s", self.webcam_forwarding)

    def load(self) -> None:
        self.connect("suspend", self.suspend_webcam)
        self.connect("resume", self.resume_webcam)

    def get_caps(self) -> dict[str, Any]:
        if not self.webcam_forwarding:
            return {}
        return {"webcam": True}

    def parse_server_capabilities(self, c: typedict) -> bool:
        v = c.get("webcam")
        log("parse_server_capabilities(..) webcam=%s", v)
        if isinstance(v, dict):
            cdict = typedict(v)
            self.server_webcam = cdict.boolget("enabled")
            self.server_webcam_encodings = cdict.strtupleget("encodings", ("png", "jpeg"))
            self.server_webcam_rgb_formats = cdict.strtupleget("rgb-formats", ("BGRX", ))
            self.server_webcam_client_mode = cdict.boolget("client_mode", False)
        elif BACKWARDS_COMPATIBLE:
            # pre v6 / 5.0.2
            self.server_webcam = c.boolget("webcam")
            if self.server_webcam:
                self.server_webcam_encodings = c.strtupleget("webcam.encodings", ("png", "jpeg"))
        log("webcam server support: %s (encodings: %s, rgb-formats=%s, client_mode: %s)",
            self.server_webcam, csv(self.server_webcam_encodings), csv(self.server_webcam_rgb_formats),
            self.server_webcam_client_mode)
        # In client_mode the server may report devices=1 without v4l2, honour that
        if self.webcam_forwarding and self.server_webcam:
            device = self.webcam_option
            if device == "on" or device.find("/dev/video") >= 0:
                try:
                    device_no = int(device.removeprefix("/dev/video"))
                except ValueError:
                    device_no = 0
                self.connect("handshake-complete", self.start_sending_webcam, device_no, device)
        return True

    def suspend_webcam(self, _client) -> None:
        self.webcam_resume_restart = (self.webcam_device_no, self.webcam_device)
        self.stop_sending_webcam()

    def resume_webcam(self, _client) -> None:
        restart = self.webcam_resume_restart
        if restart:
            self.webcam_resume_restart = ()
            self.start_sending_webcam(*restart)

    def webcam_state_changed(self) -> None:
        self.idle_add(self.emit, "webcam-changed")

    ######################################################################
    def start_sending_webcam(self, device_no: int, device: str) -> None:
        if not self.webcam_forwarding:
            return
        with self.webcam_lock:
            if not is_available():
                log("init webcam failure: neither cv2 nor libcamera found")
                if WIN32 or OSX:
                    log.info("opencv not found, webcam forwarding is not available")
                self.webcam_forwarding = False
                return
            if not self.webcam_send_timer:
                start_thread(self.do_start_sending_webcam, "start-sending-webcam",
                             daemon=True, args=(device_no, device, ))

    def do_start_sending_webcam(self, device_no: int, device: str) -> None:
        log("do_start_sending_webcam(%s, %s)", device_no, device)
        assert self.server_webcam
        from xpra.webcam import open_camera
        try:
            webcam_device = open_camera(device)
        except Exception as e:
            log("open_camera(%s)", device, exc_info=True)
            log.error("Error: failed to open webcam device %r: %s", device, e)
            return
        if webcam_device is None:
            return

        self.webcam_frame_no = 0
        try:
            # Test capture
            image = webcam_device.read()
            log("test capture using %s: %s", webcam_device, image)
            assert image is not None, "no device, no permission, or no data"
            w, h = image.get_width(), image.get_height()
            pixel_format = webcam_device.pixel_format

            mmap_write_area = getattr(self, "mmap_write_area", None)
            if mmap_write_area and mmap_write_area.enabled:
                target_formats = self.server_webcam_rgb_formats
            else:
                target_formats = PIL_FORMATS

            if pixel_format not in target_formats:
                from xpra.webcam import make_csc
                self.webcam_csc = make_csc(pixel_format, w, h, target_formats)

            if mmap_write_area and mmap_write_area.enabled:
                self.webcam_encoding = "mmap"
            else:
                from xpra.codecs.pillow.encoder import get_encodings
                client_encodings = get_encodings()
                common = [x for x in PREFERRED_ENCODING_ORDER
                          if x in self.server_webcam_encodings and x in client_encodings]
                if not common:
                    log.error("Error: no common webcam encodings")
                    log.error(" server supports: %s", csv(self.server_webcam_encodings))
                    log.error(" client supports: %s", csv(client_encodings))
                    webcam_device.release()
                    return
                log("webcam common encodings=%s", common)
                self.webcam_encoding = common[0]
            log("webcam encoding: %s", self.webcam_encoding)

            self.webcam_device_no = device_no
            self.webcam_device = webcam_device
            self.send("webcam-start", self.webcam_device_no, w, h)
            self.webcam_state_changed()
            log("webcam started")
            if self.send_webcam_frame():
                delay = 1000 // WEBCAM_TARGET_FPS
                log("webcam timer with delay=%ims for %i fps target)", delay, WEBCAM_TARGET_FPS)
                self.cancel_webcam_send_timer()
                self.webcam_send_timer = self.timeout_add(delay, self.may_send_webcam_frame)
        except Exception as e:
            log.warn("webcam test capture failed: %s", e)
            webcam_device.release()

    def cancel_webcam_send_timer(self) -> None:
        if wst := self.webcam_send_timer:
            self.webcam_send_timer = 0
            self.source_remove(wst)

    def cancel_webcam_check_ack_timer(self) -> None:
        if wact := self.webcam_ack_check_timer:
            self.webcam_ack_check_timer = 0
            self.source_remove(wact)

    def webcam_check_acks(self, ack=0) -> None:
        self.webcam_ack_check_timer = 0
        log("check_acks: webcam_last_ack=%s", self.webcam_last_ack)
        if self.webcam_last_ack < ack:
            log.warn("Warning: no acknowledgements received from the server for frame %i, stopping webcam", ack)
            self.stop_sending_webcam()

    def stop_sending_webcam(self) -> None:
        log("stop_sending_webcam()")
        with self.webcam_lock:
            self.do_stop_sending_webcam()

    def do_stop_sending_webcam(self) -> None:
        self.cancel_webcam_send_timer()
        self.cancel_webcam_check_ack_timer()
        wd = self.webcam_device
        log("do_stop_sending_webcam() device=%s", wd)
        if not wd:
            return
        self.send("webcam-stop", self.webcam_device_no)
        assert self.server_webcam
        self.webcam_device = None
        self.webcam_device_no = -1
        self.webcam_frame_no = 0
        self.webcam_last_ack = -1
        try:
            wd.release()
        except Exception as e:
            log.error("Error closing webcam device %s: %s", wd, e)
        csc = self.webcam_csc
        if csc is not None:
            self.webcam_csc = None
            try:
                csc.clean()
            except Exception as e:
                log("error cleaning webcam CSC: %s", e)
        self.webcam_state_changed()

    def may_send_webcam_frame(self) -> bool:
        self.webcam_send_timer = 0
        if self.webcam_device_no < 0 or not self.webcam_device:
            return False
        not_acked = self.webcam_frame_no - 1 - self.webcam_last_ack
        # not all frames have been acked
        latency = 100
        spl = tuple(x for _, x in self.server_ping_latency)
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
        if not self.webcam_lock.acquire(False):
            return False
        log("send_webcam_frame() webcam_device=%s", self.webcam_device)
        try:
            assert self.webcam_device_no >= 0, "device number is not set"
            assert self.webcam_device, "no webcam device to capture from"
            encoding = self.webcam_encoding
            start = monotonic()
            image = self.webcam_device.read()
            assert image is not None, "capture failed"

            # Apply CSC when the device format is not directly usable by the server
            csc = self.webcam_csc
            if csc is not None:
                image = csc.convert_image(image)

            pixel_format = image.get_pixel_format()
            w, h = image.get_width(), image.get_height()
            end = monotonic()
            log("webcam frame capture took %ims", (end - start) * 1000)

            options: dict[str, Any] = {}
            if encoding == "mmap":
                from xpra.client.subsystem.mmap import MmapClient
                assert isinstance(self, MmapClient)
                mmap_write_area = self.mmap_write_area
                options["pixel-format"] = pixel_format
                mmap_data = mmap_write_area.write_data(image.get_pixels())
                log("mmap_write_area=%s, mmap_data=%s", mmap_write_area.get_info(), mmap_data)
                img_data = b""
                options["chunks"] = mmap_data
            else:
                data = save_to_buffer(image, encoding)
                img_data = compression.Compressed(encoding, data)

            frame_no = self.webcam_frame_no
            self.webcam_frame_no += 1
            self.send("webcam-frame", self.webcam_device_no, frame_no, encoding,
                      w, h, img_data, options)
            self.cancel_webcam_check_ack_timer()
            self.webcam_ack_check_timer = self.timeout_add(10 * 1000, self.webcam_check_acks)
            return True
        except Exception as e:
            log.error("webcam frame %i failed", self.webcam_frame_no, exc_info=True)
            log.error("Error sending webcam frame: %s", e)
            self.stop_sending_webcam()
            summary = "Webcam forwarding has failed"
            body = "The system encountered the following error:\n" + \
                   ("%s\n" % e)
            may_notify_client(self, NotificationID.WEBCAM,
                              summary, body, expire_timeout=10 * 1000, icon_name="webcam")
            return False
        finally:
            self.webcam_lock.release()

    ######################################################################
    # packet handlers
    def _process_webcam_stop(self, packet: Packet) -> None:
        device_no = packet.get_u64(1)
        log("webcam-stop for device %i", device_no)
        if device_no != self.webcam_device_no:
            return
        self.stop_sending_webcam()

    def _process_webcam_ack(self, packet: Packet) -> None:
        log("process_webcam_ack: %s", packet)
        with self.webcam_lock:
            if self.webcam_device:
                frame_no = packet.get_u64(2)
                self.webcam_last_ack = frame_no
                if self.may_send_webcam_frame():
                    self.cancel_webcam_send_timer()
                    delay = 1000 // WEBCAM_TARGET_FPS
                    log("new webcam timer with delay=%ims for %i fps target)", delay, WEBCAM_TARGET_FPS)
                    self.webcam_send_timer = self.timeout_add(delay, self.may_send_webcam_frame)

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(*WebcamForwarder.PACKET_TYPES)
