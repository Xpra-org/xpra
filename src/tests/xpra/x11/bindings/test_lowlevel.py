# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from wimpiggy.test import *
import wimpiggy.lowlevel as l
import gtk
from xpra.x11.gtk_x11.error import trap, XError

class TestLowlevel(TestWithSession):
    def root(self, disp=None):
        if disp is None:
            disp = self.display
        return disp.get_default_screen().get_root_window()

    def window(self, disp=None):
        if disp is None:
            disp = self.display
        win = gtk.gdk.Window(self.root(disp), width=10, height=10,
                             # WINDOW_CHILD is sort of bogus, but it reduces
                             # the amount of magic that GDK will do (e.g.,
                             # WINDOW_TOPLEVELs automatically get a child
                             # window to be used in focus management).
                             window_type=gtk.gdk.WINDOW_CHILD,
                             wclass=gtk.gdk.INPUT_OUTPUT,
                             event_mask=0)
        return win

class TestLowlevelMisc(TestLowlevel):
    def test_get_xwindow_pywindow(self):
        d2 = self.clone_display()
        r1 = self.root()
        r2 = self.root(d2)
        assert r1 is not r2
        assert l.get_xwindow(r1) == l.get_xwindow(r2)
        win = self.window()
        assert l.get_xwindow(r1) != l.get_xwindow(win)
        assert l.get_pywindow(r2, l.get_xwindow(r1)) is r2

        assert_raises(l.XError, l.get_pywindow, self.display, 0)

        # This is necessary to stop some mysterious failure (perhaps d2 being
        # garbage collected before r2):
        del r2

    def test_get_display_for(self):
        assert l.get_display_for(self.display) is self.display
        win = self.window()
        assert l.get_display_for(win) is self.display
        assert_raises(TypeError, l.get_display_for, None)
        widg = gtk.Window()
        assert l.get_display_for(widg) is self.display
        clipboard = gtk.Clipboard(self.display, "PRIMARY")
        assert l.get_display_for(clipboard) is self.display

    def test_get_xatom_pyatom(self):
        d2 = self.clone_display()
        asdf1 = l.get_xatom("ASDF")
        asdf2 = l.get_xatom("ASDF")
        ghjk1 = l.get_xatom("GHJK")
        ghjk2 = l.get_xatom("GHJK")
        assert asdf1 == asdf2
        assert ghjk1 == ghjk2
        assert l.get_pyatom(self.display, asdf2) == "ASDF"
        assert l.get_pyatom(d2, ghjk1) == "GHJK"

    def test_property(self):
        r = self.root()
        data = "\x01\x02\x03\x04\x05\x06\x07\x08"
        assert_raises(l.NoSuchProperty,
                      l.XGetWindowProperty, r, "ASDF", "ASDF")
        l.XChangeProperty(r, "ASDF", ("GHJK", 32, data))
        assert_raises(l.BadPropertyType,
                      l.XGetWindowProperty, r, "ASDF", "ASDF")

        for n in (8, 16, 32):
            print(n)
            l.XChangeProperty(r, "ASDF", ("GHJK", n, data))
            assert l.XGetWindowProperty(r, "ASDF", "GHJK") == data

        l.XDeleteProperty(r, "ASDF")
        assert_raises(l.NoSuchProperty,
                      l.XGetWindowProperty, r, "ASDF", "GHJK")

        badwin = self.window()
        badwin.destroy()
        assert_raises((l.PropertyError, XError),
                      trap.call, l.XGetWindowProperty, badwin, "ASDF", "ASDF")

        # Giant massive property
        l.XChangeProperty(r, "ASDF",
                          ("GHJK", 32, "\x00" * 512 * (2 ** 10)))
        assert_raises(l.PropertyOverflow,
                      l.XGetWindowProperty, r, "ASDF", "GHJK")

    def test_BadProperty_on_empty(self):
        win = self.window()
        l.XChangeProperty(win, "ASDF", ("GHJK", 32, ""))
        assert l.XGetWindowProperty(win, "ASDF", "GHJK") == ""
        assert_raises(l.BadPropertyType,
                      l.XGetWindowProperty, win, "ASDF", "ASDF")

    def test_get_children_and_get_parent_and_reparent(self):
        d2 = self.clone_display()
        w1 = self.window(self.display)
        w2 = self.window(d2)
        gtk.gdk.flush()

        assert not l.get_children(w1)
        children = l.get_children(self.root())
        xchildren = map(l.get_xwindow, children)
        xwins = map(l.get_xwindow, [w1, w2])
        # GDK creates an invisible child of the root window on each
        # connection, so there are some windows we don't know about:
        for known in xwins:
            assert known in xchildren
        assert l.get_parent(w1) == w1.get_parent()

        w1.reparent(l.get_pywindow(w1, l.get_xwindow(w2)), 0, 0)
        gtk.gdk.flush()
        assert map(l.get_xwindow, l.get_children(w2)) == [l.get_xwindow(w1)]
        assert l.get_parent(w1).xid == w2.xid

    def test_get_parent_of_root(self):
        assert l.get_parent(self.root()) is None

    def test_save_set(self):
        w1 = self.window(self.display)
        w2 = self.window(self.display)
        w3 = self.window(self.display)
        gtk.gdk.flush()

        def do_child(disp_name, xwindow1, xwindow2, xwindow3):
            print("child: in do_child")
            d2 = gtk.gdk.Display(disp_name)
            w1on2 = l.get_pywindow(d2, xwindow1)
            w2on2 = l.get_pywindow(d2, xwindow2)
            w3on2 = l.get_pywindow(d2, xwindow3)
            mywin = self.window(d2)
            print("child: mywin == %s" % l.get_xwindow(mywin))
            w1on2.reparent(mywin, 0, 0)
            w2on2.reparent(mywin, 0, 0)
            w3on2.reparent(mywin, 0, 0)
            gtk.gdk.flush()
            # w1 gets saved:
            l.XAddToSaveSet(w1on2)
            # w2 does not
            # w3 is saved, but then unsaved (to test RemoveFromSaveSet):
            l.XAddToSaveSet(w3on2)
            l.XRemoveFromSaveSet(w3on2)
            gtk.gdk.flush()
            print("child: finished")
        import os
        print("prefork: ", os.getpid())
        pid = os.fork()
        if not pid:
            # Child
            try:
                print("child: pid ", os.getpid())
                name = self.display.get_name()
                # This is very important, though I don't know why.  If we
                # don't close this display then something inside
                # xcb_wait_for_reply gets Very Confused and the *parent*
                # process gets a spurious IO error with nonsense errno
                # (because errno is not actually being set, because there is
                # no IO error, just something going weird inside xcb).  I'm
                # not even sure that this actually fixes the underlying
                # problem, but it makes the test pass, so...
                self.display.close()
                do_child(name,
                         l.get_xwindow(w1),
                         l.get_xwindow(w2),
                         l.get_xwindow(w3))
            finally:
                os._exit(0)
        # Parent
        print("parent: ", os.getpid())
        print("parent: child is ", pid)
        print("parent: waiting for child")
        os.waitpid(pid, 0)
        print("parent: child exited")
        # Is there a race condition here, where the child exits but the X
        # server doesn't notice until after we send our commands?
        print(map(l.get_xwindow, [w1, w2, w3]))
        print(map(l.get_xwindow, l.get_children(self.root())))
        assert w1 in l.get_children(self.root())
        assert w2 not in l.get_children(self.root())
        assert w3 not in l.get_children(self.root())

    def test_is_mapped(self):
        win = self.window()
        gtk.gdk.flush()
        assert not l.is_mapped(win)
        win.show()
        gtk.gdk.flush()
        assert l.is_mapped(win)

    def test_is_override_redirect(self):
        win = self.window()
        gtk.gdk.flush()
        assert not l.is_override_redirect(win)
        win.set_override_redirect(True)
        gtk.gdk.flush()
        assert l.is_override_redirect(win)

