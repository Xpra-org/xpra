#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time

from rencode import dumps as rencode_dumps, __version__ as rencode_version  #@UnresolvedImport
from xpra.net.bencode import bencode, __version__ as bencode_version

ENCODER_NAME = {
                bencode             : "bencode",
                rencode_dumps       : "rencode",
                }
ENCODER_VERSION = {
                   bencode          : bencode_version,
                   rencode_dumps    : rencode_version,
                   }
#packets normally contain the packet type as an alias
#so we duplicate this here:
ALIASES = {
           12   : "new_window",
           10   : "damage-sequence",
           47   : "key-action",
           37   : "pointer-position",
           29   : "hello",
           18   : "damage",
           3    : "ping",
           5    : "ping-echo",
           }


TIMES = {}
def reset_stats():
    global TIMES
    TIMES = {}

def print_stats():
    #print("totals: %s" % TIMES)
    #print("average gain of rencode over bencode: %.1f times faster" % (bencode_time/rencode_time))
    pass

def test_packet(packet):
    for encoder in (bencode, rencode_dumps):
        test_encode(packet, encoder)

def test_encode(packet, encoder, N = 10000):
    start = time.time()
    for _ in range(N):
        encoder(packet)
    end = time.time()
    delta = end-start
    try:
        packet_info = "%s " % ALIASES.get(packet[0], packet[0])
    except:
        packet_info = str(packet)[:20]+".."
    print("encoded %s %i times with %s in %ims" % (packet_info, N, ENCODER_NAME.get(encoder, encoder), 1000*delta))
    v = TIMES.get(encoder)
    if v is None:
        v = delta
    else:
        v += delta
    TIMES[encoder] = v

