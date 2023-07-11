#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
from time import monotonic
from typing import Dict, Any, Tuple

from xpra.x11.x11_server_core import X11ServerCore
from xpra.net.compression import Compressed
from xpra.os_util import is_Wayland, get_loaded_kernel_modules
from xpra.util import envbool, envint, merge_dicts, AdHocStruct, NotificationID
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.server.shadow.gtk_root_window_model import GTKImageCapture
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.server.server_uuid import del_mode, del_uuid
from xpra.x11.gtk_x11.prop import prop_get
from xpra.x11.bindings.window import X11WindowBindings     #@UnresolvedImport
from xpra.gtk_common.gtk_util import get_default_root_window, get_root_size
from xpra.gtk_common.error import xsync, xlog
from xpra.log import Logger

log = Logger("x11", "shadow")

XSHM : bool = envbool("XPRA_SHADOW_XSHM", True)
POLL_CURSOR : int = envint("XPRA_SHADOW_POLL_CURSOR", 20)
NVFBC : bool = envbool("XPRA_SHADOW_NVFBC", True)
GSTREAMER : bool = envbool("XPRA_SHADOW_GSTREAMER", False)
nvfbc = None
if NVFBC:
    try:
        from xpra.codecs.nvidia.nvfbc.capture import get_capture_module, get_capture_instance
        nvfbc = get_capture_module()
        if nvfbc:
            nvfbc.init_nvfbc_library()
    except Exception:
        log("NvFBC Capture is not available", exc_info=True)
        NVFBC = False
        nvfbc = None


def window_matches(wspec, model_class):
    wspec = list(wspec)
    try:
        wspec.remove("skip-children")
    except ValueError:
        skip_children = False
    else:
        skip_children = True
    wb = X11WindowBindings()
    with xsync:
        allw = [wxid for wxid in wb.get_all_x11_windows() if
                not wb.is_inputonly(wxid) and wb.is_mapped(wxid)]
        names = {}
        commands = {}
        classes = {}
        for wxid in allw:
            name = prop_get(wxid, "_NET_WM_NAME", "utf8", True) or prop_get(wxid, "WM_NAME", "latin1", True)
            if name:
                names[wxid] = name
            command = prop_get(wxid, "WM_COMMAND", "latin1", True)
            if command:
                commands[wxid] = command.strip("\0")
            class_instance = wb.getClassHint(wxid)
            if class_instance:
                classes[wxid] = class_instance[0].decode("latin1")

        def matchre(re_str, xid_dict):
            xids = []
            try:
                re_c = re.compile(re_str, re.IGNORECASE)
            except re.error:
                log.error("Error: invalid window regular expression %r", re_str)
            else:
                for wxid, vstr in xid_dict.items():
                    if re_c.match(vstr):
                        xids.append(wxid)
            return xids
        def i(v):
            try:
                if v.startswith("0x"):
                    return int(v, 16)
                return int(v)
            except ValueError:
                return 0

        #log.error("get_all_x11_windows()=%s", allw)
        windows = []
        skip = []
        for m in wspec:
            xids = []
            if m.startswith("xid="):
                m = m[4:]
            xid = i(m)
            if xid:
                xids.append(xid)
            elif m.startswith("pid="):
                pid = i(m[4:])
                if pid:
                    try:
                        from xpra.x11.bindings.res import ResBindings #@UnresolvedImport pylint: disable=import-outside-toplevel
                    except ImportError:
                        XRes = None
                    else:
                        XRes = ResBindings()
                    if XRes and XRes.check_xres():
                        for xid in names:
                            if XRes.get_pid(xid)==pid:
                                xids.append(xid)
            elif m.startswith("command="):
                command = m[len("command="):]
                xids += matchre(command, commands)
            elif m.startswith("class="):
                _class = m[len("class="):]
                xids += matchre(_class, classes)
            else:
                #assume this is a window name:
                xids += matchre(m, names)
            for xid in sorted(xids):
                if xid in skip:
                    #log.info("%s skipped", hex(xid))
                    continue
                #log.info("added %s", hex(xid))
                windows.append(xid)
                if skip_children:
                    children = wb.get_all_children(xid)
                    skip += children
                #for cxid in wb.get_all_children(xid):
                #    if cxid not in windows:
                #        windows.append(cxid)
        #log.error("windows(%s)=%s", self.window_matches, tuple(hex(window) for window in windows))
        models = {}
        for xid in windows:
            x, y, w, h = wb.getGeometry(xid)[:4]
            #absp = wb.get_absolute_position(xid)
            if w>0 and h>0:
                title = names.get(xid, "unknown window")
                model = model_class(title, (x, y, w, h))
                models[xid] = model
        log("window_matches(%s, %s)=%s", wspec, model_class, models)
        #find relative position and 'transient-for':
        for xid, model in models.items():
            model.xid = xid
            model.override_redirect = wb.is_override_redirect(xid)
            transient_for_xid = prop_get(xid, "WM_TRANSIENT_FOR", "window", True)
            model.transient_for = None
            if transient_for_xid:
                try:
                    from xpra.x11.gtk3.gdk_bindings import get_pywindow
                    model.transient_for = get_pywindow(transient_for_xid)
                except ImportError:
                    pass
            rel_parent = model.transient_for
            if not rel_parent:
                parent = xid
                rel_parent = None
                while parent>0:
                    parent = wb.getParent(parent)
                    rel_parent = models.get(parent)
                    if rel_parent:
                        log.warn(f"Warning: {rel_parent} is the parent of {model}")
                        break
            model.parent = rel_parent
            #"class-instance", "client-machine", "window-type",
            if rel_parent:
                parent_g = rel_parent.get_geometry()
                dx = model.geometry[0]-parent_g[0]
                dy = model.geometry[1]-parent_g[1]
                model.relative_position = dx, dy
                log("relative_position=%s", model.relative_position)
        log("window_matches%s models=%s", (wspec, model_class), models)
        return models.values()