class _EventRoutingReceiver(MockEventReceiver):
    def __init__(self, tag, store_in):
        MockEventReceiver.__init__(self)
        self.tag = tag
        self.store_in = store_in
    def do_wimpiggy_map_event(self, event):
        print("map_event in %s" % self.tag)
        self.store_in.add(("map", self.tag))
        gtk.main_quit()
    def do_wimpiggy_child_map_event(self, event):
        print("child_map_event in %s" % self.tag)
        self.store_in.add(("child-map", self.tag))
        gtk.main_quit()

class TestEventRouting(TestLowlevel):
    def test_event_routing(self):
        w1 = self.window()
        w2 = self.window()
        w2.reparent(w1, 0, 0)
        results = set()
        r1 = _EventRoutingReceiver(1, results)
        r2 = _EventRoutingReceiver(2, results)
        r3 = _EventRoutingReceiver(3, results)
        r4 = _EventRoutingReceiver(4, results)
        l.add_event_receiver(w1, r1)
        l.add_event_receiver(w1, r2)
        l.add_event_receiver(w2, r3)
        l.add_event_receiver(w2, r4)

        w1.set_events(gtk.gdk.SUBSTRUCTURE_MASK)
        w2.set_events(gtk.gdk.STRUCTURE_MASK)
        w2.show()
        while len(results) != 4:
            gtk.main()
        w2.hide()
        assert results == set([("child-map", 1), ("child-map", 2),
                                    ("map", 3), ("map", 4)])
        l.remove_event_receiver(w1, r2)
        l.remove_event_receiver(w2, r4)
        results.clear()
        w2.show()
        while len(results) != 2:
            gtk.main()
        assert results == set([("child-map", 1), ("map", 3)])

