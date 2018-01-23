#!/usr/bin/env python

import sys

nid = 1

def notify(*_args):
    global nid
    from xpra.notifications.dbus_notifier import DBUS_Notifier, log
    log.enable_debug()
    notifier = DBUS_Notifier()
    notifier.app_name_format = "%s"
    #ensure we can send the image-path hint:
    notifier.parse_hints = notifier.noparse_hints
    actions = ["0", "Hello", "1", "Goodbye"]
    hints = {
        "image-path"    : "/usr/share/xpra/icons/encoding.png",
        }
    notifier.show_notify("dbus-id", None, nid, "xpra test app", 0, "", "Notification %i Summary" % nid, "Notification %i Body" % nid, actions, hints, 60*1000, "")
    nid += 1
    return True


def main():
    name = "test"
    if len(sys.argv)>=2:
        name = sys.argv[1]
    from xpra.platform import program_context
    with program_context(name, name):
        notify()
        from xpra.gtk_common.gobject_compat import import_glib
        glib = import_glib()
        glib.timeout_add(60*1000, notify)
        loop = glib.MainLoop()
        loop.run()


if __name__ == "__main__":
    main()
