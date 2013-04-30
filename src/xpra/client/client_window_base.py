# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import sys

from xpra.log import Logger
log = Logger()

#pretend to draw the windows, but don't actually do anything
USE_FAKE_BACKING = os.environ.get("XPRA_USE_FAKE_BACKING", "0")=="1"
DRAW_DEBUG = os.environ.get("XPRA_DRAW_DEBUG", "0")=="1"
if sys.version < '3':
    import codecs
    def u(x):
        return codecs.unicode_escape_decode(x)[0]
else:
    def u(x):
        return x


class ClientWindowBase(object):
    def __init__(self, client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay):
        #gobject-like scheduler:
        self.source_remove = client.source_remove
        self.idle_add = client.idle_add
        self.timeout_add = client.timeout_add
        self._client = client
        self._override_redirect = override_redirect
        self._can_set_workspace = False
        self.group_leader = group_leader
        self._id = wid
        self._pos = (x, y)
        self._size = (w, h)
        self._backing = None
        self._metadata = {}
        self._client_properties = client_properties
        self._auto_refresh_delay = auto_refresh_delay
        self._refresh_timer = None
        self._refresh_min_pixels = -1
        self._refresh_ignore_sequence = -1
        # used for only sending focus events *after* the window is mapped:
        self._been_mapped = False
        self._override_redirect_windows = []

        self.init_window(metadata)

    def init_window(self, metadata):
        self.new_backing(*self._size)
        self.update_metadata(metadata)


    def make_new_backing(self, backing_class, w, h):
        w = max(1, w)
        h = max(1, h)
        lock = None
        if self._backing:
            lock = self._backing._video_decoder_lock
        try:
            if lock:
                lock.acquire()
            if self._backing is None:
                if USE_FAKE_BACKING:
                    from xpra.client.fake_window_backing import FakeBacking
                    backing_class = FakeBacking
                backing = backing_class(self._id, w, h)
                if self._client.mmap_enabled:
                    backing.enable_mmap(self._client.mmap)
            backing.init(w, h)
        finally:
            if lock:
                lock.release()
        return backing

    def new_backing(self, w, h):
        raise Exception("override me!")

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

    def do_set_workspace(self, workspace):
        raise Exception("override me!")


    def set_workspace(self):
        if not self._can_set_workspace or self._been_mapped:
            return -1
        workspace = self._client_properties.get("workspace", -1)
        log("set_workspace() workspace=%s", workspace)
        if workspace<0 or workspace==self.get_current_workspace():
            return -1
        try:
            return self.do_set_workspace(workspace)
        except Exception, e:
            log.error("failed to set workspace: %s", e)
            return -1


    def is_OR(self):
        return self._override_redirect

    def is_tray(self):
        return False

    def is_GL(self):
        return False


    def update_metadata(self, metadata):
        self._metadata.update(metadata)

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
        self.set_title(title)

        if "size-constraints" in self._metadata:
            size_metadata = self._metadata["size-constraints"]
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
            #TODO:
            #gravity = size_metadata.get("gravity")

        if not self.is_realized():
            self.set_wmclass(*self._metadata.get("class-instance",
                                                 ("xpra", "Xpra")))

        modal = self._metadata.get("modal", False)
        self.set_modal(modal or False)

        if "icon" in self._metadata:
            width, height, coding, data = self._metadata["icon"]
            self.update_icon(width, height, coding, data)

        if "transient-for" in self._metadata:
            wid = self._metadata.get("transient-for")
            self.apply_transient_for(wid)

        #apply window-type hint if window is not mapped yet:
        if "window-type" in self._metadata and not self.is_mapped():
            window_types = self._metadata.get("window-type")
            self.set_window_type(window_types)

    def set_window_type(self, window_types):
        log("set_window_type(%s)", window_types)
        hints = 0
        for window_type in window_types:
            hint = self.NAME_TO_HINT.get(window_type)
            if hint:
                hints |= hint
        log("setting window type to %s - %s", window_type, hint)
        self.set_type_hint(hint)


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
            if DRAW_DEBUG:
                log.info("after_draw_refresh(%s) options=%s", success, options)
            if success and self._backing and self._backing.draw_needs_refresh:
                self.queue_draw(x, y, width, height)
            #clear the auto refresh if enough pixels were sent (arbitrary limit..)
            if success and self._refresh_timer and width*height>=self._refresh_min_pixels:
                self.source_remove(self._refresh_timer)
                self._refresh_timer = None
            #if we need to set a refresh timer, do it:
            is_hq = options.get("quality", 0)>=95
            is_lossy = coding in ("jpeg", "vpx", "x264")
            if self._refresh_timer is None and self._auto_refresh_delay>0 and is_lossy and not is_hq:
                #make sure our own refresh does not make us fire again
                #FIXME: this should be per-window!
                if self._refresh_ignore_sequence<packet_sequence:
                    #NOTE: for x264 and vpx, we always get full frames (whole window refresh)
                    #this is not the case with jpeg but since jpeg does not switch the encoding on the fly, we're ok
                    self._refresh_min_pixels = width*height
                    self._refresh_ignore_sequence = packet_sequence+1
                    self._refresh_timer = self.timeout_add(int(1000 * self._auto_refresh_delay), self.refresh_window)
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
        window_types = self._metadata.get("window-type")
        return ("_NET_WM_WINDOW_TYPE_NORMAL" in window_types) or \
               ("_NET_WM_WINDOW_TYPE_DIALOG" in window_types) or \
               ("_NET_WM_WINDOW_TYPE_SPLASH" in window_types)


    def _unfocus(self):
        if self._client._focused==self._id:
            self._client.update_focus(self._id, False)

    def quit(self):
        self._client.quit(0)

    def void(self):
        pass


    def do_motion_notify_event(self, event):
        if self._client.readonly:
            return
        pointer, modifiers, buttons = self._pointer_modifiers(event)
        self._client.send_mouse_position(["pointer-position", self._id,
                                          pointer, modifiers, buttons])

    def _button_action(self, button, event, depressed):
        if self._client.readonly:
            return
        pointer, modifiers, buttons = self._pointer_modifiers(event)
        self._client.send_positional(["button-action", self._id,
                                      button, depressed,
                                      pointer, modifiers, buttons])

    def do_button_press_event(self, event):
        self._button_action(event.button, event, True)

    def do_button_release_event(self, event):
        self._button_action(event.button, event, False)

    def do_scroll_event(self, event):
        if self._client.readonly:
            return
        self._button_action(self.SCROLL_MAP[event.direction], event, True)
        self._button_action(self.SCROLL_MAP[event.direction], event, False)