class TestUnmapWithSerial(TestLowlevel, MockEventReceiver):
    def do_wimpiggy_map_event(self, event):
        pass

    def do_wimpiggy_unmap_event(self, event):
        print("do_wimpiggy_unmap_event hi!")
        self._event = event
        gtk.main_quit()

    def test_unmap_with_serial(self):
        w = self.window()
        w.show()
        self._event = None
        l.add_event_receiver(w, self)
        serial = l.unmap_with_serial(w)
        print(serial)
        gtk.main()
        assert self._event is not None
        assert self._event.serial == serial

class TestFocusStuff(TestLowlevel, MockEventReceiver):
    def do_wimpiggy_focus_in_event(self, event):
        if event.window is self.w1:
            assert self.w1_got is None
            self.w1_got = event
        else:
            assert self.w2_got is None
            self.w2_got = event
        gtk.main_quit()
    def do_wimpiggy_focus_out_event(self, event):
        if event.window is self.w1:
            assert self.w1_lost is None
            self.w1_lost = event
        else:
            assert self.w2_lost is None
            self.w2_lost = event
        gtk.main_quit()
    def test_focus_stuff(self):
        self.w1 = self.window()
        self.w1.show()
        self.w2 = self.window()
        self.w2.show()
        gtk.gdk.flush()
        self.w1_got, self.w2_got = None, None
        self.w1_lost, self.w2_lost = None, None
        l.selectFocusChange(self.w1)
        l.selectFocusChange(self.w2)
        l.add_event_receiver(self.w1, self)
        l.add_event_receiver(self.w2, self)

        gtk.gdk.flush()
        l.XSetInputFocus(self.w1)
        gtk.gdk.flush()
        gtk.main()
        assert self.w1_got is not None
        assert self.w1_got.window is self.w1
        assert self.w1_got.mode == l.constants["NotifyNormal"]
        assert self.w1_got.detail == l.constants["NotifyNonlinear"]
        self.w1_got = None
        assert self.w2_got is None
        assert self.w1_lost is None
        assert self.w2_lost is None

        l.XSetInputFocus(self.w2)
        gtk.gdk.flush()
        gtk.main()
        gtk.main()
        assert self.w1_got is None
        assert self.w2_got is not None
        assert self.w2_got.window is self.w2
        assert self.w2_got.mode == l.constants["NotifyNormal"]
        assert self.w2_got.detail == l.constants["NotifyNonlinear"]
        self.w2_got = None
        assert self.w1_lost is not None
        assert self.w1_lost.window is self.w1
        assert self.w1_lost.mode == l.constants["NotifyNormal"]
        assert self.w1_lost.detail == l.constants["NotifyNonlinear"]
        self.w1_lost = None
        assert self.w2_lost is None

        l.XSetInputFocus(self.root())
        gtk.gdk.flush()
        gtk.main()
        assert self.w1_got is None
        assert self.w2_got is None
        assert self.w1_lost is None
        assert self.w2_lost is not None
        assert self.w2_lost.window is self.w2
        assert self.w2_lost.mode == l.constants["NotifyNormal"]
        assert self.w2_lost.detail == l.constants["NotifyAncestor"]
        self.w2_lost = None

