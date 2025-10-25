#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import random
from dbus.types import UInt32
from dbus.types import Dictionary
from typing import Any

from xpra.exit_codes import ExitCode
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.common import NotificationID, ConnectionMessage
from xpra.dbus.helper import dbus_to_native
from xpra.codecs.gstreamer.capture import Capture, capture_and_encode
from xpra.gstreamer.common import get_element_str
from xpra.codecs.image import ImageWrapper
from xpra.server.shadow.root_window_model import CaptureWindowModel
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.platform.posix.fd_portal import (
    SCREENCAST_IFACE, PORTAL_SESSION_INTERFACE,
    dbus_sender_name,
    get_portal_interface, get_session_interface,
    screenscast_dbus_call, remotedesktop_dbus_call,
    AvailableSourceTypes, AvailableDeviceTypes,
)
from xpra.log import Logger

log = Logger("shadow")

session_counter: int = random.randint(0, 2 ** 24)

VIDEO_MODE = envbool("XPRA_PIPEWIRE_VIDEO_MODE", True)
VIDEO_MODE_ENCODINGS = os.environ.get("XPRA_PIPEWIRE_VIDEO_ENCODINGS", "h264,vp8,vp9,av1").split(",")


class PipewireWindowModel(CaptureWindowModel):
    __slots__ = ("pipewire_id", "pipewire_props")

    def __init__(self, capture, title: str, geometry, node_id: int, props: typedict):
        super().__init__(capture=capture, title=title, geometry=geometry)
        self.pipewire_id = node_id
        self.pipewire_props = props


