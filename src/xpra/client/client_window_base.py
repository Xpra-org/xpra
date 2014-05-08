# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import sys

from xpra.client.client_widget_base import ClientWidgetBase
from xpra.codecs.video_helper import getVideoHelper
from xpra.log import Logger
log = Logger("window")
plog = Logger("paint")
focuslog = Logger("focus")
mouselog = Logger("mouse")

if sys.version < '3':
    import codecs
    def u(x):
        return codecs.unicode_escape_decode(x)[0]
else:
    def u(x):
        return x


class ClientWindowBase(ClientWidgetBase):

    def __init__(self, client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, border):
        log("%s%s", type(self), (client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties))
        has_alpha = self.get_backing_class().HAS_ALPHA
        ClientWidgetBase.__init__(self, client, wid, has_alpha)
        self._override_redirect = override_redirect
        self.group_leader = group_leader
        self._pos = (x, y)
        self._size = (w, h)
        self._client_properties = client_properties
        self.border = border
        self.button_state = {}

        self.init_window(metadata)
        self.setup_window()

    def __repr__(self):
        return "ClientWindow(%s)" % self._id

    def init_window(self, metadata):
        self._backing = None
        self._metadata = {}
        # used for only sending focus events *after* the window is mapped:
        self._been_mapped = False
        self._override_redirect_windows = []
        self.update_metadata(metadata)

    def new_backing(self, w, h):
        backing_class = self.get_backing_class()
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
        rgb_modes = self.get_backing_class().RGB_MODES
        self._client_properties["encodings.rgb_formats"] = rgb_modes
        self._client_properties["encoding.full_csc_modes"] = self._get_full_csc_modes(rgb_modes)
        self._client_properties["encoding.csc_modes"] = self._get_csc_modes(rgb_modes)
        self.new_backing(*self._size)

    def _get_full_csc_modes(self, rgb_modes):
        #calculate the server CSC modes the server is allowed to use
        #based on the client CSC modes we can convert to in the backing class we use
        #and trim the transparency if we cannot handle it
        target_rgb_modes = list(rgb_modes)
        if not self._has_alpha:
            target_rgb_modes = [x for x in target_rgb_modes if x.find("A")<0]
        full_csc_modes = getVideoHelper().get_server_full_csc_modes_for_rgb(*target_rgb_modes)
        log("full csc modes (%s)=%s", target_rgb_modes, full_csc_modes)
        return full_csc_modes

    def _get_csc_modes(self, rgb_modes):
        #as above, but for older servers: less detailed than "full" csc modes info
        csc_modes = []
        for modes in self._get_full_csc_modes(rgb_modes).values():
            csc_modes += modes
        csc_modes = list(set(csc_modes))
        return csc_modes


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
        #normalize window-type:
        window_type = metadata.get("window-type")
        if window_type is not None:
            #normalize the window type for servers that don't do "generic_window_types"
            window_type = [x.replace("_NET_WM_WINDOW_TYPE_", "").replace("_NET_WM_TYPE_", "") for x in window_type]
            metadata["window-type"] = window_type

        self._metadata.update(metadata)
        if not self.is_realized():
            self.set_wmclass(*self._metadata.get("class-instance",
                                                 ("xpra", "Xpra")))
        self.set_metadata(metadata)

    def set_metadata(self, metadata):
        if "title" in metadata:
            try:
                title = u(self._client.title)
                if title.find("@")>=0:
                    #perform metadata variable substitutions:
                    default_values = {"title" : u("<untitled window>"),
                                      "client-machine" : u("<unknown machine>")}
                    def metadata_replace(match):
                        atvar = match.group(0)          #ie: '@title@'
                        var = atvar[1:len(atvar)-1]     #ie: 'title'
                        default_value = default_values.get(var, u("<unknown %s>") % var)
                        value = self._metadata.get(var, default_value)
                        if sys.version<'3':
                            value = value.decode("utf-8")
                        return value
                    title = re.sub("@[\w\-]*@", metadata_replace, title)
                utf8_title = title.encode("utf-8")
            except Exception, e:
                log.error("error parsing window title: %s", e)
                utf8_title = ""
            self.set_title(utf8_title)

        if "icon-title" in metadata:
            icon_title = metadata["icon-title"]
            self.set_icon_name(icon_title)

        if "size-constraints" in metadata:
            size_metadata = metadata["size-constraints"]
            hints = {}
            for (a, h1, h2) in [
                ("maximum-size", "max_width", "max_height"),
                ("minimum-size", "min_width", "min_height"),
                ("base-size", "base_width", "base_height"),
                ("increment", "width_inc", "height_inc"),
                ]:
                v = size_metadata.get(a)
                if v:
                    v1, v2 = v
                    hints[h1], hints[h2] = int(v1), int(v2)
            for (a, h) in [
                ("minimum-aspect-ratio", "min_aspect"),
                ("maximum-aspect-ratio", "max_aspect"),
                ]:
                v = size_metadata.get(a)
                if v:
                    v1, v2 = v
                    hints[h] = float(v1)/float(v2)
            try:
                self.apply_geometry_hints(hints)
            except:
                log.error("with hints=%s", hints, exc_info=True)
            #TODO: handle gravity
            #gravity = size_metadata.get("gravity")

        if "icon" in metadata:
            width, height, coding, data = metadata["icon"]
            self.update_icon(width, height, coding, data)

        if "transient-for" in metadata:
            wid = metadata["transient-for"]
            self.apply_transient_for(wid)

        if "modal" in metadata:
            modal = bool(metadata["modal"])
            self.set_modal(modal)

        #apply window-type hint if window has not been mapped yet:
        if "window-type" in metadata and not self.is_mapped():
            window_types = metadata["window-type"]
            self.set_window_type(window_types)

        if "role" in metadata:
            role = metadata["role"]
            self.set_role(role)

        if "xid" in metadata:
            xid = metadata["xid"]
            self.set_xid(xid)

        if "opacity" in metadata:
            opacity = metadata["opacity"]
            if opacity<0:
                opacity = 1
            else:
                opacity = min(1, opacity/float(0xffffffff))
            self.set_opacity(opacity)

        if "has-alpha" in metadata:
            self._has_alpha = bool(metadata["has-alpha"])
            self.set_alpha()

        if "maximized" in metadata:
            maximized = bool(metadata["maximized"])
            if maximized:
                self.maximize()
            else:
                self.unmaximize()

        if "fullscreen" in metadata:
            fullscreen = bool(metadata["fullscreen"])
            self.set_fullscreen(fullscreen)


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

    def set_fullscreen(self, fullscreen):
        pass

    def set_alpha(self):
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
        assert self._backing, "window %s has no backing!" % self._id
        def after_draw_refresh(success):
            plog("after_draw_refresh(%s) %sx%s at %sx%s encoding=%s, options=%s", success, width, height, x, y, coding, options)
            if success and self._backing and self._backing.draw_needs_refresh:
                self.queue_draw(x, y, width, height)
        callbacks.append(after_draw_refresh)
        self._backing.draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)

    def spinner(self, ok):
        if not self.can_have_spinner():
            return
        #with normal windows, we just queue a draw request
        #and let the expose event paint the spinner
        w, h = self.get_size()
        self.queue_draw(self, 0, 0, w, h)

    def can_have_spinner(self):
        if self._backing is None:
            return False
        window_types = self._metadata.get("window-type")
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

    def log(self, message=""):
        log.info(message)

    def dbus_call(self, *args, **kwargs):
        #see UIXpraClient.dbus_call
        return self._client.dbus_call(self._id, *args, **kwargs)

    def do_motion_notify_event(self, event):
        if self._client.readonly:
            return
        pointer, modifiers, buttons = self._pointer_modifiers(event)
        mouselog("do_motion_notify_event(%s) wid=%s, pointer=%s, modifiers=%s, buttons=%s", event, self._id, pointer, modifiers, buttons)
        self._client.send_mouse_position(["pointer-position", self._id,
                                          pointer, modifiers, buttons])

    def _button_action(self, button, event, depressed):
        if self._client.readonly:
            return
        pointer, modifiers, buttons = self._pointer_modifiers(event)
        mouselog("_button_action(%s, %s, %s) wid=%s, pointer=%s, modifiers=%s, buttons=%s", button, event, depressed, self._id, pointer, modifiers, buttons)
        def send_button(pressed):
            self._client.send_positional(["button-action", self._id,
                                          button, pressed,
                                          pointer, modifiers, buttons])
        pressed_state = self.button_state.get(button, False)
        if pressed_state is False and depressed is False:
            mouselog("button action: simulating a missing mouse-down event for window %s before sending the mouse-up event", self._id)
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