class TestClientMessageAndXSelectInputStuff(TestLowlevel, MockEventReceiver):
    def do_wimpiggy_client_message_event(self, event):
        print("got clientmessage")
        self.evs.append(event)
        gtk.main_quit()

    def test_select_clientmessage_and_xselectinput(self):
        self.evs = []
        self.w = self.window()
        gtk.gdk.flush()

        l.add_event_receiver(self.w, self)
        l.add_event_receiver(self.root(), self)

        data = (0x01020304, 0x05060708, 0x090a0b0c, 0x0d0e0f10, 0x11121314)
        l.sendClientMessage(self.root(), False, 0, "NOMASK", *data)
        l.sendClientMessage(self.w, False, 0, "NOMASK", *data)
        gtk.main()
        # Should have gotten message to w, not to root
        assert len(self.evs) == 1
        ev = self.evs[0]
        assert ev.window is self.w
        assert ev.message_type == "NOMASK"
        assert ev.format == 32
        assert ev.data == data

        self.evs = []
        l.sendClientMessage(self.root(), False, l.constants["Button1MotionMask"],
                            "BAD", *data)
        l.addXSelectInput(self.root(), l.constants["Button1MotionMask"])
        l.sendClientMessage(self.root(), False, l.constants["Button1MotionMask"],
                            "GOOD", *data)
        gtk.main()
        assert len(self.evs) == 1
        ev = self.evs[0]
        assert ev.window is self.root()
        assert ev.message_type == "GOOD"
        assert ev.format == 32
        assert ev.data == data

    def test_send_wm_take_focus(self):
        self.evs = []
        win = self.window()
        l.add_event_receiver(win, self)
        gtk.gdk.flush()

        send_wm.send_wm_take_focus(win, 1234)
        gtk.main()
        assert len(self.evs) == 1
        event = self.evs[0]
        assert event is not None
        assert event.window is win
        assert event.message_type == "WM_PROTOCOLS"
        assert event.format == 32
        assert event.data == (l.get_xatom("WM_TAKE_FOCUS"), 1234, 0, 0, 0)

    def test_send_wm_take_focus_large_time(self):
        self.evs = []
        win = self.window()
        l.add_event_receiver(win, self)
        gtk.gdk.flush()

        send_wm.send_wm_take_focus(win, 0xff000000)
        gtk.main()
        assert len(self.evs) == 1
        event = self.evs[0]
        assert event is not None
        assert event.window is win
        assert event.message_type == "WM_PROTOCOLS"
        assert event.format == 32
        assert event.data == (l.get_xatom("WM_TAKE_FOCUS"), 0xff000000, 0, 0, 0)

# myGetSelectionOwner gets tested in test_selection.py

class TestSendConfigureNotify(TestLowlevel):
    # This test stomps on Wimpiggy's global event handler, so make sure not to
    # try receiving wimpiggy events in it.
    def test_sendConfigureNotify(self):
        # GDK discards ConfigureNotify's sent to child windows, so we can't
        # use self.window():
        w1 = gtk.gdk.Window(self.root(), width=10, height=10,
                            window_type=gtk.gdk.WINDOW_TOPLEVEL,
                            wclass=gtk.gdk.INPUT_OUTPUT,
                            event_mask=gtk.gdk.ALL_EVENTS_MASK)
        self.ev = None
        def myfilter(ev, data=None):
            print("ev %s" % (ev.type,))
            if ev.type == gtk.gdk.CONFIGURE:
                self.ev = ev
                gtk.main_quit()
            gtk.main_do_event(ev)
        gtk.gdk.event_handler_set(myfilter)

        w1.show()
        gtk.gdk.flush()
        l.sendConfigureNotify(w1)
        gtk.main()

        assert self.ev is not None
        assert self.ev.type == gtk.gdk.CONFIGURE
        assert self.ev.window == w1
        assert self.ev.send_event
        assert self.ev.x == 0
        assert self.ev.y == 0
        assert self.ev.width == 10
        assert self.ev.height == 10

        # We have to create w2 on a separate connection, because if we just
        # did w1.reparent(w2, ...), then GDK would magically convert w1 from a
        # TOPLEVEL window into a CHILD window.
        # Have to hold onto a reference to d2, so it doesn't get garbage
        # collected and kill the connection:
        d2 = self.clone_display()
        w2 = self.window(d2)
        gtk.gdk.flush()
        w2on1 = l.get_pywindow(w1, l.get_xwindow(w2))
        # Doesn't generate an event, because event mask is zeroed out.
        w2.move(11, 12)
        # Reparenting doesn't trigger a ConfigureNotify.
        w1.reparent(w2on1, 13, 14)
        # To double-check that it's still a TOPLEVEL:
        print(w1.get_window_type())
        w1.resize(15, 16)
        gtk.main()

        # w1 in root coordinates is now at (24, 26)
        self.ev = None
        l.sendConfigureNotify(w1)
        gtk.main()

        assert self.ev is not None
        assert self.ev.type == gtk.gdk.CONFIGURE
        assert self.ev.window == w1
        assert self.ev.send_event
        assert self.ev.x == 24
        assert self.ev.y == 26
        assert self.ev.width == 15
        assert self.ev.height == 16