def test_packets():
    reset_stats()
    hello = (29, {'pycrypto.version': '2.6.1', 'bell': True, 'cursor.default_size': 66L,
                   'platform.release': '3.11.10-200.fc19.x86_64', 'lz4': True,
                   'encoding.vpx.version': 'v1.2.0', 'sound.receive': True, 'digest': ('hmac', 'xor'),
                   'aliases': {'suspend': 13, 'encoding': 14, 'desktop_size': 15, 'damage-sequence': 10, 'focus': 16, 'unmap-window': 17, 'connection-lost': 21, 'jpeg-quality': 19, 'min-speed': 20, 'ping_echo': 8, 'keymap-changed': 18, 'shutdown-server': 22, 'quality': 23, 'close-window': 24, 'exit-server': 25, 'server-settings': 26, 'set-clipboard-enabled': 7, 'speed': 28, 'ping': 9, 'set-cursors': 11, 'resize-window': 29, 'set_deflate': 30, 'key-repeat': 31, 'layout-changed': 32, 'set-keyboard-sync-enabled': 12, 'sound-control': 33, 'screenshot': 34, 'resume': 35, 'sound-data': 36, 'pointer-position': 37, 'disconnect': 27, 'button-action': 38, 'map-window': 39, 'buffer-refresh': 40, 'info-request': 41, 'set-notify': 5, 'rpc': 42, 'configure-window': 43, 'set-bell': 6, 'min-quality': 44, 'gibberish': 45, 'hello': 46, 'key-action': 47, 'move-window': 48},
                   'platform.platform': 'Linux-3.11.10-200.fc19.x86_64-x86_64-with-fedora-19-Schr\xc3\xb6dinger\xe2\x80\x99s_Cat',
                   'change-quality': True, 'window_unmap': True,
                   'uuid': '8643124ce701ee68dbb6b7a8c4eb13a5f6409494',
                   'encoding.opencl.version': '2013.1', 'actual_desktop_size': (3840, 1080),
                   'encoding': 'rgb', 'change-min-speed': True, 'encoding.PIL.version': '1.1.7',
                   'platform': 'linux2', 'sound.server_driven': True, 'gid': 1000, 'resize_screen': True,
                   'chunked_compression': True, 'sound.pygst.version': (0, 10, 22), 'sound.send': True,
                   'encoding.x264.version': 130L, 'encodings.with_speed': ['h264', 'png', 'png/L', 'png/P', 'jpeg'],
                   'auto_refresh_delay': 250, 'client_window_properties': True, 'start_time': 1386771470,
                   'build.cpu': 'x86_64', 'pycrypto.fastmath': True, 'platform.machine': 'x86_64',
                   'build.on': 'desktop', 'rencode': True, 'root_window_size': (3840, 1080),
                   'window_configure': True, 'gtk.version': (2, 24, 22), 'window.raise': True,
                   'info-request': True, 'platform.name': 'Linux', 'zlib': True, 'build.revision': '4679',
                   'encodings.lossless': ['rgb24', 'rgb32', 'png', 'png/L', 'png/P'],
                   'modifier_keycodes': {'control': [('Control_L', 'Control_L'), ('Control_R', 'Control_R')],
                                         'mod1': [(64, 'Alt_L'), ('Alt_L', 'Alt_L'), ('Meta_L', 'Meta_L')],
                                         'mod2': [('Num_Lock', 'Num_Lock')], 'mod3': [],
                                         'mod4': [(133, 'Super_L'), ('Super_R', 'Super_R'), ('Super_L', 'Super_L'), ('Hyper_L', 'Hyper_L')],
                                         'mod5': [(92, 'ISO_Level3_Shift'), ('Multi_key', 'ISO_Level3_Shift'), ('Mode_switch', 'Mode_switch')],
                                         'shift': [('Shift_L', 'Shift_L'), ('Shift_R', 'Shift_R')],
                                         'lock': [('Caps_Lock', 'Caps_Lock')]},
                   'sound.pulseaudio.server': '', 'build.by': 'root',
                   'machine_id': '7725dfc225d14958a625ddaaaea5962b', 'display': ':10',
                   'python.version': (2, 7, 5), 'uid': 1000, 'desktop_size': (3840, 1080),
                   'encodings.with_quality': ['h264', 'jpeg'], 'pid': 11810, 'sound_sequence': True,
                   'change-speed': True, 'sound.pulseaudio.id': '', 'cursors': True,
                   'encodings': ['rgb', 'vp8', 'h264', 'png', 'png/L', 'png/P', 'jpeg'],
                   'sound.decoders': ['mp3', 'wavpack', 'wav', 'flac', 'speex'],
                   'rencode.version': '1.0.2', 'current_time': 1386771473, 'hostname': 'desktop',
                   'encodings.with_lossless_mode': [], 'key_repeat': [500, 30], 'elapsed_time': 2,
                   'encoding.generic': True, 'version': '0.11.0', 'build.bit': '64bit', 'suspend-resume': True,
                   'platform.linux_distribution': ('Fedora', '19', 'Schr\xc3\xb6dinger\xe2\x80\x99s Cat'),
                   'max_desktop_size': (5120, 3200), 'sound.encoders': ['mp3', 'wavpack', 'wav', 'flac', 'speex'],
                   'clipboard': True, 'encoding.avcodec.version': 'Lavc54.92.100', 'server_type': 'base',
                   'notify-startup-complete': True, 'bencode': True, 'toggle_keyboard_sync': True,
                   'xsettings-tuple': True, 'clipboards': ['CLIPBOARD', 'PRIMARY', 'SECONDARY'],
                   'pygtk.version': (2, 24, 0), 'change-min-quality': True, 'byteorder': 'little',
                   'build.date': '2013-12-11',
                   'python.full_version': '2.7.5 (default, Nov 12 2013, 16:18:42) \n[GCC 4.8.2 20131017 (Red Hat 4.8.2-1)]',
                   'dbus_proxy': True, 'exit_server': True, 'toggle_cursors_bell_notify': True, 'notifications': False,
                   'encodings.core': ['rgb24', 'rgb32', 'vp8', 'h264', 'png', 'png/L', 'png/P', 'jpeg'],
                   'key_repeat_modifiers': True, 'raw_packets': True,
                   'build.local_modifications': '5', 'platform.processor': 'x86_64', 'sound.gst.version': (0, 10, 36),
                   'encoding.swscale.version': 'SwS2.2.100', 'mmap_enabled': False})
    test_packet(hello)
    #test with some of the most common packets:
    damage = [18, 1, 0, 0, 499, 316, 'rgb24', '', 1, 1497, {'lz4': True, 'rgb_format': 'RGB'}]
    test_packet(damage)
    ping = [3, 1386771573608]
    test_packet(ping)
    damage_sequence = [10, 17, 1, 12, 13, 333]
    test_packet(damage_sequence)
    ping_echo = [5, 1386771673124L, 830, 880, 890, 4]
    test_packet(ping_echo)
    pointer_position = [37, 1, (204, 279), ['mod2'], []]
    test_packet(pointer_position)
    key_action = [47, 1, 's', True, ['mod2'], 115, 's', 39, 0]
    test_packet(key_action)
    new_window = [12, 2, 0, 0, 499, 316,
                    {'size-constraints': {'minimum-size': (25, 17), 'base-size': (19, 4), 'increment': (6, 13)}, 'fullscreen': False, 'has-alpha': False, 'xid': '0xc00022', 'title': 'xterm', 'pid': 13773, 'client-machine': 'desktop', 'icon-title': 'xterm', 'window-type': ['NORMAL'], 'modal': False, 'maximized': False, 'class-instance': ['xterm', 'XTerm']}, {}]
    test_packet(new_window)

    print("summary of packet tests:")
    print_stats()
    print("")