class PortalShadow(GTKShadowServerBase):
    def __init__(self, attrs: dict[str, str]):
        # we're not using X11, so no need for this check:
        os.environ["XPRA_UI_THREAD_CHECK"] = "0"
        os.environ["XPRA_NOX11"] = "1"
        GTKShadowServerBase.__init__(self, attrs)
        self.session = None
        self.session_type = "portal shadow"
        self.session_path: str = ""
        self.session_handle: str = ""
        self.authenticating_client = None
        self.capture: Capture | None = None
        self.portal_interface = get_portal_interface()
        self.input_devices_count = 0
        log(f"PortalShadow({attrs}) portal_interface={self.portal_interface}")

    def notify_new_user(self, ss) -> None:
        log("notify_new_user() start capture")
        super().notify_new_user(ss)
        if not self._window_to_id:
            self.authenticating_client = ss
            self.create_session()

    def last_client_exited(self) -> None:
        super().last_client_exited()
        self.stop_capture()
        self.stop_session()

    def client_auth_error(self, message: str) -> None:
        self.disconnect_authenticating_client(ConnectionMessage.AUTHENTICATION_FAILED, message)

    def disconnect_authenticating_client(self, reason: ConnectionMessage, message: str) -> None:
        ac = self.authenticating_client
        if ac:
            self.authenticating_client = None
            self.disconnect_protocol(ac.protocol, reason, message)
            self.cleanup_source(ac)

    def make_capture_window_models(self) -> list:
        log("make_capture_window_models()")
        return []

    def makeDynamicWindowModels(self) -> list:
        log("makeDynamicWindowModels()")
        return []

    def set_keymap(self, server_source, force=False) -> None:
        raise NotImplementedError()

    def start_refresh(self, wid: int) -> None:
        log(f"start_refresh({wid:#x})")

    def setup_capture(self) -> None:
        """
        this method is empty because the capture cannot be created without user interaction,
        this is done in `create_session` instead.
        """

    def stop_capture(self) -> None:
        c = self.capture
        if c:
            self.capture = None
            c.clean()

    def cleanup(self) -> None:
        GTKShadowServerBase.cleanup(self)
        self.portal_interface = None

    def stop_session(self) -> None:
        s = self.session
        if not s:
            return
        self.session = None
        # https://gitlab.gnome.org/-/snippets/1122
        log(f"trying to close the session {s}")
        try:
            s.Close(dbus_interface=PORTAL_SESSION_INTERFACE)
        except Exception as e:
            log(f"ignoring error closing session {s}: {e}")

    def create_session(self) -> None:
        global session_counter
        session_counter += 1
        token = f"u{session_counter}"
        self.session_path = f"/org/freedesktop/portal/desktop/session/{dbus_sender_name}/{token}"
        options: dict[str, Any] = {
            "session_handle_token": token,
        }
        log(f"create_session() session_counter={session_counter}")
        remotedesktop_dbus_call(
            self.portal_interface.CreateSession,
            self.on_create_session_response,
            options=options)

    def on_create_session_response(self, response, results) -> None:
        r = int(response)
        res = typedict(dbus_to_native(results))
        if r:
            log("on_create_session_response%s", (response, results))
            log.error(f"Error {r} creating the session")
            log.error(" session access may have been denied")
            self.client_auth_error("session not created")
            return
        self.session_handle = res.strget("session_handle")
        log("on_create_session_response%s session_handle=%s", (r, res), self.session_handle)
        if not self.session_handle:
            log.error("Error: missing session handle creating the session")
            self.client_auth_error("no session handle")
            self.quit(ExitCode.UNSUPPORTED)
            return
        self.session = get_session_interface(self.session_path)
        self.on_session_created()

    def on_session_created(self) -> None:
        self.select_devices()

    def select_devices(self) -> None:
        log("select_devices()")
        options = {
            "types": UInt32(AvailableDeviceTypes.KEYBOARD + AvailableDeviceTypes.POINTER),
        }
        remotedesktop_dbus_call(
            self.portal_interface.SelectDevices,
            self.on_select_devices_response,
            self.session_handle,
            options=options)

    def on_select_devices_response(self, response, results) -> None:
        r = int(response)
        res = dbus_to_native(results)
        if r:
            log("on_select_devices_response%s", (response, results))
            log.error(f"Error {r} selecting screencast devices")
            self.client_auth_error("failed to select devices")
            return
        log(f"on_select_devices_response devices selected, results={res}")
        self.select_sources()

    def select_sources(self) -> None:
        options = {
            "multiple": self.multi_window,
            "types": UInt32(AvailableSourceTypes.WINDOW | AvailableSourceTypes.MONITOR),
        }
        log(f"calling SelectSources with options={options}")
        screenscast_dbus_call(
            self.portal_interface.SelectSources,
            self.on_select_sources_response,
            self.session_handle,
            options=options)

    def on_select_sources_response(self, response, results) -> None:
        r = int(response)
        res = typedict(dbus_to_native(results))
        if r:
            log("on_select_sources_response%s", (response, results))
            log.error(f"Error {r} selecting screencast sources")
            self.client_auth_error("failed to select screencast sources")
            return
        log(f"on_select_sources_response sources selected, results={res}")
        self.portal_start()

    def portal_start(self) -> None:
        log("portal_start()")
        remotedesktop_dbus_call(
            self.portal_interface.Start,
            self.on_start_response,
            self.session_handle,
            "")

    def on_start_response(self, response, results) -> None:
        r = int(response)
        res = typedict(dbus_to_native(results))
        log(f"start response: {res}")
        if r:
            log("on_start_response%s", (response, results))
            log.error(f"Error {r} starting the screen capture")
            self.client_auth_error("cannot start screen capture")
            return
        streams = res.tupleget("streams")
        if not streams:
            log.error("Error: failed to start capture:")
            log.error(" missing streams")
            self.client_auth_error("no streams")
            return
        log(f"on_start_response starting pipewire capture for {streams}")
        for node_id, props in streams:
            self.start_pipewire_capture(int(node_id), typedict(props))
        self.input_devices_count = res.intget("devices")
        if not self.input_devices_count and not self.readonly:
            # ss.notify("", nid, "Xpra", 0, "", title, body, [], {}, 10*1000, icon)
            log.warn("Warning: no input devices,")
            log.warn(" keyboard and pointer events cannot be forwarded")

    def create_capture_pipeline(self, fd: int, node_id: int, w: int, h: int) -> Capture:
        capture_element = get_element_str("pipewiresrc", {
            "fd": fd,
            "path": str(node_id),
            "do-timestamp": True,
        })
        c = self.authenticating_client
        if VIDEO_MODE:
            encoding = getattr(c, "encoding", "")
            encs = getattr(c, "core_encodings", ())
            full_csc_modes = getattr(c, "full_csc_modes", {})
            log(f"create_capture_pipeline() core_encodings={encs}, full_csc_modes={full_csc_modes}")
            pipeline = capture_and_encode(capture_element, encoding, full_csc_modes, w, h)
            if pipeline:
                return pipeline
            log.warn("Warning: falling back to slow RGB capture")
        return Capture(capture_element, pixel_format="BGRX", width=w, height=h)

    def start_pipewire_capture(self, node_id: int, props: typedict) -> None:
        log(f"start_pipewire_capture({node_id}, {props})")
        if not isinstance(node_id, int):
            raise ValueError(f"node-id is a {type(node_id)}, must be an int")
        x, y = props.inttupleget("position", (0, 0))
        w, h = props.inttupleget("size", (0, 0))
        if w <= 0 or h <= 0:
            raise ValueError(f"invalid dimensions: {w}x{h}")
        empty_dict = Dictionary(signature="sv")
        fd_object = self.portal_interface.OpenPipeWireRemote(
            self.session_handle,
            empty_dict,
            dbus_interface=SCREENCAST_IFACE)
        fd = fd_object.take()
        self.capture = self.create_capture_pipeline(fd, node_id, w, h)
        self.capture.node_id = node_id
        self.capture.connect("state-changed", self.capture_state_changed)
        self.capture.connect("error", self.capture_error)
        self.capture.connect("new-image", self.capture_new_image)
        self.capture.start()
        source_type = props.intget("source_type")
        title = f"{AvailableSourceTypes(source_type)} {node_id}"
        geometry = (x, y, w, h)
        model = PipewireWindowModel(self.capture, title, geometry, node_id, props)
        # must be called from the main thread:
        log(f"new model: {model}")
        self.do_add_new_window_common(node_id, model)
        self._send_new_window_packet(model)

    def capture_new_image(self, capture, coding: str, data, client_info: dict) -> None:
        wid = capture.node_id
        model = self._id_to_window.get(wid)
        log(f"capture_new_image({capture}, {coding}, {type(data)}, {client_info}) model({wid:#x})={model}")
        if not model:
            log.error(f"Error: cannot find window model for node {wid:#x}")
            return
        if isinstance(data, ImageWrapper):
            self.refresh_window(model)
            return
        if not isinstance(data, bytes):
            log.warn(f"Warning: unexpected image datatype: {type(data)}")
            return
        # this is a frame from a compressed stream,
        # send it to all the window sources for this window:
        for ss in tuple(self._server_sources.values()):
            if not hasattr(ss, "get_window_source"):
                # client is not showing any windows
                continue
            ws = ss.get_window_source(wid)
            if not ws:
                # client not showing this window
                continue
            ws.direct_queue_draw(coding, data, client_info)

    def capture_error(self, capture, message) -> None:
        wid = capture.node_id
        log(f"capture_error({capture}, {message}) wid={wid:#x}")
        log.error("Error capturing screen:")
        log.estr(message)
        model = self._id_to_window.get(wid)
        if model:
            self._remove_window(model)
        for ss in tuple(self._server_sources.values()):
            ss.may_notify(NotificationID.FAILURE, "Session Capture Failed", str(message))

    def capture_state_changed(self, capture, state) -> None:
        wid = capture.node_id
        log(f"screencast capture state changed for model {wid:#x}: {state!r}")
