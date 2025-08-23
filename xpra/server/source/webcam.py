# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.common import noop
from xpra.os_util import POSIX, OSX
from xpra.util.objects import typedict
from xpra.util.env import envint
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("webcam")

MAX_WEBCAM_DEVICES = envint("XPRA_MAX_WEBCAM_DEVICES", 1)


def valid_encodings(args: Sequence[str]) -> list[str]:
    # ensure that the encodings specified can be validated using HEADERS
    try:
        from xpra.codecs.pillow.decoder import HEADERS  # pylint: disable=import-outside-toplevel
    except ImportError:
        return []
    encodings = []
    for x in args:
        if x not in HEADERS.values():
            log.warn("Warning: %s is not supported for webcam forwarding", x)
        else:
            encodings.append(x)
    return encodings


def find_csc_spec(src_format: str, dst_format: str):
    from xpra.codecs.video import getVideoHelper
    specs = getVideoHelper().get_csc_specs(src_format).get(dst_format, ())
    log.error(f"{specs=}")
    for spec in specs:
        if src_format not in spec.input_colorspace:
            continue
        if dst_format not in spec.output_colorspaces:
            continue
        return spec
    raise ValueError("cannot convert %r to %r", src_format, dst_format)


class WebcamConnection(StubClientConnection):
    """
    Handle webcam forwarding.
    """

    PREFIX = "webcam"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        if not caps.boolget(WebcamConnection.PREFIX):
            return False
        try:
            from xpra.codecs.pillow.decoder import HEADERS  # pylint: disable=import-outside-toplevel
            assert HEADERS
        except ImportError:
            return False
        return True

    def __init__(self):
        super().__init__()
        self.webcam_enabled = False
        self.webcam_device = None
        self.webcam_encodings = []

    def init_from(self, _protocol, server) -> None:
        self.webcam_enabled = server.webcam_enabled
        self.webcam_device = server.webcam_device
        self.webcam_encodings = valid_encodings(server.webcam_encodings)
        log("WebcamMixin: enabled=%s, device=%s, encodings=%s",
            self.webcam_enabled, self.webcam_device, self.webcam_encodings)

    def init_state(self) -> None:
        # for each webcam device_id, the actual device used
        self.webcam_forwarding_devices: dict = {}

    def cleanup(self) -> None:
        self.stop_all_virtual_webcams()

    def get_info(self) -> dict[str, Any]:
        return {
            WebcamConnection.PREFIX: {
                "encodings": self.webcam_encodings,
                "active-devices": len(self.webcam_forwarding_devices),
            }
        }

    def get_device_options(self, device_id: int) -> dict[Any, Any]:  # pylint: disable=unused-argument
        if not POSIX or OSX or not self.webcam_enabled:
            return {}
        if self.webcam_device:
            # use the device specified:
            return {
                0: {
                    "device": self.webcam_device,
                },
            }
        from xpra.platform.posix.webcam import get_virtual_video_devices  # pylint: disable=import-outside-toplevel
        return get_virtual_video_devices()

    def send_webcam_ack(self, device, frame: int, *args) -> None:
        self.send_async("webcam-ack", device, frame, *args)

    def send_webcam_stop(self, device, message) -> None:
        self.send_async("webcam-stop", device, message)

    def start_virtual_webcam(self, device_id, w: int, h: int) -> bool:
        log("start_virtual_webcam%s", (device_id, w, h))
        assert w > 0 and h > 0
        webcam = self.webcam_forwarding_devices.get(device_id)
        if webcam:
            log.warn("Warning: virtual webcam device %s already in use,", device_id)
            log.warn(" stopping it first")
            self.stop_virtual_webcam(device_id)

        def fail(msg) -> None:
            log.error("Error: cannot start webcam forwarding")
            log.error(" %s", msg)
            self.send_webcam_stop(device_id, msg)

        if not self.webcam_enabled:
            fail("webcam forwarding is disabled")
            return False
        devices = self.get_device_options(device_id)
        if not devices:
            fail("no virtual devices found")
            return False
        if len(self.webcam_forwarding_devices) > MAX_WEBCAM_DEVICES:
            ndev = len(self.webcam_forwarding_devices)
            fail(f"too many virtual devices are already in use: {ndev}")
            return False
        errs: dict[str, str] = {}
        for vid, device_info in devices.items():
            log("trying device %s: %s", vid, device_info)
            device_str = device_info.get("device")
            try:
                # pylint: disable=import-outside-toplevel
                from xpra.codecs.v4l2.virtual import VirtualWebcam, get_input_colorspaces
                in_cs = get_input_colorspaces()
                p = VirtualWebcam()
                src_format = in_cs[0]
                p.init_context(w, h, w, src_format, device_str)
                self.webcam_forwarding_devices[device_id] = p
                log.info("webcam forwarding using %s", device_str)
                # this tell the client to start sending, and the size to use - which may have changed:
                self.send_webcam_ack(device_id, 0, p.get_width(), p.get_height())
                return True
            except Exception as e:
                log.error("Error: failed to start virtual webcam")
                log.error(" using device %s: %s", vid, device_info, exc_info=True)
                errs[device_str] = str(e)
                del e
        fail("all devices failed")
        if len(errs) > 1:
            log.error(" tried %i devices:", len(errs))
        for device_str, err in errs.items():
            log.error(" %s : %s", device_str, err)
        return False

    def stop_all_virtual_webcams(self) -> None:
        log("stop_all_virtual_webcams() stopping: %s", self.webcam_forwarding_devices)
        for device_id in tuple(self.webcam_forwarding_devices.keys()):
            self.stop_virtual_webcam(device_id)

    def stop_virtual_webcam(self, device_id, message="") -> None:
        webcam = self.webcam_forwarding_devices.pop(device_id, None)
        log("stop_virtual_webcam(%s, %s) webcam=%s", device_id, message, webcam)
        if not webcam:
            log.warn("Warning: cannot stop webcam device %s: no such context!", device_id)
            return
        try:
            webcam.clean()
        except Exception as e:
            log.error("Error stopping virtual webcam device: %s", e)
            log("%s.clean()", exc_info=True)

    def process_webcam_frame(self, device_id, frame_no: int, encoding: str, w: int, h: int, data, options: dict) -> bool:
        webcam = self.webcam_forwarding_devices.get(device_id)
        log("process_webcam_frame: device %s, frame no %i: %s %ix%i, %i bytes, options=%s, webcam=%s",
            device_id, frame_no, encoding, w, h, len(data), options, webcam)
        if not (encoding and w and h and (data or (encoding == "mmap" and options))):
            log.error("Error: webcam frame data is incomplete")
            self.send_webcam_stop(device_id, "incomplete frame data")
            return False
        if not webcam:
            log.error("Error: webcam forwarding is not active, dropping frame")
            self.send_webcam_stop(device_id, "not started")
            return False
        free = noop
        try:
            if encoding == "mmap":
                chunks = options.pop("chunks", ())
                mmap_read_area = getattr(self, "mmap_read_area", None)
                assert mmap_read_area, "no mmap read area!"
                assert self.mmap_supported, "mmap is not supported, yet the client used it!?"
                pixels, free = mmap_read_area.mmap_read(*chunks)
                rgb_pixel_format = options.get("pixel-format", "BGRX")
            else:
                # pylint: disable=import-outside-toplevel
                from xpra.codecs.pillow.decoder import open_only
                if encoding not in self.webcam_encodings:
                    raise ValueError(f"invalid encoding specified: {encoding} (must be one of {self.webcam_encodings})")
                img = open_only(data, (encoding,))
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                pixels = img.tobytes("raw", "RGBA")
                rgb_pixel_format = "BGRX"

            from xpra.codecs.image import ImageWrapper
            bgrx_image = ImageWrapper(0, 0, w, h, pixels, rgb_pixel_format, 32, w * 4, planes=ImageWrapper.PACKED)
            src_format = webcam.get_src_format()
            if not src_format:
                log("no webcam src format")
                # closed / closing
                return False
            try:
                csc_spec = find_csc_spec(rgb_pixel_format, src_format)
            except ValueError as e:
                message = f"cannot convert {rgb_pixel_format!r} to {src_format!r}: {e}"
                log(f"Warning: {message}")
                self.send_webcam_stop(device_id, message)
                return False
            tw = webcam.get_width()
            th = webcam.get_height()
            csc = csc_spec.codec_class()
            csc.init_context(w, h, rgb_pixel_format, tw, th, src_format, typedict())
            image = csc.convert_image(bgrx_image)
            webcam.push_image(image)
            # tell the client all is good:
            self.send_webcam_ack(device_id, frame_no)
            return True
        except Exception as e:
            log("error on %ix%i frame %i using encoding %s", w, h, frame_no, encoding, exc_info=True)
            log.error("Error processing webcam frame:")
            msg = str(e)
            if not msg:
                msg = "unknown error"
                log.error(f" {webcam} error", exc_info=True)
            log.error(" %s", msg)
            self.send_webcam_stop(device_id, msg)
            self.stop_virtual_webcam(device_id)
            return False
        finally:
            free()