def test_image():
    #this code is from here:
    #http://www.tortall.net/mu/wiki/CairoTutorial/diagram.py?raw
    #we use it to generate some non-random pixels
    import cairo
    w = 1280
    h = 768
    alpha = [1, 0.15, 0.15]
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    cr.scale(w, h)
    cr.set_line_width(0.01)
    cr.save()
    cr.transform(cairo.Matrix(0.6, 0, 1.0/3, 0.5, 0.02, 0.45))
    cr.push_group()
    cr.rectangle(0, 0, 1, 1); cr.clip()
    def draw_dest():
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, 1, 1)
        cr.fill()
    draw_dest()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width( max(cr.device_to_user_distance(2, 2)) )
    cr.rectangle(0, 0, 1, 1)
    cr.stroke()
    cr.pop_group_to_source()
    cr.paint_with_alpha(alpha[0])
    cr.restore()

    cr.save()
    cr.transform(cairo.Matrix(0.6, 0, 1.0/3, 0.5, 0.04, 0.25))
    cr.push_group()
    cr.rectangle(0, 0, 1, 1); cr.clip()
    def draw_mask():
        cr.set_source_rgb(1, 0.9, 0.6)
        cr.rectangle(0, 0, 1, 1)
        cr.fill()
    draw_mask()
    cr.pop_group_to_source()
    cr.paint_with_alpha(alpha[1])
    cr.restore()

    cr.save()
    cr.transform(cairo.Matrix(0.6, 0, 1.0/3, 0.5, 0.06, 0.05))
    cr.push_group()
    cr.rectangle(0, 0, 1, 1); cr.clip()
    def draw_src():
        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(0, 0, 1, 1)
        cr.fill()
    draw_src()
    cr.pop_group_to_source()
    cr.paint_with_alpha(alpha[2])
    cr.restore()

    if True:
        cr.save()
        cr.translate(1, 0)
        cr.scale(1.0 / 3, 1.0 / 3)
        cr.push_group()
        cr.rectangle(0, 0, 1, 1); cr.clip()
        draw_src()
        cr.pop_group_to_source()
        cr.paint()
        cr.restore()

        cr.save()
        cr.translate(1, 1.0 / 3)
        cr.scale(1.0 / 3, 1.0 / 3)
        cr.push_group()
        cr.rectangle(0, 0, 1, 1); cr.clip()
        draw_mask()
        cr.pop_group_to_source()
        cr.paint()
        cr.restore()

        cr.save()
        cr.translate(1, 2.0 / 3)
        cr.scale(1.0 / 3, 1.0 / 3)
        cr.push_group()
        cr.rectangle(0, 0, 1, 1); cr.clip()
        draw_dest()
        cr.pop_group_to_source()
        cr.paint()
        cr.restore()

        cr.set_line_width( max(cr.device_to_user_distance(2, 2)) )
        cr.rectangle(1, 0, 1.0/3, 1)
        cr.clip_preserve()
        cr.stroke()
        cr.rectangle(1, 1.0/3, 1.0/3, 1.0/3)
        cr.stroke()

    pixels = surface.get_data()[:]
    #cr.show_page()
    print("pixels=%s bytes" % len(pixels))
    surface.finish()

    reset_stats()
    for encoder in ENCODER_NAME.keys():
        test_encode(pixels, encoder, 500)
    print("image compression test complete")
    print_stats()
    print("")

def main():
    print("encoders being tested: %s" % ENCODER_NAME)
    print("versions: %s" % ENCODER_VERSION)
    test_image()
    test_packets()


if __name__ == "__main__":
    main()
