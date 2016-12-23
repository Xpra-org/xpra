#!/usr/bin/env python
#
#gtkPopupNotify.py
#
# Copyright 2009 Daniel Woodhouse
# Copyright 2013 Antoine Martin <antoine@devloop.org.uk>
#
#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU Lesser General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU Lesser General Public License for more details.
#
#You should have received a copy of the GNU Lesser General Public License
#along with this program.  If not, see <http://www.gnu.org/licenses/>.
import gtk
import glib

from xpra.os_util import OSX
DEFAULT_FG_COLOUR = None
DEFAULT_BG_COLOUR = None
if OSX:
    #black on white fits better with osx
    DEFAULT_FG_COLOUR = gtk.gdk.Color("black")
    DEFAULT_BG_COLOUR = gtk.gdk.Color(62000, 62000, 62000)
DEFAULT_WIDTH = 340
DEFAULT_HEIGHT = 100

from xpra.gtk_common.gtk_util import add_close_accel
from xpra.client.notifications.notifier_base import NotifierBase, log


class GTK2_Notifier(NotifierBase):

    def __init__(self, size_x=DEFAULT_WIDTH, size_y=DEFAULT_HEIGHT, timeout=5):
        """
        Create a new notification stack.  The recommended way to create Popup instances.
          Parameters:
            `size_x` : The desired width of the notifications.
            `size_y` : The desired minimum height of the notifications. If the text is
            longer it will be expanded to fit.
            `timeout` : Popup instance will disappear after this timeout if there
            is no human intervention. This can be overridden temporarily by passing
            a new timout to the new_popup method.
        """
        self.size_x = size_x
        self.size_y = size_y
        self.timeout = timeout
        """
        Other parameters:
        These will take effect for every popup created after the change.
            `max_popups` : The maximum number of popups to be shown on the screen
            at one time.
            `bg_color` : if None default is used (usually grey). set with a gtk.gdk.Color.
            `fg_color` : if None default is used (usually black). set with a gtk.gdk.Color.
            `show_timeout : if True, a countdown till destruction will be displayed.

        """
        self.max_popups = 5
        self.fg_color = DEFAULT_FG_COLOUR
        self.bg_color = DEFAULT_BG_COLOUR
        self.show_timeout = False

        self._notify_stack = []
        self._offset = 0

        display = gtk.gdk.display_get_default()
        screen = display.get_default_screen()
        n = screen.get_n_monitors()
        log("screen=%s, monitors=%s", screen, n)
        if n<2:
            self.max_width = screen.get_width()
            self.max_height = screen.get_height()
            log("screen dimensions: %dx%d", self.max_width, self.max_height)
        else:
            rect = screen.get_monitor_geometry(0)
            self.max_width = rect.width
            self.max_height = rect.height
            log("first monitor dimensions: %dx%d", self.max_width, self.max_height)
        self.x = self.max_width - 20        #keep away from the edge
        self.y = self.max_height - 64        #space for a panel
        log("our reduced dimensions: %dx%d", self.x, self.y)

    def get_origin_x(self):
        return    self.x

    def get_origin_y(self):
        return    self.y

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, may_retry=True):
        """Create a new Popup instance."""
        if len(self._notify_stack) == self.max_popups:
            self._notify_stack[0].hide_notification()
        popup = Popup(self, summary, body, callback=None, image=None)
        self._notify_stack.append(popup)
        self._offset += self._notify_stack[-1].h
        return popup

    def destroy_popup_cb(self, popup):
        if popup in self._notify_stack:
            self._notify_stack.remove(popup)
            #move popups down if required
            offset = 0
            for note in self._notify_stack:
                offset = note.reposition(offset, self)
            self._offset = offset


