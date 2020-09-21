# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re

from xpra.client.client_widget_base import ClientWidgetBase
from xpra.os_util import bytestostr, OSX, WIN32, is_Wayland
from xpra.util import typedict, envbool, envint, WORKSPACE_UNSET, WORKSPACE_NAMES
from xpra.log import Logger

log = Logger("window")
plog = Logger("paint")
focuslog = Logger("focus")
mouselog = Logger("mouse")
workspacelog = Logger("workspace")
keylog = Logger("keyboard")
metalog = Logger("metadata")
geomlog = Logger("geometry")
iconlog = Logger("icon")
alphalog = Logger("alpha")


SIMULATE_MOUSE_DOWN = envbool("XPRA_SIMULATE_MOUSE_DOWN", True)
PROPERTIES_DEBUG = [x.strip() for x in os.environ.get("XPRA_WINDOW_PROPERTIES_DEBUG", "").split(",")]
AWT_DIALOG_WORKAROUND = envbool("XPRA_AWT_DIALOG_WORKAROUND", WIN32)
SET_SIZE_CONSTRAINTS = envbool("XPRA_SET_SIZE_CONSTRAINTS", True)
DEFAULT_GRAVITY = envint("XPRA_DEFAULT_GRAVITY", 0)
OVERRIDE_GRAVITY = envint("XPRA_OVERRIDE_GRAVITY", 0)


