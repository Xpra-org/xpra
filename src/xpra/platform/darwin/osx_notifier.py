#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from Foundation import NSUserNotification, NSUserNotificationCenter, NSUserNotificationDefaultSoundName #@UnresolvedImport


notification_center = None


def show_notify(nid, summary, body):
    notification = NSUserNotification.alloc().init()
    notification.setTitle_(summary)
    notification.setInformativeText_(body)
    notification.setIdentifier_("%s" % nid)
    #enable sound:
    notification.setSoundName_(NSUserNotificationDefaultSoundName)
    notification_center.deliverNotification_(notification)


def main():
    if len(sys.argv)<4:
        print("Error: not enough arguments")
        return 1
    global notification_center
    notification_center = NSUserNotificationCenter.defaultUserNotificationCenter()
    if not notification_center:
        print("Error: cannot access notification center")
        return 2
    nid = sys.argv[1]
    summary = sys.argv[2]
    body = sys.argv[3]
    show_notify(nid, summary, body)
    return 0


if __name__ == "__main__":
    v = main()
    sys.exit(v)