class Popup(gtk.Window):
    def __init__(self, stack, title, message, callback, image):
        log("Popup%s", (stack, title, message, callback, image))
        self.stack = stack
        gtk.Window.__init__(self)

        self.set_size_request(stack.size_x, -1)
        self.set_decorated(False)
        self.set_deletable(False)
        self.set_property("skip-pager-hint", True)
        self.set_property("skip-taskbar-hint", True)
        self.connect("enter-notify-event", self.on_hover, True)
        self.connect("leave-notify-event", self.on_hover, False)
        self.set_opacity(0.2)
        self.set_keep_above(True)
        self.destroy_cb = stack.destroy_popup_cb

        main_box = gtk.VBox()
        header_box = gtk.HBox()
        self.header = gtk.Label()
        self.header.set_markup("<b>%s</b>" % title)
        self.header.set_padding(3, 3)
        self.header.set_alignment(0, 0)
        header_box.pack_start(self.header, True, True, 5)
        if True:
            close_button = gtk.Image()
            close_button.set_from_stock(gtk.STOCK_CANCEL, gtk.ICON_SIZE_BUTTON)
            close_button.set_padding(3, 3)
            close_window = gtk.EventBox()
            close_window.set_visible_window(False)
            close_window.connect("button-press-event", self.hide_notification)
            close_window.add(close_button)
            header_box.pack_end(close_window, False, False)
        main_box.pack_start(header_box)

        body_box = gtk.HBox()
        if image is not None:
            self.image = gtk.Image()
            self.image.set_size_request(70, 70)
            self.image.set_alignment(0, 0)
            self.image.set_from_pixbuf(image)
            body_box.pack_start(self.image, False, False, 5)
        self.message = gtk.Label()
        self.message.set_property("wrap", True)
        self.message.set_size_request(stack.size_x - 90, -1)
        self.message.set_alignment(0, 0)
        self.message.set_padding(5, 10)
        self.message.set_text(message)
        self.counter = gtk.Label()
        self.counter.set_alignment(1, 1)
        self.counter.set_padding(3, 3)
        self.timeout = stack.timeout

        body_box.pack_start(self.message, True, False, 5)
        body_box.pack_end(self.counter, False, False, 5)
        main_box.pack_start(body_box)

        if callback:
            cb_text, cb = callback
            button = gtk.Button(cb_text)
            button.set_relief(gtk.RELIEF_NORMAL)
            def popup_cb_clicked(*args):
                self.hide_notification()
                log("popup_cb_clicked%s", args)
                cb()
            button.connect("clicked", popup_cb_clicked)
            alignment = gtk.Alignment(xalign=1.0, yalign=0.5, xscale=0.0, yscale=0.0)
            alignment.add(button)
            main_box.pack_start(alignment)
        self.add(main_box)
        if stack.bg_color is not None:
            self.modify_bg(gtk.STATE_NORMAL, stack.bg_color)
        if stack.fg_color is not None:
            self.message.modify_fg(gtk.STATE_NORMAL, stack.fg_color)
            self.header.modify_fg(gtk.STATE_NORMAL, stack.fg_color)
            self.counter.modify_fg(gtk.STATE_NORMAL, stack.fg_color)
        self.show_timeout = stack.show_timeout
        self.hover = False
        self.show_all()
        self.w, self.h = self.size_request()
        self.move(self.get_x(self.w), self.get_y(self.h))
        self.wait_timer = None
        self.fade_out_timer = None
        self.fade_in_timer = glib.timeout_add(100, self.fade_in)
        #ensure we dont show it in the taskbar:
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.realize()
        add_close_accel(self, self.hide_notification)

    def get_x(self, w):
        x =    self.stack.get_origin_x() - w/2
        if (x + w) >= self.stack.max_width:    #dont overflow on the right
            x = self.stack.max_width - w
        if x <= 0:                                #or on the left
            x = 0
        log("get_x(%s)=%s", w, x)
        return    x

    def get_y(self, h):
        y = self.stack.get_origin_y()
        if y >= (self.stack.max_height/2):        #if near bottom, substract window height
            y = y - h
        if (y + h) >= self.stack.max_height:
            y = self.stack.max_height - h
        if y<= 0:
            y = 0
        log("get_y(%s)=%s", h, y)
        return    y

    def reposition(self, offset, stack):
        """Move the notification window down, when an older notification is removed"""
        log("reposition(%s, %s)", offset, stack)
        new_offset = self.h + offset
        self.move(self.get_x(self.w), self.get_y(new_offset))
        return new_offset

    def fade_in(self):
        opacity = self.get_opacity()
        opacity += 0.15
        if opacity >= 1:
            self.wait_timer = glib.timeout_add(1000, self.wait)
            self.fade_in_timer = None
            return False
        self.set_opacity(opacity)
        return True

    def wait(self):
        if not self.hover:
            self.timeout -= 1
        if self.show_timeout:
            self.counter.set_markup(str("<b>%s</b>" % self.timeout))
        if self.timeout == 0:
            self.fade_out_timer = glib.timeout_add(100, self.fade_out)
            self.wait_timer = None
            return False
        return True

    def fade_out(self):
        opacity = self.get_opacity()
        opacity -= 0.10
        if opacity <= 0:
            self.in_progress = False
            self.hide_notification()
            self.fade_out_timer = None  #redundant
            return False
        self.set_opacity(opacity)
        return True

    def on_hover(self, window, event, hover):
        """Starts/Stops the notification timer on a mouse in/out event"""
        self.hover = hover

    def hide_notification(self, *args):
        """Destroys the notification and tells the stack to move the
        remaining notification windows"""
        log("hide_notification%s", args)
        for timer in ("fade_in_timer", "fade_out_timer", "wait_timer"):
            v = getattr(self, timer)
            if v:
                setattr(self, timer, None)
                glib.source_remove(v)
        self.destroy()
        self.destroy_cb(self)



def main():
    #example usage
    import random
    color_combos = (("red", "white"), ("white", "blue"), ("green", "black"))
    messages = (("Hello", "This is a popup"),
            ("Some Latin", "Quidquid latine dictum sit, altum sonatur."),
            ("A long message", "The quick brown fox jumped over the lazy dog. " * 6))
    images = ("logo1_64.png", None)
    def notify_factory():
        color = random.choice(color_combos)
        message = random.choice(messages)
        image = random.choice(images)
        notifier.bg_color = gtk.gdk.Color(color[0])
        notifier.fg_color = gtk.gdk.Color(color[1])
        notifier.show_timeout = random.choice((True, False))
        notifier.new_popup(title=message[0], message=message[1], image=image)
        return True
    def gtk_main_quit():
        print("quitting")
        gtk.main_quit()

    notifier = GTK2_Notifier(timeout=6)
    glib.timeout_add(4000, notify_factory)
    glib.timeout_add(20000, gtk_main_quit)
    gtk.main()

if __name__ == "__main__":
    main()