class TestSubstructureRedirect(TestLowlevel, MockEventReceiver):
    def do_child_map_request_event(self, event):
        print("do_child_map_request_event")
        self.map_ev = event
        gtk.main_quit()
    def do_child_configure_request_event(self, event):
        print("do_child_configure_request_event")
        self.conf_ev = event
        gtk.main_quit()

    def test_substructure_redirect(self):
        self.map_ev = None
        self.conf_ev = None
        root = self.root()
        d2 = self.clone_display()
        w2 = self.window(d2)
        gtk.gdk.flush()
        w1 = l.get_pywindow(self.display, l.get_xwindow(w2))

        l.add_event_receiver(root, self)
        l.substructureRedirect(root)
        gtk.gdk.flush()

        # gdk_window_show does both a map and a configure (to raise the
        # window)
        print("showing w2")
        w2.show()
        # Can't just call gtk.main() twice, the two events may be delivered
        # together and processed in a single mainloop iteration.
        while None in (self.map_ev, self.conf_ev):
            gtk.main()
        assert self.map_ev.delivered_to is root
        assert self.map_ev.window is w1

        assert self.conf_ev.delivered_to is root
        assert self.conf_ev.window is w1
        for field in ("x", "y", "width", "height",
                      "border_width", "above", "detail", "value_mask"):
            print(field)
            assert hasattr(self.conf_ev, field)

        self.map_ev = None
        self.conf_ev = None

        w2.move_resize(1, 2, 3, 4)
        gtk.main()
        assert self.map_ev is None
        assert self.conf_ev is not None
        assert self.conf_ev.delivered_to is root
        assert self.conf_ev.window is w1
        assert self.conf_ev.x == 1
        assert self.conf_ev.y == 2
        assert self.conf_ev.width == 3
        assert self.conf_ev.height == 4
        assert self.conf_ev.value_mask == (l.constants["CWX"]
                                           | l.constants["CWY"]
                                           | l.constants["CWWidth"]
                                           | l.constants["CWHeight"])

        self.map_ev = None
        self.conf_ev = None
        w2.move(5, 6)
        gtk.main()
        assert self.map_ev is None
        assert self.conf_ev.x == 5
        assert self.conf_ev.y == 6
        assert self.conf_ev.value_mask == (l.constants["CWX"] | l.constants["CWY"])

        self.map_ev = None
        self.conf_ev = None
        w2.raise_()
        gtk.main()
        assert self.map_ev is None
        assert self.conf_ev.detail == l.constants["Above"]
        assert self.conf_ev.value_mask == l.constants["CWStackMode"]

    def test_configureAndNotify(self):
        self.conf_ev = None
        l.substructureRedirect(self.root())
        l.add_event_receiver(self.root(), self)
        # Need to hold onto a handle to this, so connection doesn't get
        # dropped:
        client = self.clone_display()
        w1_client = self.window(client)
        gtk.gdk.flush()
        w1_wm = l.get_pywindow(self.display, l.get_xwindow(w1_client))

        l.configureAndNotify(w1_client, 11, 12, 13, 14)
        gtk.main()

        assert self.conf_ev is not None
        assert self.conf_ev.delivered_to is self.root()
        assert self.conf_ev.window is w1_wm
        assert self.conf_ev.x == 11
        assert self.conf_ev.y == 12
        assert self.conf_ev.width == 13
        assert self.conf_ev.height == 14
        assert self.conf_ev.border_width == 0
        assert self.conf_ev.value_mask == (l.constants["CWX"]
                                           | l.constants["CWY"]
                                           | l.constants["CWWidth"]
                                           | l.constants["CWHeight"]
                                           | l.constants["CWBorderWidth"])

        partial_mask = l.constants["CWWidth"] | l.constants["CWStackMode"]
        l.configureAndNotify(w1_client, 11, 12, 13, 14, partial_mask)
        gtk.main()

        assert self.conf_ev is not None
        assert self.conf_ev.delivered_to is self.root()
        assert self.conf_ev.window is w1_wm
        assert self.conf_ev.width == 13
        assert self.conf_ev.border_width == 0
        assert self.conf_ev.value_mask == (l.constants["CWWidth"]
                                           | l.constants["CWBorderWidth"])



