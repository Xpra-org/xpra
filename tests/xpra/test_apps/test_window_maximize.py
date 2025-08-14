#!/usr/bin/env python3

from xpra.os_util import gi_import

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")


def main():
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_size_request(220, 120)
    window.connect("delete_event", Gtk.main_quit)
    vbox = Gtk.VBox(homogeneous=False, spacing=0)

    def add_buttons(t1, cb1, t2, cb2):
        hbox = Gtk.HBox(homogeneous=True, spacing=10)
        b1 = Gtk.Button(t1)

        def vcb1(*_args):
            cb1()

        b1.connect('clicked', vcb1)
        hbox.pack_start(b1, expand=True, fill=False, padding=5)
        b2 = Gtk.Button(t2)

        def vcb2(*_args):
            cb2()

        b2.connect('clicked', vcb2)
        hbox.pack_start(b2, expand=True, fill=False, padding=5)
        vbox.pack_start(hbox, expand=False, fill=False, padding=2)

    def send_maximized_wm_state(mode):
        from xpra.x11.gtk.display_source import init_gdk_display_source
        init_gdk_display_source()
        from xpra.x11.bindings.core import constants
        from xpra.x11.bindings.window import X11WindowBindings
        X11Window = X11WindowBindings()
        root = window.get_window().get_screen().get_root_window()
        root_xid = root.get_xid()
        xwin = window.get_window().get_xid()
        SubstructureNotifyMask = constants["SubstructureNotifyMask"]
        SubstructureRedirectMask = constants["SubstructureRedirectMask"]
        event_mask = SubstructureNotifyMask | SubstructureRedirectMask
        X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_WM_STATE", mode,
                                    "_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ", 0, 0)

    def maximize_X11(*args):
        send_maximized_wm_state(1)  #ADD

    def unmaximize_X11(*args):
        send_maximized_wm_state(2)  #REMOVE

    add_buttons("maximize", window.maximize, "unmaximize", window.unmaximize)
    add_buttons("maximize X11", maximize_X11, "unmaximize X11", unmaximize_X11)
    add_buttons("fullscreen", window.fullscreen, "unfullscreen", window.unfullscreen)

    def window_state(widget, event):
        STATES = {
            Gdk.WindowState.WITHDRAWN: "withdrawn",
            Gdk.WindowState.ICONIFIED: "iconified",
            Gdk.WindowState.MAXIMIZED: "maximized",
            Gdk.WindowState.STICKY: "sticky",
            Gdk.WindowState.FULLSCREEN: "fullscreen",
            Gdk.WindowState.ABOVE: "above",
            Gdk.WindowState.BELOW: "below",
        }
        print("window_state(%s, %s)" % (widget, event))
        print("flags: %s" % [STATES[x] for x in STATES.keys() if x & event.new_window_state])
    window.connect("window-state-event", window_state)

    window.add(vbox)
    window.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    main()