class ClientWindowBase(ClientWidgetBase):

    #(overriden in subclasses)
    NAME_TO_HINT = {}

    def __init__(self, client, group_leader, watcher_pid, wid,
                 wx, wy, ww, wh, bw, bh,
                 metadata, override_redirect, client_properties,
                 border, max_window_size, default_cursor_data, pixel_depth):
        log("%s%s", type(self),
            (client, group_leader, watcher_pid, wid,
             wx, wy, ww, wh, bw, bh,
             metadata, override_redirect, client_properties,
             border, max_window_size, default_cursor_data, pixel_depth))
        super().__init__(client, watcher_pid, wid, metadata.boolget("has-alpha"))
        self._override_redirect = override_redirect
        self.group_leader = group_leader
        self._pos = (wx, wy)
        self._size = (ww, wh)
        self._client_properties = client_properties
        self._set_initial_position = metadata.boolget("set-initial-position", False)
        self.size_constraints = typedict()
        self.geometry_hints = {}
        self.content_type = ""
        self._fullscreen = None
        self._maximized = False
        self._above = False
        self._below = False
        self._shaded = False
        self._sticky = False
        self._skip_pager = False
        self._skip_taskbar = False
        self._sticky = False
        self._iconified = False
        self._focused = False
        self.window_gravity = OVERRIDE_GRAVITY or DEFAULT_GRAVITY
        self.border = border
        self.cursor_data = None
        self.default_cursor_data = default_cursor_data
        self.max_window_size = max_window_size
        self.button_state = {}
        self.pixel_depth = pixel_depth      #0 for default
        self.window_offset = None           #actual vs reported coordinates
        self.pending_refresh = []

        self.init_window(metadata)
        self.setup_window(bw, bh)
        self.update_metadata(metadata)

    def __repr__(self):
        return "ClientWindow(%s)" % self._id

    def init_window(self, metadata):
        self._backing = None
        self._metadata = typedict()
        # used for only sending focus events *after* the window is mapped:
        self._been_mapped = False
        self._override_redirect_windows = []
        def wn(w):
            return WORKSPACE_NAMES.get(w, w)
        workspace = typedict(self._client_properties).intget("workspace", None)
        workspacelog("init_window(..) workspace from client properties %s: %s", self._client_properties, wn(workspace))
        if workspace is not None:
            #client properties override application specified workspace value on init only:
            metadata[b"workspace"] = workspace
        self._window_workspace = WORKSPACE_UNSET        #will get set in set_metadata if present
        self._desktop_workspace = self.get_desktop_workspace()  #pylint: disable=assignment-from-none
        workspacelog("init_window(..) workspace=%s, current workspace=%s",
                     wn(self._window_workspace), wn(self._desktop_workspace))
        if self.max_window_size and b"size-constraints" not in metadata:
            #this ensures that we will set size-constraints and honour max_window_size:
            metadata[b"size-constraints"] = {}
        #initialize gravity early:
        sc = typedict(metadata.dictget("size-constraints", {}))
        self.window_gravity = OVERRIDE_GRAVITY or sc.intget("gravity", DEFAULT_GRAVITY)
        self.set_decorated(metadata.boolget("decorations", True))


    def get_desktop_workspace(self):
        return None

    def get_window_workspace(self):
        return None


    def new_backing(self, bw, bh):
        backing_class = self.get_backing_class()
        log("new_backing(%s, %s) backing_class=%s", bw, bh, backing_class)
        assert backing_class is not None
        w, h = self._size
        self._backing = self.make_new_backing(backing_class, w, h, bw, bh)
        self._backing.border = self.border
        self._backing.default_cursor_data = self.default_cursor_data
        self._backing.gravity = self.window_gravity
        return self._backing._backing


    def destroy(self):
        #ensure we clear reference to other windows:
        self.group_leader = None
        self._override_redirect_windows = []
        self._metadata = {}
        if self._backing:
            self._backing.close()
            self._backing = None


    def setup_window(self, bw, bh):
        self.new_backing(bw, bh)
        #tell the server about the encoding capabilities of this backing instance:
        #but don't bother if they're the same as what we sent as defaults
        #(with a bit of magic to collapse the missing namespace from encoding_defaults)
        backing_props = self._backing.get_encoding_properties()
        encoding_defaults = self._client.encoding_defaults
        for k in tuple(backing_props.keys()):
            v = backing_props[k]
            try:
                #ie: "encodings.rgb_formats" -> "rgb_formats"
                #ie: "encoding.full_csc_modes" -> "full_csc_modes"
                ek = k.split(".", 1)[1]
            except IndexError:
                ek = k
            dv = encoding_defaults.get(ek)
            if dv is not None and dv==v:
                del backing_props[k]
        self._client_properties.update(backing_props)


    def send(self, *args):
        self._client.send(*args)

    def reset_icon(self):
        current_icon = self._current_icon
        iconlog("reset_icon() current icon=%s", current_icon)
        if current_icon:
            self.update_icon(current_icon)

    def update_icon(self, img):
        raise NotImplementedError("override me!")

    def apply_transient_for(self, wid):
        raise NotImplementedError("override me!")

    def paint_spinner(self, context, area):
        raise NotImplementedError("override me!")

    def _pointer_modifiers(self, event):
        raise NotImplementedError("override me!")


    def xget_u32_property(self, target, name):
        raise NotImplementedError("override me!")


    def is_OR(self):
        return self._override_redirect


    def update_metadata(self, metadata):
        metalog("update_metadata(%s)", metadata)
        if self._client.readonly:
            metadata.update(self._force_size_constraint(*self._size))
        self._metadata.update(metadata)
        try:
            self.set_metadata(metadata)
        except Exception:
            metalog.warn("failed to set window metadata to '%s'", metadata, exc_info=True)

    def _force_size_constraint(self, *size):
        return {
            b"size-constraints" : {
                b"maximum-size" : size,
                b"minimum-size" : size,
                b"base-size" : size,
                }
            }

    def set_metadata(self, metadata):
        metalog("set_metadata(%s)", metadata)
        debug_props = [x for x in PROPERTIES_DEBUG if x in metadata.keys()]
        for x in debug_props:
            metalog.info("set_metadata: %s=%s", x, metadata.get(x))
        #WARNING: "class-instance" needs to go first because others may realize the window
        #(and GTK doesn't set the "class-instance" once the window is realized)
        if b"class-instance" in metadata:
            self.set_class_instance(*self._metadata.strtupleget("class-instance", ("xpra", "Xpra"), 2, 2))
            self.reset_icon()

        if b"title" in metadata:
            try:
                title = bytestostr(self._client.title).replace("\0", "")
                if title.find("@")>=0:
                    #perform metadata variable substitutions:
                    #full of py3k unicode headaches that don't need to be
                    default_values = {
                        "title"           : "<untitled window>",
                        "client-machine"  : "<unknown machine>",
                        "windowid"        : str(self._id),
                        "server-machine"  : getattr(self._client, "_remote_hostname", None) or "<unknown machine>",
                        "server-display"  : getattr(self._client, "_remote_display", None) or "<unknown display>",
                        }
                    def getvar(var):
                        #"hostname" is magic:
                        #we try harder to find a useful value to show:
                        if var=="hostname":
                            #try to find the hostname:
                            proto = getattr(self._client, "_protocol", None)
                            if proto:
                                conn = getattr(proto, "_conn", None)
                                if conn:
                                    hostname = conn.info.get("host") or bytestostr(conn.target)
                                    if hostname:
                                        return hostname
                            for m in ("client-machine", "server-machine"):
                                value = getvar(m)
                                if value not in (
                                    "localhost",
                                    "localhost.localdomain",
                                    "<unknown machine>",
                                    "",
                                    None):
                                    return value
                            return "<unknown machine>"
                        value = self._metadata.bytesget(var)
                        if value is None:
                            return default_values.get(var, "<unknown %s>" % var)
                        try:
                            return value.decode("utf-8")
                        except UnicodeDecodeError:
                            return str(value)
                    def metadata_replace(match):
                        atvar = match.group(0)          #ie: '@title@'
                        var = atvar[1:len(atvar)-1]     #ie: 'title'
                        if not var:
                            #atvar = "@@"
                            return "@"
                        return getvar(var)
                    title = re.sub(r"@[\w\-]*@", metadata_replace, title)
            except Exception as e:
                log.error("Error parsing window title:")
                log.error(" %s", e)
                title = ""
            self.set_title(title)

        if b"icon-title" in metadata:
            icon_title = metadata.strget("icon-title")
            self.set_icon_name(icon_title)
            #the DE may have reset the icon now,
            #force it to use the one we really want:
            self.reset_icon()

        if b"size-constraints" in metadata:
            sc = typedict(metadata.dictget("size-constraints", {}))
            self.size_constraints = sc
            self._set_initial_position = sc.boolget("set-initial-position", self._set_initial_position)
            self.set_size_constraints(sc, self.max_window_size)

        if b"set-initial-position" in metadata:
            #this should be redundant - but we keep it here for consistency
            self._set_initial_position = metadata.boolget("set-initial-position")

        if b"transient-for" in metadata:
            wid = metadata.intget("transient-for", -1)
            self.apply_transient_for(wid)

        if b"modal" in metadata:
            modal = metadata.boolget("modal")
            self.set_modal(modal)

        #apply window-type hint if window has not been mapped yet:
        if b"window-type" in metadata and not self.is_mapped():
            window_types = metadata.strtupleget("window-type")
            self.set_window_type(window_types)

        if b"role" in metadata:
            role = metadata.strget("role")
            self.set_role(role)

        if b"xid" in metadata:
            xid = metadata.strget("xid")
            self.set_xid(xid)

        if b"opacity" in metadata:
            opacity = metadata.intget("opacity", -1)
            if opacity<0:
                opacity = 1
            else:
                opacity = min(1, opacity/0xffffffff)
            #requires gtk>=2.12!
            if hasattr(self, "set_opacity"):
                self.set_opacity(opacity)

        if b"has-alpha" in metadata:
            new_alpha = metadata.boolget("has-alpha")
            if new_alpha!=self._has_alpha:
                l = alphalog
                if not WIN32:
                    #win32 without opengl can't do transparency,
                    #so it triggers too many warnings
                    l = log.warn
                l("Warning: window %s changed its transparency attribute", self._id)
                l(" from %s to %s, behaviour is undefined", self._has_alpha, new_alpha)
                self._has_alpha = new_alpha

        if b"maximized" in metadata:
            maximized = metadata.boolget("maximized")
            if maximized!=self._maximized:
                self._maximized = maximized
                if maximized:
                    self.maximize()
                else:
                    self.unmaximize()

        if b"fullscreen" in metadata:
            fullscreen = metadata.boolget("fullscreen")
            if self._fullscreen is None or self._fullscreen!=fullscreen:
                self._fullscreen = fullscreen
                self.set_fullscreen(fullscreen)

        if b"iconic" in metadata:
            iconified = metadata.boolget("iconic")
            if self._iconified!=iconified:
                self._iconified = iconified
                if iconified:
                    self.iconify()
                else:
                    self.deiconify()

        if b"decorations" in metadata:
            decorated = metadata.boolget("decorations", True)
            was_decorated = self.get_decorated()
            if WIN32 and decorated!=was_decorated:
                log.info("decorations flag toggled, now %s, re-initializing window", decorated)
                self.idle_add(self._client.reinit_window, self._id, self)
            else:
                self.set_decorated(metadata.boolget("decorations"))
                self.apply_geometry_hints(self.geometry_hints)

        if b"above" in metadata:
            above = metadata.boolget("above")
            if self._above!=above:
                self._above = above
                self.set_keep_above(above)

        if b"below" in metadata:
            below = metadata.boolget("below")
            if self._below!=below:
                self._below = below
                self.set_keep_below(below)

        if b"shaded" in metadata:
            shaded = metadata.boolget("shaded")
            if self._shaded!=shaded:
                self._shaded = shaded
                self.set_shaded(shaded)

        if b"sticky" in metadata:
            sticky = metadata.boolget("sticky")
            if self._sticky!=sticky:
                self._sticky = sticky
                if sticky:
                    self.stick()
                else:
                    self.unstick()

        if b"skip-taskbar" in metadata:
            skip_taskbar = metadata.boolget("skip-taskbar")
            if self._skip_taskbar!=skip_taskbar:
                self._skip_taskbar = skip_taskbar
                self.set_skip_taskbar_hint(skip_taskbar)

        if b"skip-pager" in metadata:
            skip_pager = metadata.boolget("skip-pager")
            if self._skip_pager!=skip_pager:
                self._skip_pager = skip_pager
                self.set_skip_pager_hint(skip_pager)

        if b"workspace" in metadata:
            self.set_workspace(metadata.intget("workspace"))

        if b"bypass-compositor" in metadata:
            self.set_bypass_compositor(metadata.intget("bypass-compositor"))

        if b"strut" in metadata:
            self.set_strut(metadata.dictget("strut", {}))

        if b"fullscreen-monitors" in metadata:
            self.set_fullscreen_monitors(metadata.inttupleget("fullscreen-monitors"))

        if b"shape" in metadata:
            self.set_shape(metadata.dictget("shape", {}))

        if b"command" in metadata:
            self.set_command(metadata.strget("command"))

        if b"x11-property" in metadata:
            self.set_x11_property(*metadata.tupleget("x11-property"))

        if b"content-type" in metadata:
            self.content_type = metadata.strget("content-type")


    def set_x11_property(self, *x11_property):
        pass

    def set_command(self, command):
        pass

    def set_class_instance(self, wmclass_name, wmclass_class):
        pass

    def set_shape(self, shape):
        log("set_shape(%s) not implemented", shape)

    def set_bypass_compositor(self, v):
        pass        #see gtk client window base

    def set_strut(self, strut):
        pass        #see gtk client window base

    def set_fullscreen_monitors(self, fsm):
        pass        #see gtk client window base

    def set_shaded(self, shaded):
        pass        #see gtk client window base


    def reset_size_constraints(self):
        self.set_size_constraints(self.size_constraints, self.max_window_size)

    def set_size_constraints(self, size_constraints, max_window_size):
        if not SET_SIZE_CONSTRAINTS:
            return
        geomlog("set_size_constraints(%s, %s)", size_constraints, max_window_size)
        hints = typedict()
        client = self._client
        for (a, h1, h2) in (
            (b"maximum-size", b"max_width", b"max_height"),
            (b"minimum-size", b"min_width", b"min_height"),
            (b"base-size", b"base_width", b"base_height"),
            (b"increment", b"width_inc", b"height_inc"),
            ):
            v = size_constraints.intpair(a)
            geomlog("intpair(%s)=%s", a, v)
            if v:
                v1, v2 = v
                if a==b"maximum-size" and v1>=32000 and v2>=32000 and WIN32:
                    #causes problems, see #2714
                    continue
                sv1 = client.sx(v1)
                sv2 = client.sy(v2)
                if a in (b"base-size", b"increment"):
                    #rounding is not allowed for these values
                    fsv1 = client.fsx(v1)
                    fsv2 = client.fsy(v2)
                    def closetoint(v):
                        #tolerate some rounding error:
                        #(ie: 2:3 scaling may not give an integer without a tiny bit of rounding)
                        return abs(int(v)-v)<0.00001
                    if not closetoint(fsv1) or not closetoint(fsv2):
                        #the scaled value is not close to an int,
                        #so we can't honour it:
                        geomlog("cannot honour '%s' due to scaling, scaled values are not both integers: %s, %s",
                                a, fsv1, fsv2)
                        continue
                hints[h1], hints[h2] = sv1, sv2
        if not OSX:
            for (a, h) in (
                (b"minimum-aspect-ratio", b"min_aspect"),
                (b"maximum-aspect-ratio", b"max_aspect"),
                ):
                v = size_constraints.intpair(a)
                if v:
                    v1, v2 = v
                    hints[h] = (v1*self._client.xscale)/(v2*self._client.yscale)
        #apply max-size override if needed:
        w,h = max_window_size
        if w>0 and h>0 and not self._fullscreen:
            #get the min size, if there is one:
            minw = max(1, hints.intget(b"min_width", 1))
            minh = max(1, hints.intget(b"min_height", 1))
            #the actual max size is:
            # * greater than the min-size
            # * the lowest of the max-size set by the application and the one we have
            # * ensure we honour the other hints, and round the max-size down if needed:
            #according to the GTK docs:
            #allowed window widths are base_width + width_inc * N where N is any integer
            #allowed window heights are base_height + width_inc * N where N is any integer
            maxw = hints.intget(b"max_width", 32768)
            maxh = hints.intget(b"max_height", 32768)
            maxw = max(minw, min(w, maxw))
            maxh = max(minh, min(h, maxh))
            rw = (maxw - hints.intget(b"base_width", 0)) % max(hints.intget(b"width_inc", 1), 1)
            rh = (maxh - hints.intget(b"base_height", 0)) % max(hints.intget(b"height_inc", 1), 1)
            maxw -= rw
            maxh -= rh
            #if the hints combination is invalid, it's possible that we'll end up
            #not honouring "base" + "inc", but honouring just "min" instead:
            maxw = max(minw, maxw)
            maxh = max(minh, maxh)
            geomlog("modified hints for max window size %s: %s (rw=%s, rh=%s) -> max=%sx%s",
                    max_window_size, hints, rw, rh, maxw, maxh)
            #ensure we don't have duplicates with bytes / strings,
            #and that keys are always "bytes":
            #(in practice this code should never fire, just here as a reminder)
            for x in ("max_width", "max_height"):
                try:
                    del hints[x]
                except KeyError:
                    pass
            #bug 2214: GTK3 on win32 gets confused if we specify a large max-size
            # and it will mess up maximizing the window
            if not WIN32 or (maxw<32000 or maxh<32000):
                hints[b"max_width"] = maxw
                hints[b"max_height"] = maxh
        try:
            geomlog("calling: %s(%s)", self.apply_geometry_hints, hints)
            #save them so the window hooks can use the last value used:
            self.geometry_hints = hints
            self.apply_geometry_hints(hints)
        except Exception:
            geomlog("set_size_constraints%s", (size_constraints, max_window_size), exc_info=True)
            geomlog.error("Error setting window hints:")
            for k,v in hints.items():
                geomlog.error(" %s=%s", bytestostr(k), v)
            geomlog.error(" from size constraints:")
            for k,v in size_constraints.items():
                geomlog.error(" %s=%s", k, v)
        self.window_gravity = OVERRIDE_GRAVITY or size_constraints.intget("gravity", DEFAULT_GRAVITY)
        b = self._backing
        if b:
            b.gravity = self.window_gravity


    def set_window_type(self, window_types):
        hints = 0
        for window_type in window_types:
            #win32 workaround:
            if AWT_DIALOG_WORKAROUND and window_type=="DIALOG" and self._metadata.boolget("skip-taskbar"):
                wm_class = self._metadata.strtupleget("class-instance", (None, None), 2, 2)
                if wm_class and len(wm_class)==2 and wm_class[0] and wm_class[0].startswith("sun-awt-X11"):
                    #replace "DIALOG" with "NORMAL":
                    if "NORMAL" in window_types:
                        continue
                    window_type = "NORMAL"
            hint = self.NAME_TO_HINT.get(window_type, None)
            if hint is not None:
                hints |= hint
            else:
                log("ignoring unknown window type hint: %s", window_type)
        log("set_window_type(%s) hints=%s", window_types, hints)
        if hints:
            self.set_type_hint(hints)

    def set_workspace(self, workspace):
        pass

    def set_fullscreen(self, fullscreen):
        pass

    def set_xid(self, xid):
        pass


    def toggle_debug(self, *_args):
        b = self._backing
        log.info("toggling debug on backing %s for window %i", b, self._id)
        if not b:
            return
        if b.paint_box_line_width>0:
            b.paint_box_line_width = 0
        else:
            b.paint_box_line_width = b.default_paint_box_line_width

    def increase_quality(self, *_args):
        if self._client.quality>0:
            #change fixed quality:
            self._client.quality = min(100, self._client.quality + 10)
            self._client.send_quality()
            log("new quality=%s", self._client.quality)
        else:
            self._client.min_quality = min(100, self._client.min_quality + 10)
            self._client.send_min_quality()
            log("new min-quality=%s", self._client.min_quality)

    def decrease_quality(self, *_args):
        if self._client.quality>0:
            #change fixed quality:
            self._client.quality = max(1, self._client.quality - 10)
            self._client.send_quality()
            log("new quality=%s", self._client.quality)
        else:
            self._client.min_quality = max(0, self._client.min_quality - 10)
            self._client.send_min_quality()
            log("new min-quality=%s", self._client.min_quality)

    def increase_speed(self, *_args):
        if self._client.speed>0:
            #change fixed speed:
            self._client.speed = min(100, self._client.speed + 10)
            self._client.send_speed()
            log("new speed=%s", self._client.speed)
        else:
            self._client.min_speed = min(100, self._client.min_speed + 10)
            self._client.send_min_speed()
            log("new min-speed=%s", self._client.min_speed)

    def decrease_speed(self, *_args):
        if self._client.speed>0:
            #change fixed speed:
            self._client.speed = max(1, self._client.speed - 10)
            self._client.send_speed()
            log("new speed=%s", self._client.speed)
        else:
            self._client.min_speed = max(0, self._client.min_speed - 10)
            self._client.send_min_speed()
            log("new min-speed=%s", self._client.min_speed)

    def scaleup(self, *_args):
        self._client.scaleup()

    def scaledown(self, *_args):
        self._client.scaledown()

    def scalingoff(self):
        self._client.scalingoff()

    def scalereset(self, *_args):
        self._client.scalereset()

    def magic_key(self, *args):
        b = self.border
        if b:
            b.toggle()
            log("magic_key%s border=%s", args, b)
            self.queue_draw_area(0, 0, *self._size)

    def refresh_window(self, *args):
        log("refresh_window(%s) wid=%s", args, self._id)
        self._client.send_refresh(self._id)

    def refresh_all_windows(self, *_args):
        #this method is only here because we may want to fire it
        #from a --key-shortcut action and the event is delivered to
        #the "ClientWindow"
        self._client.send_refresh_all()

    def draw_region(self, x, y, width, height, coding, img_data, rowstride, _packet_sequence, options, callbacks):
        """ Note: this runs from the draw thread (not UI thread) """
        backing = self._backing
        if not backing:
            log("draw_region: window %s has no backing, gone?", self._id)
            from xpra.client.window_backing_base import fire_paint_callbacks
            fire_paint_callbacks(callbacks, -1, "no backing")
            return
        #only register this callback if we actually need it:
        if backing.draw_needs_refresh:
            if not backing.repaint_all:
                self.pending_refresh.append((x, y, width, height))
            if options.intget("flush", 0)==0:
                callbacks.append(self.after_draw_refresh)
        backing.draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)

    def after_draw_refresh(self, success, message=""):
        plog("after_draw_refresh(%s, %s) pending_refresh=%s",
             success, message, self.pending_refresh)
        backing = self._backing
        if not backing:
            return
        if backing.repaint_all or self._client.xscale!=1 or self._client.yscale!=1 or is_Wayland():
            #easy: just repaint the whole window:
            rw, rh = self.get_size()
            self.idle_add(self.queue_draw_area, 0, 0, rw, rh)
            return
        pr = self.pending_refresh
        self.pending_refresh = []
        for x, y, w, h in pr:
            rx, ry, rw, rh = self._client.srect(x, y, w, h)
            if self.window_offset:
                rx += self.window_offset[0]
                ry += self.window_offset[1]
            self.idle_add(self.queue_draw_area, rx, ry, rw, rh)

    def eos(self):
        """ Note: this runs from the draw thread (not UI thread) """
        backing = self._backing
        if backing:
            backing.eos()

    def spinner(self, _ok):
        if not self.can_have_spinner():
            return
        log("spinner(%s) queueing redraw")
        #with normal windows, we just queue a draw request
        #and let the expose event paint the spinner
        w, h = self.get_size()
        self.queue_draw_area(0, 0, w, h)

    def can_have_spinner(self):
        if self._backing is None:
            return False
        window_types = self._metadata.strtupleget("window-type")
        if not window_types:
            return False
        return ("NORMAL" in window_types) or \
               ("DIALOG" in window_types) or \
               ("SPLASH" in window_types)


    def _unfocus(self):
        focuslog("_unfocus() wid=%s, focused=%s", self._id, self._client._focused)
        if self._client._focused==self._id:
            self._client.update_focus(self._id, False)

    def quit(self):
        self._client.quit(0)

    def void(self):
        pass

    def show_session_info(self, *args):
        self._client.show_session_info(*args)

    def show_menu(self, *args):
        self._client.show_menu(*args)

    def show_start_new_command(self, *args):
        self._client.show_start_new_command(*args)

    def show_bug_report(self, *args):
        self._client.show_bug_report(*args)

    def show_file_upload(self, *args):
        self._client.show_file_upload(*args)


    def log(self, message=""):
        log.info(message)


    def keyboard_layout_changed(self, *args):
        #used by win32 hooks to tell us about keyboard layout changes for this window
        keylog("keyboard_layout_changed%s", args)
        self._client.window_keyboard_layout_changed(self)


    def dbus_call(self, *args, **kwargs):
        #alias for rpc_call using dbus as rpc_type, see UIXpraClient.dbus_call
        if not self._client.server_dbus_proxy:
            log.error("Error: cannot send remote dbus call:")
            log.error(" this server does not support dbus-proxying")
            return
        rpc_args = [self._id]+args
        self._client.rpc_call("dbus", rpc_args, **kwargs)


    def get_mouse_event_wid(self, _x, _y):
        #overriden in GTKClientWindowBase
        return self._id

    def _do_motion_notify_event(self, event):
        if self._client.readonly or self._client.server_readonly or not self._client.server_pointer:
            return
        pointer, relative_pointer, modifiers, buttons = self._pointer_modifiers(event)
        wid = self.get_mouse_event_wid(*pointer)
        mouselog("do_motion_notify_event(%s) wid=%s / focus=%s / window wid=%i, device=%s, pointer=%s, relative pointer=%s, modifiers=%s, buttons=%s", event, wid, self._client._focused, self._id, self._device_info(event), pointer, relative_pointer, modifiers, buttons)
        pdata = pointer
        if self._client.server_pointer_relative:
            pdata = list(pointer)+list(relative_pointer)
        packet = ["pointer-position", wid, pdata, modifiers, buttons]
        self._client.send_mouse_position(packet)

    def _device_info(self, event):
        try:
            return event.device.get_name()
        except AttributeError:
            return ""

    def _button_action(self, button, event, depressed, *args):
        if self._client.readonly or self._client.server_readonly or not self._client.server_pointer:
            return
        pointer, relative_pointer, modifiers, buttons = self._pointer_modifiers(event)
        wid = self.get_mouse_event_wid(*pointer)
        mouselog("_button_action(%s, %s, %s) wid=%s / focus=%s / window wid=%i, device=%s, pointer=%s, modifiers=%s, buttons=%s",
                 button, event, depressed, wid, self._client._focused, self._id, self._device_info(event), pointer, modifiers, buttons)
        #map wheel buttons via translation table to support inverted axes:
        server_button = button
        if button>3:
            server_button = self._client.wheel_map.get(button)
            if not server_button:
                return
        server_buttons = []
        for b in buttons:
            if b>3:
                sb = self._client.wheel_map.get(button)
                if not sb:
                    continue
                b = sb
            server_buttons.append(b)
        pdata = pointer
        if self._client.server_pointer_relative:
            pdata = list(pointer)+list(relative_pointer)
        def send_button(pressed):
            self._client.send_button(wid, server_button, pressed, pdata, modifiers, server_buttons, *args)
        pressed_state = self.button_state.get(button, False)
        if SIMULATE_MOUSE_DOWN and pressed_state is False and depressed is False:
            mouselog("button action: simulating a missing mouse-down event for window %s before sending the mouse-up event", wid)
            #(needed for some dialogs on win32):
            send_button(True)
        self.button_state[button] = depressed
        send_button(depressed)

    def do_button_press_event(self, event):
        self._button_action(event.button, event, True)

    def do_button_release_event(self, event):
        self._button_action(event.button, event, False)
