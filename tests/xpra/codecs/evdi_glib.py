#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def main():
    from gi.repository import GLib  # @UnresolvedImport

    from xpra.log import Logger
    log = Logger("evdi")

    from xpra.codecs.evdi.capture import find_evdi_devices, EvdiDevice  # @UnresolvedImport
    devices = find_evdi_devices()
    assert devices

    evdi_device = None

    def evdi_setup():
        #import time
        #time.sleep(2)
        log.warn("evdi_setup()")
        dev = EvdiDevice(devices[0])
        log.warn(f"evdi_setup() evdi_device={dev}")
        dev.open()
        dev.connect()
        dev.enable_cursor_events()
        log.warn("evdi_setup() done")
        return dev

    def io_event(channel, condition):
        log.warn(f"io_event({channel}, {condition})")
        evdi_device.handle_events()
        evdi_device.refresh()
        return True

    def refresh():
        dev = evdi_device
        log.warn(f"refresh() device={dev}")
        if dev:
            dev.refresh()
        return True

    def start():
        #self.evdi_device.handle_all_events()
        fd_source = evdi_device.get_event_fd()
        channel = GLib.IOChannel.unix_new(fd_source)
        channel.set_encoding(None)
        channel.set_buffered(False)
        GLib.io_add_watch(channel, GLib.PRIORITY_LOW, GLib.IO_IN, io_event)
        GLib.timeout_add(50, refresh)
        return False
    evdi_device = evdi_setup()
    # GLib.timeout_add(2*1000, refresh)
    GLib.timeout_add(1*1000, start)
    log("run()")
    GLib.MainLoop().run()


if __name__ == '__main__':
    main()
