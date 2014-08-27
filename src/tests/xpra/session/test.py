# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import subprocess
import sys
import os
import traceback
import atexit
import errno
import gobject
import gtk.gdk
from xpra.gtk_common.gobject_util import one_arg_signal

# Skip contents of this file when looking for tests
__test__ = False

def assert_raises(exc_class, f, *args, **kwargs):
    # exc_class can be a tuple.
    try:
        value = f(*args, **kwargs)
    except exc_class:
        pass
    except:
        (cls, e, _) = sys.exc_info()
        raise AssertionError(("unexpected exception: %s: %s\n"
                               + "Original traceback:\n%s")
                               % (cls, e, traceback.format_exc()))
    else:
        raise AssertionError("wanted exception, got normal return (%r)" % (value,))


def assert_emits(f, obj, signal, slot=None):
    """Call f(obj), and assert that 'signal' is emitted.  Optionally, also
    passes signaled data to 'slot', which may make its own assertions."""
    backchannel = {
        "signal_was_emitted": False,
        "slot_exc": None,
        }
    def real_slot(*args, **kwargs):
        backchannel["signal_was_emitted"] = True
        if slot is not None:
            try:
                slot(*args, **kwargs)
            except:
                backchannel["slot_exc"] = sys.exc_info()
    connection = obj.connect(signal, real_slot)
    try:
        f(obj)
    finally:
        obj.disconnect(connection)
    assert backchannel["signal_was_emitted"]
    if backchannel["slot_exc"] is not None:
        exc = backchannel["slot_exc"]
        raise exc[0](exc[1:])

def assert_mainloop_emits(obj, signal, slot=None):
    """Runs the mainloop and asserts that 'signal' is emitted.  Optionally,
    also passes signaled data to 'slot', which may make its own assertions."""
    def real_slot(*args, **kwargs):
        gtk.main_quit()
        if slot is not None:
            slot(*args, **kwargs)
    assert_emits(lambda x: gtk.main(), obj, signal, real_slot)

class Session(object):
    def __init__(self, display_name):
        self._my_process = os.getpid()
        self.display_name = display_name
        self._x11 = None
        self._dbus = None
        self._dbus_address = None

    def _alive(self, pid):
        # Just in case it's a zombie, reap it; otherwise, do nothing.
        try:
            os.waitpid(pid, os.WNOHANG)
        except OSError as e:
            pass
        # Then use the old SIG 0 trick.
        try:
            os.kill(pid, 0)
        except OSError as e:
            if e.errno == errno.ESRCH:
                return False
        return True

    def _x_really_running(self):
        try:
            d = gtk.gdk.Display(self.display_name)
            d.close()
        except RuntimeError:
            return False
        return True

    def validate(self):
        assert os.getpid() == self._my_process
        # FIXME: add some sort of check in here that X has actually reset
        # since the last time -- e.g., set a prop on the root window and make
        # sure it isn't here anymore.  This is to make sure that other
        # connections got properly disconnected, etc.
        if (self._x11 is None
            or self._dbus is None
            or not self._alive(self._x11.pid)
            or not self._alive(self._dbus.pid)
            or not self._x_really_running()):
            self.destroy()
            self._x11 = subprocess.Popen(["Xvfb-for-xpra", self.display_name,
                                          "-ac",
                                          #"-audit", "10",
                                          "+extension", "Composite",
                                          # Need to set the depth like this to
                                          # get non-paletted visuals:
                                          "-screen", "0", "1024x768x24+32"],
                                         executable="Xvfb",
                                         stderr=open("/dev/null", "w"))
            self._dbus = subprocess.Popen(["dbus-daemon-for-xpra", "--session",
                                           "--nofork", "--print-address"],
                                          executable="dbus-daemon",
                                          stdout=subprocess.PIPE)
            self._dbus_address = self._dbus.stdout.readline().strip()

    def destroy(self):
        if os.getpid() != self._my_process:
            return
        if self._x11 is not None:
            try:
                os.kill(self._x11.pid, 15)
                self._x11.wait()
            except OSError:
                pass
            self._x11 = None
        if self._dbus is not None:
            try:
                os.kill(self._dbus.pid, 15)
                self._dbus.wait()
            except OSError:
                pass
            self._dbus = None
            self._dbus_address = None

_the_session = None

class TestWithSession(object):
    "A test that runs with its own isolated X11 and D-Bus session."
    display_name = ":13"
    display = None

    @classmethod
    def preForkClassSetUp(cls):
        global _the_session
        if _the_session is None:
            _the_session = Session(cls.display_name)
            atexit.register(_the_session.destroy)
        _the_session.validate()

    def setUp(self):
        # This is not a race condition, nor do we need to sleep here, because
        # gtk.gdk.Display.__init__ is smart enough to silently block until the
        # X server comes up.  By using 127.0.0.1 explicitly we can force it to
        # use TCP over loopback and that means wireshark can work.
        self.display = gtk.gdk.Display("127.0.0.1" + self.display_name)
        default_display = gtk.gdk.display_manager_get().get_default_display()
        if default_display is not None:
            default_display.close()
        # This line is critical, because many gtk functions (even
        # _for_display/_for_screen functions) actually use the default
        # display, even if only temporarily.  For instance,
        # gtk_clipboard_for_display creates a GtkInvisible, which
        # unconditionally sets its colormap (using the default display) before
        # gtk_clipboard_for_display gets a chance to switch it to the proper
        # display.  So the end result is that we always need a valid default
        # display of some sort:
        gtk.gdk.display_manager_get().set_default_display(self.display)
        print("Opened new display %r" % (self.display,))

        os.environ["DBUS_SESSION_BUS_ADDRESS"] = _the_session._dbus_address

    def tearDown(self):
        # Could do cleanup here (close X11 connections, unset
        # os.environ["DBUS_SESSION_BUS_ADDRESS"], etc.), but our test runner
        # runs us in a forked off process that will exit immediately after
        # this, so who cares?
        pass

    def clone_display(self):
        clone = gtk.gdk.Display(self.display.get_name())
        print("Cloned new display %r" % (clone,))
        return clone


class MockEventReceiver(gobject.GObject):
    __gsignals__ = {
        "child-map-request-event": one_arg_signal,
        "child-configure-request-event": one_arg_signal,
        "xpra-focus-in-event": one_arg_signal,
        "xpra-focus-out-event": one_arg_signal,
        "xpra-client-message-event": one_arg_signal,
        "xpra-map-event": one_arg_signal,
        "xpra-unmap-event": one_arg_signal,
        "xpra-child-map-event": one_arg_signal,
        }
    def do_child_map_request_event(self, event):
        print("do_child_map_request_event")
        assert False
    def do_child_configure_request_event(self, event):
        print("do_child_configure_request_event")
        assert False
    def do_xpra_focus_in_event(self, event):
        print("do_xpra_focus_in_event")
        assert False
    def do_xpra_focus_out_event(self, event):
        print("do_xpra_focus_out_event")
        assert False
    def do_xpra_client_message_event(self, event):
        print("do_xpra_client_message_event")
        assert False
    def do_xpra_map_event(self, event):
        print("do_xpra_map_event")
        assert False
    def do_xpra_child_map_event(self, event):
        print("do_xpra_child_map_event")
        assert False
    def do_xpra_unmap_event(self, event):
        print("do_xpra_unmap_event")
gobject.type_register(MockEventReceiver)

