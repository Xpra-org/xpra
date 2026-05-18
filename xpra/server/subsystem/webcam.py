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

    def __init__(self, server=None):
        StubServerMixin.__init__(self, server)
        self.device = ""
        self.encodings: Sequence[str] = ()
        self.enabled = False
        self.virtual = False
        self.virtual_video_devices: int = 0
        self.client_mode: bool = False
        self.rgb_formats = "RGB", "BGR", "BGRX"
        # device_id → proto — populated when webcam-client connects
        self.client_connections: dict[int, Any] = {}
        # device_id → Popen
        self.client_processes: dict[int, Popen] = {}

    def init(self, opts) -> None:
        self.enabled = opts.webcam.lower() not in FALSE_OPTIONS
        if not self.enabled:
            return
        self.virtual = True
        self.client_mode = True
        if os.path.isabs(opts.webcam):
            self.device = opts.webcam
            self.client_mode = False
        elif opts.webcam.lower() == "window":
            self.virtual = False
        elif opts.webcam.lower() in ("v4l2", "virtual"):
            self.client_mode = False
        log("init(..) webcam=%s, virtual=%s, client-mode=%s", opts.webcam, self.virtual, self.client_mode)

    def setup(self) -> None:
        self.init_webcam()

    def get_server_features(self, _source) -> dict[str, Any]:
        return {
            WebcamServer.PREFIX: {
                "enabled": self.enabled,
                "encodings": self.encodings,
                "rgb-formats": self.rgb_formats,
                "virtual": self.virtual,
                "devices": self.virtual_video_devices,
                "client_mode": self.client_mode,
            },
        }

    def get_info(self, _proto) -> dict[str, Any]:
        info: dict[str, Any] = {
            "enabled": self.enabled,
        }
        if self.enabled:
            info.update({
                "encodings": self.encodings,
                "rgb-formats": self.rgb_formats,
                "virtual": self.virtual,
                "devices": self.virtual_video_devices,
                "client_mode": self.client_mode,
            })
        if self.device:
            info["device"] = self.device
        return {WebcamServer.PREFIX: info}

    def init_webcam(self) -> None:
        if not self.enabled:
            return
        try:
            # pylint: disable=import-outside-toplevel
            from xpra.codecs.pillow.decoder import get_encodings
        except ImportError:
            log("init_webcam()", exc_info=True)
            log.info("webcam forwarding cannot be enabled without the pillow decoder")
            self.enabled = False
            return
        try:
            self.encodings = tuple(x for x in ("png", "jpeg", "webp") if x in get_encodings())
        except Exception as e:
            log("init_webcam()", exc_info=True)
            log.error("Error: webcam forwarding disabled:")
            log.estr(e)
            self.enabled = False
            return
        if self.device:
            self.virtual_video_devices = 1
            return
        if self.client_mode:
            log.info("webcam window mode enabled")
        if self.virtual:
            self.virtual_video_devices = init_virtual_video_devices()
            self.virtual = bool(self.virtual_video_devices)
            if not self.virtual_video_devices and not self.client_mode:
                log.info("no v4l2 virtual devices found")
            else:
                log.info("found %i virtual video devices for webcam forwarding", self.virtual_video_devices)
        self.enabled = self.virtual or self.client_mode
        log("init_webcam() virtual=%s (%i devices), client-mode=%s",
            self.virtual, self.virtual_video_devices, self.client_mode)

    # ------------------------------------------------------------------
    # Webcam-client connection attach (regular client flow)

    def add_new_client(self, ss, c: typedict) -> None:
        wc = c.dictget("webcam-client")
        if wc:
            device_id = typedict(wc).intget("device", -1)
            self.add_new_webcam_client(ss, device_id)

    def add_new_webcam_client(self, ss, device_id: int) -> None:
        proto = ss.protocol
        log("webcam-client connection (device_id=%i) from %s", device_id, proto)
        for other_ss in self.get_sources_by_type(WebcamConnection, ss):
            pending = other_ss.webcam_pending_clients
            if not pending:
                continue
            if device_id >= 0:
                if device_id not in pending:
                    continue
                matched = device_id
            else:
                matched = next(iter(pending))
            if not other_ss.attach_webcam_client(matched, ss):
                continue
            self.client_connections[matched] = proto
            proto.large_packets.append("webcam-frame")
            log("webcam-client connection accepted for device %i", matched)
            return
        log.warn("Warning: no webcam device available (requested device_id=%i)", device_id)
        self.server.disconnect_client(proto, "no webcam device available")

    def cleanup_protocol(self, protocol) -> None:
        for device_id, proto in tuple(self.client_connections.items()):
            if proto is protocol:
                self.client_connections.pop(device_id, None)

    # ------------------------------------------------------------------
    # Packet handlers

    def _process_webcam_start(self, proto, packet: Packet) -> None:
        if self.server.readonly:
            return
        assert self.enabled
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for webcam start")
            return
        device_id = packet.get_i64(1)
        w = packet.get_u16(2)
        h = packet.get_u16(3)
        if self.client_mode:
            ss.request_webcam_client_forwarder(device_id, w, h)
            self._spawn_webcam_client(ss, device_id, w, h)
        else:
            ss.start_virtual_webcam(device_id, w, h)

    def _spawn_webcam_client(self, ss, device_id: int, w: int, h: int) -> None:
        socket_path = ""
        if self.server.unix_socket_paths:
            socket_path = self.server.unix_socket_paths[0]
        if not socket_path:
            log.warn("Warning: cannot spawn webcam-client: no unix socket path available")
            ss.send_webcam_stop(device_id, "no server socket available")
            return

        from xpra.platform.paths import get_xpra_command
        uri = f"socket://{socket_path}?device={device_id}"
        cmd = get_xpra_command() + ["webcam-client", uri]
        if is_debug_enabled("webcam"):
            cmd.append("--debug=webcam")
        env = self.server.get_child_env()
        log("spawning webcam-client: %s", cmd)
        log(" with env=%s", env)
        try:
            proc = Popen(cmd, env=env, close_fds=True)
            self.client_processes[device_id] = proc
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
        if self.server.readonly:
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
        if proto := self.client_connections.pop(device_id, None):
            proto.close(reason)
        if proc := self.client_processes.pop(device_id, None):
            try:
                proc.terminate()
            except OSError:
                pass

    def _process_webcam_frame(self, proto, packet: Packet) -> None:
        if self.server.readonly:
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
        if self.enabled:
            self.add_packets("webcam-start", "webcam-stop", "webcam-frame")
