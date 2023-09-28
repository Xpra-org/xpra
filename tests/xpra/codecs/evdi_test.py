#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def main():
    from xpra.codecs.evdi.load import load_evdi_module
    load_evdi_module()
    from xpra.codecs.drm.drm import query  # @UnresolvedImport
    info = query()
    from xpra.util.str_fn import print_nested_dict
    print_nested_dict(info)
    from xpra.codecs.evdi.capture import find_evdi_devices, test_device  # @UnresolvedImport
    #from xpra.gtk.gobject_compat import register_os_signals
    #import sys
    #def handler(*args):
    #    sys.exit(0)
    #register_os_signals(handler, "evdi test")
    devices = find_evdi_devices()
    print(f"devices={devices}")
    if devices:
        for device in devices:
            test_device(device)
            break


if __name__ == '__main__':
    main()
