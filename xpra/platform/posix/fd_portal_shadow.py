#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import random
from time import monotonic
from dbus.types import UInt32
from dbus.types import Dictionary

from xpra.exit_codes import ExitCode
from xpra.util import typedict, envbool, ConnectionMessage
from xpra.net.compression import Compressed
from xpra.dbus.helper import dbus_to_native
from xpra.codecs.gstreamer.capture import Capture, CaptureAndEncode
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.server.shadow.root_window_model import RootWindowModel
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

session_counter : int = random.randint(0, 2**24)

VIDEO_MODE = envbool("XPRA_PIPEWIRE_VIDEO_MODE", True)


class PipewireWindowModel(RootWindowModel):
    __slots__ = ("pipewire_id", "pipewire_props")


class PortalShadow(GTKShadowServerBase):
    def __init__(self, multi_window=True):
        GTKShadowServerBase.__init__(self, multi_window=multi_window)
        self.session = None
        self.session_path : str = ""
        self.session_handle : str = ""
        self.authenticating_client = None
        self.capture : Capture = None
        self.portal_interface = get_portal_interface()
        log(f"setup_capture() self.portal_interface={self.portal_interface}")
        #we're not using X11, so no need for this check:
        os.environ["XPRA_UI_THREAD_CHECK"] = "0"


    def notify_new_user(self, ss):
        log("notify_new_user() start capture")
        super().notify_new_user(ss)
        if not self._window_to_id:
            self.authenticating_client = ss
            self.create_session()

    def last_client_exited(self):
        super().last_client_exited()
        self.stop_capture()
        self.stop_session()

    def client_auth_error(self, message):
        self.disconnect_authenticating_client(ConnectionMessage.AUTHENTICATION_FAILED, message)

    def disconnect_authenticating_client(self, reason : ConnectionMessage, message : str):
        ac = self.authenticating_client
        if ac:
            self.authenticating_client = None
            self.disconnect_protocol(ac.protocol, reason, message)
            self.cleanup_source(ac)


    def makeRootWindowModels(self):
        log("makeRootWindowModels()")
        return []

    def makeDynamicWindowModels(self):
        log("makeDynamicWindowModels()")
        return []

    def set_keymap(self, server_source, force=False):
        raise NotImplementedError()


    def start_refresh(self, wid):
        self.start_capture()

    def start_capture(self):
        pass

    def setup_capture(self):
        pass

    def stop_capture(self):
        c = self.capture
        if c:
            self.capture = None
            c.clean()

    def cleanup(self):
        GTKShadowServerBase.cleanup(self)
        self.portal_interface = None


    def stop_session(self):
        s = self.session
        if not s:
            return
        self.session = None
        #https://gitlab.gnome.org/-/snippets/1122
        log(f"trying to close the session {s}")
        try:
            s.Close(dbus_interface=PORTAL_SESSION_INTERFACE)
        except Exception as e:
            log(f"ignoring error closing session {s}: {e}")

    def create_session(self):
        global session_counter
        session_counter += 1
        token = f"u{session_counter}"
        self.session_path = f"/org/freedesktop/portal/desktop/session/{dbus_sender_name}/{token}"
        options = {
            "session_handle_token"  : token,
            }
        log(f"create_session() session_counter={session_counter}")
        remotedesktop_dbus_call(
            self.portal_interface.CreateSession,
            self.on_create_session_response,
            options=options,
            )

    def on_create_session_response(self, response, results):
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

    def on_session_created(self):
        self.select_devices()


    def select_devices(self):
        log("select_devices()")
        options = {
            "types" : UInt32(AvailableDeviceTypes.KEYBOARD + AvailableDeviceTypes.POINTER),
            }
        remotedesktop_dbus_call(
            self.portal_interface.SelectDevices,
            self.on_select_devices_response,
            self.session_handle,
            options=options)

    def on_select_devices_response(self, response, results):
        r = int(response)
        res = dbus_to_native(results)
        if r:
            log("on_select_devices_response%s", (response, results))
            log.error(f"Error {r} selecting screencast devices")
            self.client_auth_error("failed to select devices")
            return
        log(f"on_select_devices_response devices selected, results={res}")
        self.select_sources()


    def select_sources(self):
        options = {
            "multiple"  : self.multi_window,
            "types"     : UInt32(AvailableSourceTypes.WINDOW | AvailableSourceTypes.MONITOR),
            }
        log(f"calling SelectSources with options={options}")
        screenscast_dbus_call(
            self.portal_interface.SelectSources,
            self.on_select_sources_response,
            self.session_handle,
            options=options)

    def on_select_sources_response(self, response, results):
        r = int(response)
        res = typedict(dbus_to_native(results))
        if r:
            log("on_select_sources_response%s", (response, results))
            log.error(f"Error {r} selecting screencast sources")
            self.client_auth_error("failed to select screencast sources")
            return
        log(f"on_select_sources_response sources selected, results={res}")
        self.portal_start()


    def portal_start(self):
        log("portal_start()")
        remotedesktop_dbus_call(
            self.portal_interface.Start,
            self.on_start_response,
            self.session_handle,
            "")

    def on_start_response(self, response, results):
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
            self.start_pipewire_capture(node_id, typedict(props))
        self.input_devices = res.intget("devices")
        if not self.input_devices and not self.readonly:
            #ss.notify("", nid, "Xpra", 0, "", title, body, [], {}, 10*1000, icon)
            log.warn("Warning: no input devices,")
            log.warn(" keyboard and pointer events cannot be forwarded")


    def create_capture_pipeline(self, fd : int, node_id : int, w : int, h : int):
        el = f"pipewiresrc fd={fd} path={node_id} do-timestamp=true"
        c = self.authenticating_client
        if VIDEO_MODE:
            encs = getattr(c, "core_encodings", ())
            log(f"core_encodings({c})={encs}")
            if "h264" in encs:
                return CaptureAndEncode(el, pixel_format="BGRX", width=w, height=h)
        return Capture(el, pixel_format="BGRX", width=w, height=h)

    def start_pipewire_capture(self, node_id, props):
        log(f"start_pipewire_capture({node_id}, {props})")
        x, y = props.inttupleget("position", (0, 0))
        w, h = props.inttupleget("size", (0, 0))
        if w<=0 or h<=0:
            raise ValueError(f"invalid dimensions: {w}x{h}")
        empty_dict = Dictionary(signature="sv")
        fd_object = self.portal_interface.OpenPipeWireRemote(
            self.session_handle,
            empty_dict,
            dbus_interface=SCREENCAST_IFACE,
            )
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
        model = PipewireWindowModel(self.root, self.capture, title, geometry)
        model.pipewire_id = node_id
        model.pipewire_props = props
        #must be called from the main thread:
        log(f"new model: {model}")
        self.do_add_new_window_common(node_id, model)
        self._send_new_window_packet(model)

    def capture_new_image(self, capture, frame, coding, data):
        wid = capture.node_id
        model = self._id_to_window.get(wid)
        log(f"capture_new_image({capture}, {frame}, {coding}, {type(data)}) model({wid})={model}")
        if not model:
            log.error(f"Error: cannot find window model for node {wid}")
            return
        if isinstance(data, ImageWrapper):
            self.refresh_window(model)
            return
        if not isinstance(data, bytes):
            log.warn(f"Warning: unexpected image datatype: {type(data)}")
            return
        #this is a frame from a compressed stream,
        #send it to all the window sources for this window:
        cdata = Compressed(coding, data)
        client_options = {
            "frame" : frame,
            }
        options = {}
        x = y = 0
        w, h = model.geometry[2:4]
        outstride = 0
        damage_time = process_damage_time = monotonic()
        for ss in tuple(self._server_sources.values()):
            if not hasattr(ss, "get_window_source"):
                #client is not showing any windows
                continue
            ws = ss.get_window_source(wid)
            if not ws:
                #client not showing this window
                continue
            log(f"sending {len(data)} bytes packet of {coding} stream to {ws} of {ss}")
            packet = ws.make_draw_packet(x, y, w, h, coding, cdata, outstride, client_options, options)
            ws.queue_damage_packet(packet, damage_time, process_damage_time, options)


    def capture_error(self, capture, message):
        log(f"capture_error({capture}, {message})")
        log.error("Error capturing screen:")
        log.estr(message)
        #perhaps we should "lose" the window here?

    def capture_state_changed(self, capture, state):
        log(f"screencast capture state: {state}")