class XImageCapture:
    __slots__ = ("xshm", "xwindow", "XImage")
    def __init__(self, xwindow:int):
        log("XImageCapture(%#x)", xwindow)
        self.xshm = None
        self.xwindow = xwindow
        from xpra.x11.bindings.ximage import XImageBindings     #@UnresolvedImport pylint: disable=import-outside-toplevel
        self.XImage = XImageBindings()
        assert XSHM and self.XImage.has_XShm(), "no XShm support"
        if is_Wayland():
            log.warn("Warning: shadow servers do not support Wayland")
            log.warn(" please switch to X11 for shadow support")

    def __repr__(self):
        return f"XImageCapture({self.xwindow:x})"

    def get_type(self) -> str:
        return "XImageCapture"

    def clean(self) -> None:
        self.close_xshm()

    def close_xshm(self) -> None:
        xshm = self.xshm
        if self.xshm:
            self.xshm = None
            with xlog:
                xshm.cleanup()

    def _err(self, e, op="capture pixels") -> None:
        if getattr(e, "msg", None)=="BadMatch":
            log("BadMatch - temporary error in %s of window #%x", op, self.xwindow, exc_info=True)
        else:
            log.warn("Warning: failed to %s of window %#x:", op, self.xwindow)
            log.warn(" %s", e)
        self.close_xshm()

    def refresh(self) -> bool:
        if self.xshm:
            #discard to ensure we will call XShmGetImage next time around
            self.xshm.discard()
            return True
        try:
            with xsync:
                log("%s.refresh() xshm=%s", self, self.xshm)
                self.xshm = self.XImage.get_XShmWrapper(self.xwindow)
                self.xshm.setup()
        except Exception as e:
            self.xshm = None
            self._err(e, "xshm setup")
        return True

    def get_image(self, x:int, y:int, width:int, height:int):
        log("XImageCapture.get_image%s for %#x", (x, y, width, height), self.xwindow)
        if self.xshm is None:
            log("no xshm, cannot get image")
            return None
        start = monotonic()
        try:
            with xsync:
                log("X11 shadow get_image, xshm=%s", self.xshm)
                image = self.xshm.get_image(self.xwindow, x, y, width, height)
                return image
        except Exception as e:
            self._err(e)
            return None
        finally:
            end = monotonic()
            log("X11 shadow captured %s pixels at %i MPixels/s using %s",
                width*height, (width*height/(end-start))//1024//1024, ["GTK", "XSHM"][XSHM])


def setup_capture(window):
    ww, wh = window.get_geometry()[2:4]
    if NVFBC:
        try:
            capture = get_capture_instance()
            capture.init_context(ww, wh)
            capture.refresh()
            image = capture.get_image(0, 0, ww, wh)
            assert image, "test capture failed"
            return capture
        except Exception as e:
            log("get_image() NvFBC test failed", exc_info=True)
            log(f"not using NvFBC capture: {e}")
    if GSTREAMER:
        try:
            from xpra.codecs.gstreamer.capture import Capture
            xid = window.get_xid()
            el = "ximagesrc"
            if xid>=0:
                el += f" xid={xid} startx=0 starty=0"
            if ww>0:
                el += f" endx={ww}"
            if wh>0:
                el += f" endy={wh}"
            capture = Capture(el, width=ww, height=wh)
            capture.start()
            image = capture.get_image(0, 0, ww, wh)
            if image:
                return capture
            log("gstreamer capture failed to return an image")
        except ImportError as e:
            log(f"not using X11 capture using gstreamer: {e}")
        except Exception:
            log("not using X11 capture using gstreamer", exc_info=True)
    if XSHM:
        try:
            from xpra.x11.bindings.ximage import XImageBindings     #@UnresolvedImport pylint: disable=import-outside-toplevel
            XImage = XImageBindings()
        except ImportError as e:
            log(f"not using X11 capture using bindings: {e}")
        else:
            if XImage.has_XShm():
                return XImageCapture(window.get_xid())
    return GTKImageCapture(window)


class X11ShadowModel(RootWindowModel):
    __slots__ = ("xid", "override_redirect", "transient_for", "parent", "relative_position")
    def __init__(self, root_window, capture=None, title="", geometry=None):
        super().__init__(root_window, capture, title, geometry)
        self.property_names += ["transient-for", "parent", "relative-position"]
        self.dynamic_property_names += ["transient-for", "parent", "relative-position"]
        self.override_redirect : bool = False
        self.transient_for = None
        self.parent = None
        self.relative_position = ()
        try:
            self.xid = root_window.get_xid()
            self.property_names.append("xid")
        except Exception:
            self.xid = 0

    def get_id(self) -> int:
        return self.xid

    def __repr__(self) -> str:
        info = ", OR" if self.override_redirect else ""
        return f"X11ShadowModel({self.capture} : {self.geometry} : {self.xid:x}{info})"


#FIXME: warning: this class inherits from ServerBase twice..
#so many calls will happen twice there (__init__ and init)
class ShadowX11Server(GTKShadowServerBase, X11ServerCore):

    def __init__(self, multi_window:bool=True):
        GTKShadowServerBase.__init__(self, multi_window=multi_window)
        X11ServerCore.__init__(self)
        self.session_type = "X11 shadow"
        self.modify_keymap = False

    def init(self, opts) -> None:
        GTKShadowServerBase.init(self, opts)
        #don't call init on X11ServerCore,
        #this would call up to GTKServerBase.init(opts) again:
        X11ServerCore.do_init(self, opts)
        self.modify_keymap = opts.keyboard_layout.lower() in ("client", "auto")

    def init_fake_xinerama(self) -> None:
        #don't enable fake xinerama with shadow servers,
        #we want to keep whatever settings they have
        self.libfakeXinerama_so = None


    def set_keymap(self, server_source, force:bool=False) -> None:
        if self.readonly:
            return
        if self.modify_keymap:
            X11ServerCore.set_keymap(self, server_source, force)
        else:
            ShadowServerBase.set_keymap(self, server_source, force)

    def cleanup(self) -> None:
        GTKShadowServerBase.cleanup(self)
        X11ServerCore.cleanup(self)     #@UndefinedVariable
        for fn in (del_mode, del_uuid):
            try:
                fn()
            except Exception:
                log("cleanup() failed to remove X11 attribute", exc_info=True)
        self.do_clean_session_files("xauthority")


    def setup_capture(self):
        capture = setup_capture(self.root)
        log(f"setup_capture({self.root})={capture}")
        return capture


    def get_root_window_model_class(self) -> type:
        return X11ShadowModel


    def makeDynamicWindowModels(self):
        assert self.window_matches
        rwmc = self.get_root_window_model_class()
        root = get_default_root_window()
        def model_class(title, geometry):
            model = rwmc(root, self.capture, title, geometry)
            model.dynamic_property_names.append("size-hints")
            return model
        return window_matches(self.window_matches, model_class)


    def client_startup_complete(self, ss) -> None:
        super().client_startup_complete(ss)
        log("is_Wayland()=%s", is_Wayland())
        if is_Wayland():
            ss.may_notify(NotificationID.SHADOWWAYLAND,
                          "Wayland Shadow Server",
                          "This shadow session is running under wayland,\n"+
                          "the screen scraping will probably come up empty",
                          icon_name="unticked")


    def last_client_exited(self) -> None:
        GTKShadowServerBase.last_client_exited(self)
        X11ServerCore.last_client_exited(self)


    def do_get_cursor_data(self) -> Tuple[Any,Any]:
        return X11ServerCore.get_cursor_data(self)


    def send_initial_data(self, ss, c, send_ui:bool, share_count:int) -> None:
        super().send_initial_data(ss, c, send_ui, share_count)
        if getattr(ss, "ui_client", True) and getattr(ss, "send_windows", True):
            self.verify_capture(ss)


    def verify_capture(self, ss) -> None:
        #verify capture works:
        log(f"verify_capture({ss})")
        nid = NotificationID.DISPLAY
        try:
            capture = GTKImageCapture(self.root)
            bdata = capture.take_screenshot()[-1]
            title = body = ""
            if any(b!=0 for b in bdata):
                log("verify_capture(%s) succeeded", ss)
                if is_Wayland():
                    title = "Wayland Session Warning"
                    body = "Wayland sessions are not supported,\n"+\
                            "the screen capture is likely to be empty"
            else:
                log.warn("Warning: shadow screen capture is blank")
                body = "The shadow display capture is blank"
                if get_loaded_kernel_modules("vboxguest", "vboxvideo"):
                    body += "\nthis may be caused by the VirtualBox video driver."
                title = "Shadow Capture Failure"
            log("verify_capture: title=%r, body=%r", title, body)
            if title and body:
                ss.may_notify(nid, title, body, icon_name="server")
        except Exception as e:
            ss.may_notify(nid, "Shadow Error", f"Error shadowing the display:\n{e}", icon_name="bugs")


    def make_hello(self, source) -> Dict[str,Any]:
        capabilities = X11ServerCore.make_hello(self, source)
        capabilities.update(GTKShadowServerBase.make_hello(self, source))
        capabilities["server_type"] = "X11 Shadow"
        return capabilities

    def get_info(self, proto, *_args) -> Dict[str,Any]:
        info = X11ServerCore.get_info(self, proto)
        merge_dicts(info, ShadowServerBase.get_info(self, proto))
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("server", {})["type"] = "Python/gtk3/x11-shadow"
        return info

    def do_make_screenshot_packet(self) -> Tuple[str,int,int,str,int,Compressed]:
        capture = GTKImageCapture(self.root)
        w, h, encoding, rowstride, data = capture.take_screenshot()
        assert encoding=="png"  #use fixed encoding for now
        # pylint: disable=import-outside-toplevel
        return ("screenshot", w, h, encoding, rowstride, Compressed(encoding, data))


def snapshot(filename) -> int:
    #pylint: disable=import-outside-toplevel
    from io import BytesIO
    from xpra.os_util import memoryview_to_bytes
    root = get_default_root_window()
    capture = setup_capture(root)
    capture.refresh()
    w, h = get_root_size()
    image = capture.get_image(0, 0, w, h)
    log(f"snapshot: {capture.get_image}(0, 0, {w}, {h})={image}")
    from PIL import Image
    fmt = image.get_pixel_format().replace("X", "A")
    pixels = memoryview_to_bytes(image.get_pixels())
    log(f"converting {len(pixels)} bytes in format {fmt} to RGBA")
    if len(fmt)==3:
        target = "RGB"
    else:
        target = "RGBA"
    pil_image = Image.frombuffer(target, (w, h), pixels, "raw", fmt, image.get_rowstride())
    if target!="RGB":
        pil_image = pil_image.convert("RGB")
    buf = BytesIO()
    pil_image.save(buf, "png")
    data = buf.getvalue()
    buf.close()
    with open(filename, "wb") as f:
        f.write(data)
    return 0


def main(*args) -> int:
    assert len(args)>0
    if args[0].endswith(".png"):
        return snapshot(args[0])
    def cb(title, geom):
        s = AdHocStruct()
        s.title = title
        s.geometry = geom
        return s
    from xpra.x11.gtk3 import gdk_display_source  #pylint: disable=import-outside-toplevel, no-name-in-module
    gdk_display_source.init_gdk_display_source()  # @UndefinedVariable
    for w in window_matches(args, cb):
        print(f"{w}")
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv)==1:
        cmd = sys.argv[0]
        print(f"usage: {cmd} filename.png")
        print(f"usage: {cmd} windowname|windowpid")
        r = 1
    else:
        r = main(*sys.argv[1:])
    sys.exit(r)
