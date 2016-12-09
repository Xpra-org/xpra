#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.rencode import dumps as rencode_dumps  #@UnresolvedImport
from xpra.net.rencode import loads as rencode_loads  #@UnresolvedImport
#from xpra.net.rencode import __version__

def compare_dict(d1, d2):
    errs = []
    for k in d1.keys():
        if k not in d2:
            errs.append("key %s missing from reloaded dict!" % str(k))
            continue
        v = d1.get(k)
        lv = d2.get(k)
        if v!=lv:
            if type(v) in (list, tuple):
                v = list(v)
                lv = list(lv)
                if v==lv:
                    continue
            if type(v)==dict:
                errs += compare_dict(v, lv)
                continue
            errs.append("value for key %s differs, expected %s but got %s" % (k, v, lv))
    return errs

def test_hello():
    data = {'pycrypto.version': '2.6', 'bell': True, 'cursor.default_size': 66L, 'platform.release': '3.11.3-201.fc19.x86_64', 'lz4': False, 'encoding.vpx.version': 6, 'sound.receive': True, 'digest': ('hmac', 'xor'), 'aliases': {'suspend': 13, 'encoding': 14, 'desktop_size': 15, 'damage-sequence': 10, 'focus': 16, 'unmap-window': 17, 'connection-lost': 21, 'jpeg-quality': 19, 'min-speed': 20, 'ping_echo': 8, 'keymap-changed': 18, 'shutdown-server': 22, 'speed': 23, 'close-window': 24, 'server-settings': 25, 'set-clipboard-enabled': 7, 'quality': 27, 'ping': 9, 'set-cursors': 11, 'resize-window': 28, 'set_deflate': 29, 'key-repeat': 30, 'layout-changed': 31, 'set-keyboard-sync-enabled': 12, 'sound-control': 32, 'screenshot': 33, 'resume': 34, 'sound-data': 35, 'pointer-position': 36, 'disconnect': 26, 'button-action': 37, 'map-window': 38, 'buffer-refresh': 39, 'info-request': 40, 'set-notify': 5, 'configure-window': 41, 'set-bell': 6, 'min-quality': 42, 'gibberish': 43, 'hello': 44, 'key-action': 45, 'move-window': 46}, 'encodings.with_quality': ['jpeg'], 'change-quality': True, 'window_unmap': True, 'encodings.core': ['rgb24', 'rgb32', 'png', 'png/L', 'png/P', 'jpeg', 'vpx'], 'actual_desktop_size': (2560, 1600), 'encoding': 'png', 'root_window_size': (2560, 1600), 'encoding.PIL.version': '1.1.7', 'platform': 'linux2', 'gid': 1000, 'resize_screen': True, 'chunked_compression': True, 'sound.pygst.version': (0, 10, 22), 'sound.send': True, 'encoding.x264.version': 130L, 'encodings.with_speed': ['png', 'png/L', 'png/P', 'jpeg'], 'auto_refresh_delay': 250, 'client_window_properties': True, 'start_time': 1381225490, 'build.cpu': 'x86_64', 'notifications': False, 'server_type': 'base', 'platform.machine': 'x86_64', 'build.on': 'desktop', 'MARKER': '***********************************************************************************', 'rencode': True, 'window_configure': True, 'gtk.version': (2, 24, 19), 'window.raise': True, 'encodings.lossless': ['rgb24', 'rgb32', 'png', 'png/L', 'png/P', 'webp'], 'platform.name': 'Linux', 'build.revision': '4193', 'modifier_keycodes': {'control': [('Control_L', 'Control_L'), ('Control_R', 'Control_R')], 'mod1': [(64, 'Alt_L'), ('Alt_L', 'Alt_L'), ('Meta_L', 'Meta_L')], 'mod2': [('Num_Lock', 'Num_Lock')], 'mod3': [], 'mod4': [(133, 'Super_L'), ('Super_R', 'Super_R'), ('Super_L', 'Super_L'), ('Hyper_L', 'Hyper_L')], 'mod5': [(92, 'ISO_Level3_Shift'), ('Multi_key', 'ISO_Level3_Shift'), ('Mode_switch', 'Mode_switch')], 'shift': [('Shift_L', 'Shift_L'), ('Shift_R', 'Shift_R')], 'lock': [('Caps_Lock', 'Caps_Lock')]}, 'sound.pulseaudio.server': '', 'build.by': 'root', 'display': ':10', 'python.version': (2, 7, 5), 'uid': 1000, 'desktop_size': (2560, 1600), 'pid': 21794, 'sound_sequence': True, 'change-speed': True, 'sound.pulseaudio.id': '', 'cursors': True, 'encodings': ['png/L', 'vpx', 'jpeg', 'webp', 'rgb', 'png/P', 'png'], 'sound.decoders': ['mp3', 'wavpack', 'wav', 'flac', 'speex'], 'rencode.version': '1.0.2', 'current_time': 1381225493, 'hostname': 'desktop', 'encodings.with_lossless_mode': ['webp'], 'key_repeat': [500, 30], 'elapsed_time': 3, 'version': '0.11.0', 'build.bit': '64bit', 'suspend-resume': True, 'platform.linux_distribution': ('Fedora', '19', 'Schr\xc3\xb6dinger\xe2\x80\x99s Cat'), 'max_desktop_size': (5120, 3200), 'sound.encoders': ['mp3', 'wavpack', 'wav', 'flac', 'speex'], 'clipboard': True, 'encoding.avcodec.version': 'Lavc54.92.100', 'platform.platform': 'Linux-3.11.3-201.fc19.x86_64-x86_64-with-fedora-19-Schr\xc3\xb6dinger\xe2\x80\x99s_Cat', 'notify-startup-complete': True, 'toggle_keyboard_sync': True, 'xsettings-tuple': True, 'change-min-speed': True, 'clipboards': ['CLIPBOARD', 'PRIMARY', 'SECONDARY'], 'pygtk.version': (2, 24, 0), 'change-min-quality': True, 'byteorder': 'little', 'build.date': '2013-10-08', 'python.full_version': '2.7.5 (default, Aug 22 2013, 09:31:58) \n[GCC 4.8.1 20130603 (Red Hat 4.8.1-1)]', 'toggle_cursors_bell_notify': True, 'encoding.opencl.version': '2013.1', 'encoding.webp.version': '0.2.2', 'key_repeat_modifiers': True, 'raw_packets': True, 'build.local_modifications': '1', 'platform.processor': 'x86_64', 'sound.gst.version': (0, 10, 36), 'encoding.swscale.version': 'SwS2.2.100', 'mmap_enabled': False}
    s = rencode_dumps(data)
    #import binascii
    #print("rencode(%s)=%s" % (data, binascii.hexlify(s)))
    l = rencode_loads(s)
    #print("rdecode(%s)=%s" % (binascii.hexlify(s), l))
    #print("original has %s keys, reloaded has %s keys" % (len(data), len(l)))
    errs = compare_dict(data, l)
    return len(errs)==0

def test_invalid():
    try:
        rencode_dumps([set([1, 2]), "somethingelse"])
        return False
    except:
        return True

def main():
    assert test_hello()
    assert test_invalid()
    print("OK")

if __name__ == "__main__":
    main()
