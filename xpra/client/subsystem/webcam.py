# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from time import monotonic
from threading import RLock
from typing import Any
from collections.abc import Sequence

from xpra.log import Logger
from xpra.util.parsing import FALSE_OPTIONS
from xpra.net import compression
from xpra.net.common import Packet
from xpra.os_util import WIN32
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool, OSEnvContext
from xpra.common import may_notify_client
from xpra.constants import NotificationID
from xpra.client.base.stub import StubClientMixin
from xpra.util.thread import start_thread

log = Logger("webcam")

WEBCAM_ALLOW_VIRTUAL = envbool("XPRA_WEBCAM_ALLOW_VIRTUAL", False)
WEBCAM_TARGET_FPS = max(1, min(50, envint("XPRA_WEBCAM_FPS", 20)))


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
        self.webcam_resume_restart = False
        self.webcam_csc = None
        self.server_webcam = False
        self.server_webcam_encodings: Sequence[str] = ()
        self.server_virtual_video_devices = 0
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
        self.server_virtual_video_devices = 0
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
        if isinstance(v, dict):
            cdict = typedict(v)
            self.server_webcam = cdict.boolget("enabled")
            self.server_webcam_encodings = cdict.strtupleget("encodings", ("png", "jpeg"))
            self.server_virtual_video_devices = cdict.intget("devices")
        else:
            # pre v6 / 5.0.2
            self.server_webcam = c.boolget("webcam")
            self.server_webcam_encodings = c.strtupleget("webcam.encodings", ("png", "jpeg"))
            self.server_virtual_video_devices = c.intget("virtual-video-devices")
        log("webcam server support: %s (%i devices, encodings: %s)",
            self.server_webcam, self.server_virtual_video_devices, csv(self.server_webcam_encodings))
        if self.webcam_forwarding and self.server_webcam and self.server_virtual_video_devices > 0:
            if self.webcam_option == "on" or self.webcam_option.find("/dev/video") >= 0:
                self.connect("handshake-complete", self.start_sending_webcam)
        return True

    def suspend_webcam(self, _client) -> None:
        self.webcam_resume_restart = bool(self.webcam_device)
        self.stop_sending_webcam()

    def resume_webcam(self, _client) -> None:
        wrr = self.webcam_resume_restart
        if wrr:
            self.webcam_resume_restart = False
            self.start_sending_webcam()

    def webcam_state_changed(self) -> None:
        self.idle_add(self.emit, "webcam-changed")

    ######################################################################
    def start_sending_webcam(self) -> None:
        if not self.webcam_forwarding:
            return
        with self.webcam_lock:
            with OSEnvContext(LANG="C", LC_ALL="C"):
                available = False
                try:
                    import cv2  # noqa: F401
                    available = True
                except ImportError:
                    pass
                if not available:
                    try:
                        import libcamera  # noqa: F401
                        available = True
                    except ImportError:
                        pass
                if not available:
                    log("init webcam failure: neither cv2 nor libcamera found")
                    if WIN32:
                        log.info("opencv not found, webcam forwarding is not available")
                    self.webcam_forwarding = False
                    return
            if not self.webcam_send_timer:
                start_thread(self.do_start_sending_webcam, "start-sending-webcam",
                             daemon=True, args=(self.webcam_option, ))

    def do_start_sending_webcam(self, device_str: str) -> None:
        assert self.server_webcam
        virt_devices, all_video_devices, non_virtual = {}, {}, {}
        try:
            from xpra.platform.webcam import get_virtual_video_devices, get_all_video_devices
            virt_devices = get_virtual_video_devices()
            all_video_devices = get_all_video_devices()  # pylint: disable=assignment-from-none
            non_virtual = {k: v for k, v in all_video_devices.items() if k not in virt_devices}
            log("virtual video devices=%s", virt_devices)
            log("all_video_devices=%s", all_video_devices)
            log("found %s known non-virtual video devices: %s", len(non_virtual), non_virtual)
        except ImportError as e:
            log("no webcam_util: %s", e)
        log("do_start_sending_webcam(%s)", device_str)

        from xpra.client.webcam import open_camera, make_csc_to_bgrx
        try:
            webcam_device = open_camera(device_str, virt_devices, non_virtual)
        except Exception as e:
            log.warn("Warning: failed to open webcam device %r: %s", device_str, e)
            return

        # Warn and optionally refuse virtual devices on the cv2 path
        from xpra.client.webcam.cv2_camera import CV2Camera
        if isinstance(webcam_device, CV2Camera):
            device_no = webcam_device._device_no
            if device_no in virt_devices:
                log.warn("Warning: video device %s is a virtual device", virt_devices.get(device_no, device_no))
                if WEBCAM_ALLOW_VIRTUAL:
                    log.warn(" environment override - this may hang..")
                else:
                    log.warn(" cowardly refusing to use it")
                    log.warn(" set WEBCAM_ALLOW_VIRTUAL=1 to force enable it")
                    webcam_device.release()
                    return

        self.webcam_frame_no = 0
        try:
            # Test capture
            image = webcam_device.read()
            log("test capture using %s: %s", webcam_device, image)
            assert image is not None, "no device, no permission, or no data"
            w, h = image.get_width(), image.get_height()

            # Set up CSC if the device does not deliver BGRX
            csc = make_csc_to_bgrx(webcam_device.pixel_format, w, h)
            self.webcam_csc = csc

            self.webcam_device_no = getattr(webcam_device, "_device_no", 0)
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
        wst = self.webcam_send_timer
        if wst:
            self.webcam_send_timer = 0
            self.source_remove(wst)

    def cancel_webcam_check_ack_timer(self) -> None:
        wact = self.webcam_ack_check_timer
        if wact:
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
            from xpra.codecs.pillow.encoder import get_encodings
            client_webcam_encodings = get_encodings()
            common_encodings = list(set(self.server_webcam_encodings).intersection(client_webcam_encodings))
            log("common encodings (server=%s, client=%s): %s",
                csv(self.server_encodings), csv(client_webcam_encodings), csv(common_encodings))
            if not common_encodings:
                log.error("Error: cannot send webcam image, no common formats")
                log.error(" the server supports: %s", csv(self.server_webcam_encodings))
                log.error(" the client supports: %s", csv(client_webcam_encodings))
                self.stop_sending_webcam()
                return False
            preferred_order = ["jpeg", "png", "png/L", "png/P", "webp"]
            formats = [x for x in preferred_order if x in common_encodings] + common_encodings
            encoding = formats[0]
            start = monotonic()
            image = self.webcam_device.read()
            assert image is not None, "capture failed"

            # Apply CSC to convert to BGRX if needed
            csc = self.webcam_csc
            if csc is not None:
                image = csc.convert_image(image)

            w, h = image.get_width(), image.get_height()
            end = monotonic()
            log("webcam frame capture took %ims", (end - start) * 1000)

            options: dict[str, Any] = {}
            # Try to use mmap if available
            mmap_write_area = getattr(self, "mmap_write_area", None)
            if mmap_write_area and mmap_write_area.enabled:
                # Convert to BGRX for mmap path (we already have BGRX from the csc above,
                # or BGR from cv2 which we need to convert to BGRX here)
                pixel_format = image.get_pixel_format()
                if pixel_format == "BGR":
                    import cv2
                    import numpy
                    raw = numpy.frombuffer(image.get_pixels(), dtype=numpy.uint8).reshape(h, w, 3)
                    bgrx = cv2.cvtColor(raw, cv2.COLOR_BGR2RGBA)
                    pixel_format = "BGRX"
                    from xpra.codecs.image import ImageWrapper as _IW
                    image = _IW(0, 0, w, h, bgrx.tobytes(), "BGRX", 32, w * 4, planes=_IW.PACKED)
                options["pixel-format"] = pixel_format
                mmap_data = mmap_write_area.write_data(image.get_pixels())
                log("mmap_write_area=%s, mmap_data=%s", self.mmap_write_area.get_info(), mmap_data)
                encoding = "mmap"
                img_data = b""
                options["chunks"] = mmap_data
            else:
                # Encode via Pillow: convert to RGB first
                pixel_format = image.get_pixel_format()
                pixels = image.get_pixels()
                if pixel_format in ("BGR", "BGRX"):
                    import cv2
                    import numpy
                    channels = 3 if pixel_format == "BGR" else 4
                    raw = numpy.frombuffer(pixels, dtype=numpy.uint8).reshape(h, w, channels)
                    if pixel_format == "BGR":
                        rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
                    else:
                        rgb = cv2.cvtColor(raw, cv2.COLOR_BGRA2RGB)
                    pil_data = rgb.tobytes()
                    pil_mode = "RGB"
                else:
                    # For NV12/YUYV that were not CSC'd, fall back to raw bytes
                    pil_data = pixels if isinstance(pixels, bytes) else bytes(pixels)
                    pil_mode = "RGB"
                from PIL import Image
                from io import BytesIO
                pil_image = Image.frombytes(pil_mode, (w, h), pil_data)
                buf = BytesIO()
                pil_image.save(buf, format=encoding)
                data = buf.getvalue()
                buf.close()
                img_data = compression.Compressed(encoding, data)
                start = monotonic()
                end = monotonic()
                log("webcam frame compression to %s took %ims", encoding, (end - start) * 1000)

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
