# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
import os.path
from subprocess import Popen
from typing import Any
from collections.abc import Sequence

from xpra.os_util import OSX, POSIX
from xpra.server.common import get_sources_by_type
from xpra.server.source.webcam import WebcamConnection
from xpra.util.objects import typedict
from xpra.net.common import Packet
from xpra.util.parsing import FALSE_OPTIONS
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger, is_debug_enabled

log = Logger("webcam")


def init_virtual_video_devices() -> int:
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
        from xpra.platform.posix.webcam import get_virtual_video_devices
    except ImportError as e:
        log.warn("Warning: cannot load webcam components")
        log.warn(" %s", e)
        log.warn(" webcam forwarding disabled")
        return 0
    devices = get_virtual_video_devices()
    log.info("found %i virtual video devices for webcam forwarding", len(devices))
    return len(devices)


class WebcamServer(StubServerMixin):
    toggle_features = ("webcam",)
    """
    Mixin for servers that handle webcam forwarding.
    Supports two modes:
    - v4l2 mode: frames are written into a virtual video device (requires v4l2loopback)
    - client_mode: a webcam-client subprocess is spawned; frames are forwarded to it directly
    """
    PREFIX = "webcam"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.webcam_device = ""
        self.webcam_encodings: Sequence[str] = ()
        self.webcam_enabled = False
        self.webcam_virtual = False
        self.webcam_virtual_video_devices: int = 0
        self.webcam_client_mode: bool = False
        self.webcam_rgb_formats = "RGB", "BGR", "BGRX"
        # device_id → proto — populated when webcam-client connects
        self.webcam_client_connections: dict[int, Any] = {}
        # device_id → Popen
        self.webcam_client_processes: dict[int, Popen] = {}

    def init(self, opts) -> None:
        self.webcam_enabled = opts.webcam.lower() not in FALSE_OPTIONS
        if not self.webcam_enabled:
            return
        self.webcam_virtual = True
        self.webcam_client_mode = True
        if os.path.isabs(opts.webcam):
            self.webcam_device = opts.webcam
            self.webcam_client_mode = False
        elif opts.webcam.lower() == "window":
            self.webcam_virtual = False
        elif opts.webcam.lower() in ("v4l2", "virtual"):
            self.webcam_client_mode = False
        log("init(..) webcam=%s, virtual=%s, client-mode=%s", opts.webcam, self.webcam_virtual, self.webcam_client_mode)

    def init_state(self) -> None:
        # duplicated
        self.readonly = False

    def setup(self) -> None:
        self.init_webcam()
        if self.webcam_client_mode:
            self.hello_request_handlers["webcam-client"] = self._handle_hello_webcam_client

    def get_server_features(self, _source) -> dict[str, Any]:
        return {
            WebcamServer.PREFIX: {
                "enabled": self.webcam_enabled,
                "encodings": self.webcam_encodings,
                "rgb-formats": self.webcam_rgb_formats,
                "virtual": self.webcam_virtual,
                "devices": self.webcam_virtual_video_devices,
                "client_mode": self.webcam_client_mode,
            },
        }

    def get_info(self, _proto) -> dict[str, Any]:
        info: dict[str, Any] = {
            "enabled": self.webcam_enabled,
        }
        if self.webcam_enabled:
            info.update({
                "encodings": self.webcam_encodings,
                "rgb-formats": self.webcam_rgb_formats,
                "virtual": self.webcam_virtual,
                "devices": self.webcam_virtual_video_devices,
                "client_mode": self.webcam_client_mode,
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
            return
        if self.webcam_device:
            self.webcam_virtual_video_devices = 1
            return
        if self.webcam_client_mode:
            log.info("webcam window mode enabled")
        if self.webcam_virtual:
            self.webcam_virtual_video_devices = init_virtual_video_devices()
            self.webcam_virtual = bool(self.webcam_virtual_video_devices)
            if not self.webcam_virtual_video_devices:
                log.info("no v4l2 virtual devices found")
        self.webcam_enabled = self.webcam_virtual or self.webcam_client_mode
        log("init_webcam() virtual=%s (%i devices), client-mode=%s",
            self.webcam_virtual, self.webcam_virtual_video_devices, self.webcam_client_mode)

    # ------------------------------------------------------------------
    # Hello handler for the webcam-client subprocess

    def _handle_hello_webcam_client(self, proto, caps: typedict) -> bool:
        wc = caps.dictget("webcam-client") or {}
        device_id = typedict(wc).intget("device", -1)
        log("_handle_hello_webcam_client: device_id=%i", device_id)
        webcam_clients = get_sources_by_type(self, WebcamConnection)
        for ss in webcam_clients:
            devices = getattr(ss, "webcam_forwarding_devices", {})
            if not devices:
                continue
            if device_id >= 0:
                if device_id not in devices:
                    continue
                matched = device_id
            else:
                matched = next(iter(devices))
            self.webcam_client_connections[matched] = proto
            ss.set_webcam_client_proto(matched, proto)
            proto.large_packets.append("webcam-frame")
            proto.send_now(Packet("hello", {"webcam": True}))
            log("webcam-client connection accepted for device %i", matched)
            return True
        log.warn("Warning: no webcam device available (requested device_id=%i)", device_id)
        self.disconnect_client(proto, "no webcam device available")
        return True

    # ------------------------------------------------------------------
    # Packet handlers

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
        if self.webcam_client_mode:
            ss.setup_webcam_client_forwarder(device_id, w, h)
            self._spawn_webcam_client(ss, device_id, w, h)
        else:
            ss.start_virtual_webcam(device_id, w, h)

    def _spawn_webcam_client(self, ss, device_id: int, w: int, h: int) -> None:
        socket_path = ""
        if self.unix_socket_paths:
            socket_path = self.unix_socket_paths[0]
        if not socket_path:
            log.warn("Warning: cannot spawn webcam-client: no unix socket path available")
            ss.send_webcam_stop(device_id, "no server socket available")
            return

        from xpra.platform.paths import get_xpra_command
        uri = f"socket://{socket_path}?device={device_id}"
        cmd = get_xpra_command() + ["webcam-client", uri]
        if is_debug_enabled("webcam"):
            cmd.append("--debug=webcam")
        env = self.get_child_env()
        log("spawning webcam-client: %s", cmd)
        log(" with env=%s", env)
        try:
            proc = Popen(cmd, env=env, close_fds=True)
            self.webcam_client_processes[device_id] = proc
            log("webcam-client process spawned: pid=%i", proc.pid)

            def on_webcam_client_exit(_proc_info) -> None:
                log("webcam-client process for device %i exited", device_id)
                self._cleanup_webcam_client(device_id, "exit")
                ss.send_webcam_stop(device_id, "webcam-client exited")

            from xpra.util.child_reaper import get_child_reaper
            get_child_reaper().add_process(proc, f"webcam-client-{device_id}", cmd,
                                           ignore=False, forget=True, callback=on_webcam_client_exit)
        except Exception as e:
            log.error("Error: failed to spawn webcam-client process: %s", e)
            ss.send_webcam_stop(device_id, f"spawn failed: {e}")

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
        self._cleanup_webcam_client(device_id, "stop")

    def _cleanup_webcam_client(self, device_id: int, reason: str) -> None:
        if proto := self.webcam_client_connections.pop(device_id, None):
            proto.close(reason)
        if proc := self.webcam_client_processes.pop(device_id, None):
            try:
                proc.terminate()
            except OSError:
                pass

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
