# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import re

from xpra.client.client_widget_base import ClientWidgetBase
from xpra.util import typedict, bytestostr, WORKSPACE_UNSET
from xpra.log import Logger
log = Logger("window")
plog = Logger("paint")
focuslog = Logger("focus")
mouselog = Logger("mouse")
workspacelog = Logger("workspace")
metalog = Logger("metadata")


class ClientWindowBase(ClientWidgetBase):

    def __init__(self, client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, border, max_window_size):
        log("%s%s", type(self), (client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, max_window_size))
        ClientWidgetBase.__init__(self, client, wid, metadata.boolget("has-alpha"))
        self._override_redirect = override_redirect
        self.group_leader = group_leader
        self._pos = (x, y)
        self._size = (w, h)
        self._client_properties = client_properties
        self._set_initial_position = False
        self.size_constraints = typedict()
        self.geometry_hints = {}
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
        self.border = border
        self.max_window_size = max_window_size
        self.button_state = {}

        self.init_window(metadata)
        self.setup_window()

    def __repr__(self):
        return "ClientWindow(%s)" % self._id

    def init_window(self, metadata):
        self._backing = None
        self._metadata = typedict()
        # used for only sending focus events *after* the window is mapped:
        self._been_mapped = False
        self._override_redirect_windows = []
        if "workspace" in self._client_properties:
            workspace = self._client_properties.get("workspace")
            if workspace is not None:
                workspacelog("workspace from client properties: %s", workspace)
                #client properties override application specified workspace value on init only:
                metadata["workspace"] = int(workspace)
        self._window_workspace = WORKSPACE_UNSET        #will get set in set_metadata if present
        self._desktop_workspace = self.get_desktop_workspace()
        workspacelog("init_window(..) workspace=%s, current workspace=%s", self._window_workspace, self._desktop_workspace)
        self.update_metadata(metadata)


    def get_desktop_workspace(self):
        return None

    def get_window_workspace(self):
        return None


    def new_backing(self, w, h):
        backing_class = self.get_backing_class()
        log("new_backing(%s, %s) backing_class=%s", w, h, backing_class)
        assert backing_class is not None
        self._backing = self.make_new_backing(backing_class, w, h)
        self._backing.border = self.border

    def destroy(self):
        #ensure we clear reference to other windows:
        self.group_leader = None
        self._override_redirect_windows = []
        self._metadata = {}
        if self._backing:
            self._backing.close()
            self._backing = None


    def setup_window(self):
        self.new_backing(*self._size)
        #tell the server about the encoding capabilities of this backing instance:
        #"rgb_formats", "full_csc_modes", "csc_modes":
        self._client_properties.update(self._backing.get_encoding_properties())


    def send(self, *args):
        self._client.send(*args)


    def update_icon(self, width, height, coding, data):
        raise Exception("override me!")

    def is_realized(self):
        raise Exception("override me!")

    def apply_transient_for(self, wid):
        raise Exception("override me!")

    def paint_spinner(self, context, area):
        raise Exception("override me!")

    def _pointer_modifiers(self, event):
        raise Exception("override me!")


    def xget_u32_property(self, target, name):
        raise Exception("override me!")



    def is_OR(self):
        return self._override_redirect


    def update_metadata(self, metadata):
        metalog("update_metadata(%s)", metadata)
        self._metadata.update(metadata)
        if not self.is_realized():
            #Warning: window managers may ignore the icons we try to set
            #if the wm_class value is set and matches something somewhere undocumented
            #(if the default is used, you cannot override the window icon)
            self.set_wmclass(*self._metadata.strlistget("class-instance", ("xpra", "Xpra")))
        try:
            self.set_metadata(metadata)
        except Exception:
            metalog.warn("failed to set window metadata to '%s'", metadata, exc_info=True)

    def set_metadata(self, metadata):
        metalog("set_metadata(%s)", metadata)
        if b"title" in metadata:
            try:
                title = bytestostr(self._client.title).replace("\0", "")
                if title.find("@")>=0:
                    #perform metadata variable substitutions:
                    #full of py3k unicode headaches that don't need to be
                    default_values = {"title"           : "<untitled window>",
                                      "client-machine"  : "<unknown machine>"}
                    def metadata_replace(match):
                        atvar = match.group(0)          #ie: '@title@'
                        var = atvar[1:len(atvar)-1]     #ie: 'title'
                        default_value = default_values.get(var, "<unknown %s>" % var)
                        value = self._metadata.strget(var, default_value)
                        if sys.version<'3':
                            value = value.decode("utf-8")
                        return value
                    title = re.sub("@[\w\-]*@", metadata_replace, title)
                    if sys.version<'3':
                        utf8_title = title.encode("utf-8")
                    else:
                        utf8_title = title
            except Exception as e:
                log.error("error parsing window title: %s", e)
                utf8_title = b""
            self.set_title(utf8_title)

        if b"icon-title" in metadata:
            icon_title = metadata.strget("icon-title")
            self.set_icon_name(icon_title)

        if b"size-constraints" in metadata:
            self.size_constraints = typedict(metadata.dictget("size-constraints"))
            self.set_size_constraints(self.size_constraints, self.max_window_size)

        if b"transient-for" in metadata:
            wid = metadata.intget("transient-for", -1)
            self.apply_transient_for(wid)

        if b"modal" in metadata:
            modal = metadata.boolget("modal")
            self.set_modal(modal)

        #apply window-type hint if window has not been mapped yet:
        if b"window-type" in metadata and not self.is_mapped():
            window_types = metadata.strlistget("window-type")
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
                opacity = min(1, opacity/float(0xffffffff))
            #requires gtk>=2.12!
            if hasattr(self, "set_opacity"):
                self.set_opacity(opacity)

        if b"has-alpha" in metadata:
            new_alpha = metadata.boolget("has-alpha")
            if new_alpha!=self._has_alpha:
                log.warn("window %s changed its alpha flag from %s to %s (unsupported)", self._id, self._has_alpha, new_alpha)
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
                self.set_skip_taskbar_hint(skip_pager)

        if b"workspace" in metadata:
            self.set_workspace(metadata.intget("workspace"))

        if b"bypass-compositor" in metadata:
            self.set_bypass_compositor(metadata.intget("bypass-compositor"))

        if b"strut" in metadata:
            self.set_strut(metadata.dictget("strut"))

        if b"fullscreen-monitors" in metadata:
            self.set_fullscreen_monitors(metadata.intlistget("fullscreen-monitors"))

        if b"shape" in metadata:
            self.set_shape(metadata.dictget("shape"))

    def set_shape(self, shape):
        log("set_shape(%s) not implemented", shape)

    def set_bypass_compositor(self, v):
        pass        #see gtk client window base

    def set_strut(self, d):
        pass        #see gtk client window base

    def set_fullscreen_monitors(self, fsm):
        pass        #see gtk client window base

    def set_shaded(self, shaded):
        pass        #see gtk client window base


    def set_size_constraints(self, size_constraints, max_window_size):
        self._set_initial_position = size_constraints.get("set-initial-position")
        hints = {}
        for (a, h1, h2) in [
            ("maximum-size", "max_width", "max_height"),
            ("minimum-size", "min_width", "min_height"),
            ("base-size", "base_width", "base_height"),
            ("increment", "width_inc", "height_inc"),
            ]:
            v = size_constraints.intlistget(a)
            if v:
                v1, v2 = v
                hints[h1], hints[h2] = int(v1), int(v2)
        for (a, h) in [
            ("minimum-aspect-ratio", "min_aspect"),
            ("maximum-aspect-ratio", "max_aspect"),
            ]:
            v = size_constraints.intlistget(a)
            if v:
                v1, v2 = v
                hints[h] = float(v1)/float(v2)
        #apply max-size override if needed:
        w,h = max_window_size
        if w>0 and h>0 and not self._fullscreen:
            #get the min size, if there is one:
            minw = max(1, hints.get("min_width", 1))
            minh = max(1, hints.get("min_height", 1))
            #the actual max size is:
            # * greater than the min-size
            # * the lowest of the max-size set by the application and the one we have
            # * ensure we honour the other hints, and round the max-size down if needed:
            #according to the GTK docs:
            #allowed window widths are base_width + width_inc * N where N is any integer
            #allowed window heights are base_height + width_inc * N where N is any integer
            maxw = hints.get("max_width", 32768)
            maxh = hints.get("max_height", 32768)
            maxw = max(minw, min(w, maxw))
            maxh = max(minh, min(h, maxh))
            rw = (maxw - hints.get("base_width", 0)) % max(hints.get("width_inc", 1), 1)
            rh = (maxh - hints.get("base_height", 0)) % max(hints.get("height_inc", 1), 1)
            maxw -= rw
            maxh -= rh
            #if the hints combination is invalid, it's possible that we'll end up
            #not honouring "base" + "inc", but honouring just "min" instead:
            maxw = max(minw, maxw)
            maxh = max(minh, maxh)
            metalog("modified hints for max window size %s: %s (rw=%s, rh=%s) -> max=%sx%s", max_window_size, hints, rw, rh, maxw, maxh)
            hints["max_width"] = maxw
            hints["max_height"] = maxh
        try:
            metalog("calling: %s(%s)", self.apply_geometry_hints, hints)
            #save them so the window hooks can use the last value used:
            self.geometry_hints = hints
            self.apply_geometry_hints(hints)
        except:
            metalog.error("with hints=%s", hints, exc_info=True)
        #TODO: handle gravity
        #gravity = size_metadata.get("gravity")

    def set_window_type(self, window_types):
        hints = 0
        for window_type in window_types:
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

    def magic_key(self, *args):
        log.info("magic_key(%s) not handled in %s", args, type(self))

    def refresh_window(self, *args):
        log("refresh_window(%s) wid=%s", args, self._id)
        self._client.send_refresh(self._id)

    def refresh_all_windows(self):
        #this method is only here because we may want to fire it
        #from a --key-shortcut action and the event is delivered to
        #the "ClientWindow"
        self._client.send_refresh_all()

    def draw_region(self, x, y, width, height, coding, img_data, rowstride, packet_sequence, options, callbacks):
        """ Note: this runs from the draw thread (not UI thread) """
        backing = self._backing
        if not backing:
            log("draw_region: window %s has no backing, gone?", self._id)
            from xpra.client.window_backing_base import fire_paint_callbacks
            fire_paint_callbacks(callbacks, False)
            return
        def after_draw_refresh(success):
            plog("after_draw_refresh(%s) %sx%s at %sx%s encoding=%s, options=%s", success, width, height, x, y, coding, options)
            if not success:
                return
            backing = self._backing
            if backing and backing.draw_needs_refresh:
                self.queue_draw(x, y, width, height)
        #only register this callback if we actually need it:
        if backing.draw_needs_refresh:
            callbacks.append(after_draw_refresh)
        self._backing.draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)

    def spinner(self, ok):
        if not self.can_have_spinner():
            return
        log("spinner(%s) queueing redraw")
        #with normal windows, we just queue a draw request
        #and let the expose event paint the spinner
        w, h = self.get_size()
        self.queue_draw(self, 0, 0, w, h)

    def can_have_spinner(self):
        if self._backing is None:
            return False
        window_types = self._metadata.strlistget("window-type")
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

    def show_start_new_command(self, *args):
        self._client.show_start_new_command(*args)


    def log(self, message=""):
        log.info(message)

    def dbus_call(self, *args, **kwargs):
        #see UIXpraClient.dbus_call
        return self._client.dbus_call(self._id, *args, **kwargs)


    def get_mouse_event_wid(self):
        #on OSX, the mouse events are reported against the wrong window by GTK,
        #so we have to use the currently focused window
        if sys.platform.startswith("darwin"):
            return self._client._focused or self._id
        return self._id

    def do_motion_notify_event(self, event):
        if self._client.readonly:
            return
        pointer, modifiers, buttons = self._pointer_modifiers(event)
        wid = self.get_mouse_event_wid()
        mouselog("do_motion_notify_event(%s) wid=%s / focus=%s, pointer=%s, modifiers=%s, buttons=%s", event, self._id, self._client._focused, pointer, modifiers, buttons)
        self._client.send_mouse_position(["pointer-position", wid,
                                          pointer, modifiers, buttons])

    def _button_action(self, button, event, depressed):
        if self._client.readonly:
            return
        pointer, modifiers, buttons = self._pointer_modifiers(event)
        wid = self.get_mouse_event_wid()
        mouselog("_button_action(%s, %s, %s) wid=%s / focus=%s, pointer=%s, modifiers=%s, buttons=%s", button, event, depressed, self._id, self._client._focused, pointer, modifiers, buttons)
        def send_button(pressed):
            self._client.send_button(wid, button, pressed, pointer, modifiers, buttons)
        pressed_state = self.button_state.get(button, False)
        if pressed_state is False and depressed is False:
            mouselog("button action: simulating a missing mouse-down event for window %s before sending the mouse-up event", wid)
            #(needed for some dialogs on win32):
            send_button(True)
        self.button_state[button] = depressed
        send_button(depressed)

    def do_button_press_event(self, event):
        self._button_action(event.button, event, True)

    def do_button_release_event(self, event):
        self._button_action(event.button, event, False)

    def do_scroll_event(self, event):
        if self._client.readonly:
            return
        button_mapping = self.SCROLL_MAP.get(event.direction, -1)
        mouselog("do_scroll_event direction=%s, button_mapping=%s", event.direction, button_mapping)
        if button_mapping>=0:
            self._button_action(button_mapping, event, True)
            self._button_action(button_mapping, event, False)
