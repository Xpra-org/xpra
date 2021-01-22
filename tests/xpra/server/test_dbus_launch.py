#!/usr/bin/env python

import os
import sys


def main():
    from xpra.scripts.server import start_dbus
    dbus_pid, dbus_env = start_dbus("dbus-launch --sh-syntax --close-stderr")
    print("dbus_pid=%s" % (dbus_pid))
    print("dbus_env=%s" % (dbus_env))
    os.environ.update(dbus_env)
    from xpra.dbus.notifications_forwarder import main as nf_main
    nf_main()


if __name__ == '__main__':
    sys.exit(main())