class TestGeometryConstraints(object):
    # This doesn't actually need a session to play with...
    def test_calc_constrained_size(self):
        class Foo:
            def __repr__(self):
                return repr(self.__dict__)
        def hints(**args):
            f = Foo()
            for k in ("max_size", "min_size", "base_size", "resize_inc",
                      "min_aspect", "max_aspect"):
                setattr(f, k, None)
            for k, v in args.iteritems():
                setattr(f, k, v)
            return f
        def t(w, h, hints, exp_w, exp_h, exp_vw, exp_vh):
            got = l.calc_constrained_size(w, h, hints)
            print(repr(hints))
            assert got == (exp_w, exp_h, exp_vw, exp_vh)
        t(150, 100, None, 150, 100, 150, 100)
        t(150, 100, hints(), 150, 100, 150, 100)
        t(150, 100, hints(max_size=(90, 150)), 90, 100, 90, 100)
        t(150, 100, hints(max_size=(200, 90)), 150, 90, 150, 90)
        t(150, 100, hints(min_size=(90, 150)), 150, 150, 150, 150)
        t(150, 100, hints(min_size=(200, 90)), 200, 100, 200, 100)
        t(150, 100, hints(min_size=(182, 17), max_size=(182, 17)),
          182, 17, 182, 17)

        t(150, 100, hints(base_size=(3, 4), resize_inc=(10, 10)),
          143, 94, 14, 9)
        try:
            t(150, 100, hints(base_size=(3, 4), resize_inc=(10, 10),
                              max_size=(100, 150), min_size=(0, 140)),
              93, 144, 9, 14)
        except AssertionError:
            print("Assertion Failed!  But *cough* *cough* actually gdk "
                   + "(and apparently every wm ever) has a bug here. "
                   + "and it's trivial and I'm ignoring it for now. "
                   + "(see http://bugzilla.gnome.org/show_bug.cgi?id=492961)")
        else:
            raise AssertionError("Dude look at this, gtk+ fixed bug#492961")
        # FIXME: this is wrong (see above), but it is what it actually
        # returns, and is not so bad as all that:
        t(150, 100, hints(base_size=(3, 4), resize_inc=(10, 10),
                          max_size=(100, 150), min_size=(0, 140)),
          93, 134, 9, 13)

        # Behavior in this case is basically undefined, so *shrug*:
        t(150, 100, hints(base_size=(3, 4), resize_inc=(10, 10),
                          max_size=(100, 100), min_size=(100, 100)),
          93, 94, 9, 9)

        t(150, 100, hints(min_aspect=1, max_aspect=1), 100, 100, 100, 100)
        t(100, 150, hints(min_aspect=1, max_aspect=1), 100, 100, 100, 100)

        t(100, 150, hints(min_aspect=1, max_aspect=1,
                          base_size=(3, 3), resize_inc=(10, 10)),
          93, 93, 9, 9)

        # Also undefined, but (93, 94) is good enough:
        t(100, 150, hints(min_aspect=1, max_aspect=1,
                          base_size=(3, 4), resize_inc=(10, 10)),
          93, 94, 9, 9)


class TestRegion(object):
    def test_get_rectangle_from_region(self):
        print(1)
        region = gtk.gdk.Region()
        assert_raises(ValueError, l.get_rectangle_from_region, region)
        print(2)
        rect1 = gtk.gdk.Rectangle(1, 2, 3, 4)
        region = gtk.gdk.region_rectangle(rect1)
        (x, y, w, h) = l.get_rectangle_from_region(region)
        assert (x, y, w, h) == (1, 2, 3, 4)
        print(3)
        region.union_with_rect(gtk.gdk.Rectangle(10, 11, 12, 13))
        (x, y, w, h) = l.get_rectangle_from_region(region)
        assert (x, y, w, h) in [(1, 2, 3, 4), (10, 11, 12, 13)]
        print(4)
        region.subtract(gtk.gdk.region_rectangle(rect1))
        (x, y, w, h) = l.get_rectangle_from_region(region)
        assert (x, y, w, h) == (10, 11, 12, 13)
        print(5)

class TestImageOptimizations(object):
    def test_premultiply_argb_in_place(self):
        import array
        ar = array.array("I", [0x80ffffff, 0x306090b0])
        l.premultiply_argb_in_place(ar)
        # Got each byte by calculating e.g.:
        #   hex(int(0xb0 * (0x30 / 255.))) == 0x21
        assert ar[0] == 0x80808080
        assert ar[1] == 0x30121b21
