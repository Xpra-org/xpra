#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=line-too-long

import unittest
import binascii

from xpra.os_util import strtobytes, bytestostr
from xpra.util import repr_ellipsized
from xpra.net.bencode.bencode import bencode, bdecode
from xpra.net.bencode import cython_bencode   #@UnresolvedImport


#sample data to encode:
hello = ["hello", {
                   "__prerelease_version"   : "0.0.7.26",
                   "desktop_size"           : [480,800],
                   "jpeg"                   : 4,
                   "challenge"              : "ba59e4110119264f4a6eaf3adc075ea2c5408550",
                   "challenge_response"     : "ba59e4110119264f4a6eaf3adc075ea2c5408550",
                   }]
large_hello = ["hello",
               {'pycrypto.version': '2.6.1', 'named_cursors': True, 'bell': True, 'encoding.cython.version': (0, 1),
                'platform.release': '3.12.5-200.fc19.x86_64', 'lz4': True, 'clipboard.greedy': False,
                'encoding.vpx.version': 'v1.2.0', 'xkbmap_print': u'xkb_keymap {\n\txkb_keycodes  { include "evdev+aliases(qwerty)"\t};\n\txkb_types     { include "complete"\t};\n\txkb_compat    { include "complete"\t};\n\txkb_symbols   { include "pc+gb+us:2+inet(evdev)"\t};\n\txkb_geometry  { include "pc(pc104)"\t};\n};\n',
                'sound.receive': True, 'digest': ('hmac', 'xor'),
                'aliases':
                {'lost-window': 6, 'bell': 7, 'desktop_size': 8, 'new-override-redirect': 9, 'ping_echo': 5, 'new-window': 10,
                 'connection-lost': 11, 'startup-complete': 12, 'info-response': 2, 'disconnect': 13, 'ping': 3, 'window-resized': 14,
                 'set_deflate': 15, 'rpc-reply': 16, 'window-icon': 17, 'draw': 18, 'notify_close': 19, 'sound-data': 1, 'raise-window': 20,
                 'window-metadata': 21, 'set-clipboard-enabled': 22, 'configure-override-redirect': 23, 'challenge': 24, 'cursor': 25,
                 'notify_show': 26, 'gibberish': 27, 'new-tray': 28, 'hello': 29,
                 },
                'platform.platform': 'Linux-3.12.5-200.fc19.x86_64-x86_64-with-fedora-20',
                'mmap_file': '/tmp/xpra.AFrOuc.mmap', 'uuid': '8643124ce701ee68dbb6b7a8c4eb13a5f6409494', 'encoding.opencl.version': '2013.1',
                'bencode.version': ('Cython', 0, 11), 'xkbmap_layout': '',
                'xkbmap_mod_meanings': {'ISO_Level3_Shift': 'mod5', 'Meta_L': 'mod1', 'Control_R': 'control', 'Super_R': 'mod4',
                                        'Mode_switch': 'mod5', 'Hyper_L': 'mod4', 'Caps_Lock': 'lock', 'Alt_L': 'mod1', 'Num_Lock': 'mod2', 'Super_L': 'mod4', 'Shift_R': 'shift', 'Shift_L': 'shift', 'Control_L': 'control'},
                'encoding.PIL.version': '1.1.7', 'platform': 'linux2', 'sound.server_driven': True, 'clipboard': True,
                'encodings.rgb_formats': ['RGB', 'RGBA'], 'chunked_compression': True, 'keyboard_sync': True,
                'sound.pygst.version': (0, 10, 22), 'sound.send': True, 'screen_sizes': [
                    (':0.0', 1920, 1080, 508, 286, [('DVI-I-1', 0, 0, 1920, 1080, 531, 299)], 0, 0, 1920, 1055)],
                'username': 'antoine', 'auto_refresh_delay': 250, 'mmap_token': 215666214940457138203759294163634184205,
                'encoding.h264.YUV420P.profile': 'high10', 'encoding.transparency': True, 'build.cpu': 'x86_64', 'pycrypto.fastmath': True,
                'xkbmap_query': u'rules:      evdev\nmodel:      pc104\nlayout:     gb,us\nvariant:    ,\n',
                'encoding.rgb24zlib': True, 'platform.machine': 'x86_64', 'encoding.csc_atoms': True, 'encoding.x264.YUV420P.profile': 'high10',
                'build.on': 'desktop', 'rencode': True, 'generic_window_types': True, 'gtk.version': (2, 24, 22), 'window.raise': True, 'modifiers': [],
                'name': 'Antoine Martin', 'encoding.client_options': True, 'encoding.supports_delta': ['png', 'rgb24', 'rgb32'],
                'platform.name': 'Linux', 'zlib': True, 'build.revision': '5071', 'client_type': 'Python/Gtk2',
                'sound.pulseaudio.server': '{7725dfc225d14958a625ddaaaea5962b}unix:/run/user/1000/pulse/native', 'encoding_client_options': True,
                'build.by': 'root', 'machine_id': '7725dfc225d14958a625ddaaaea5962b', 'display': ':10', 'python.version': (2, 7, 5),
                'encoding.video_scaling': True, 'encoding.x264.version': 130, 'encoding.uses_swscale': True, 'server_uuid': '',
                'desktop_size': [1920, 1080], 'encodings': ['h264', 'vp8', 'png', 'png/P', 'png/L', 'rgb', 'jpeg'], 'share': False,
                'xkbmap_variant': '', 'sound.pulseaudio.id': '1000@7725dfc225d14958a625ddaaaea5962b/2073', 'cursors': True, 'randr_notify': True,
                'sound.decoders': ['mp3', 'wavpack', 'wav', 'flac', 'speex'], 'rencode.version': '1.0.2',
                'encoding.csc_modes': ('YUV420P', 'YUV422P', 'YUV444P', 'BGRA', 'BGRX'), 'generic-rgb-encodings': True,
                'xkbmap_keycodes': [(65307, 'Escape', 9, 0, 0), (49, '1', 10, 0, 0), (33, 'exclam', 10, 0, 1), (185, 'onesuperior', 10, 0, 2), (161, 'exclamdown', 10, 0, 3), (49, '1', 10, 1, 0), (33, 'exclam', 10, 1, 1), (50, '2', 11, 0, 0), (34, 'quotedbl', 11, 0, 1), (178, 'twosuperior', 11, 0, 2), (2755, 'oneeighth', 11, 0, 3), (50, '2', 11, 1, 0), (64, 'at', 11, 1, 1), (51, '3', 12, 0, 0), (163, 'sterling', 12, 0, 1), (179, 'threesuperior', 12, 0, 2), (163, 'sterling', 12, 0, 3), (51, '3', 12, 1, 0), (35, 'numbersign', 12, 1, 1), (52, '4', 13, 0, 0), (36, 'dollar', 13, 0, 1), (8364, 'EuroSign', 13, 0, 2), (188, 'onequarter', 13, 0, 3), (52, '4', 13, 1, 0), (36, 'dollar', 13, 1, 1), (53, '5', 14, 0, 0),
                                    (37, 'percent', 14, 0, 1), (189, 'onehalf', 14, 0, 2), (2756, 'threeeighths', 14, 0, 3), (53, '5', 14, 1, 0), (37, 'percent', 14, 1, 1), (54, '6', 15, 0, 0), (94, 'asciicircum', 15, 0, 1), (190, 'threequarters', 15, 0, 2), (2757, 'fiveeighths', 15, 0, 3), (54, '6', 15, 1, 0), (94, 'asciicircum', 15, 1, 1), (55, '7', 16, 0, 0), (38, 'ampersand', 16, 0, 1), (123, 'braceleft', 16, 0, 2), (2758, 'seveneighths', 16, 0, 3), (55, '7', 16, 1, 0), (38, 'ampersand', 16, 1, 1), (56, '8', 17, 0, 0), (42, 'asterisk', 17, 0, 1), (91, 'bracketleft', 17, 0, 2), (2761, 'trademark', 17, 0, 3), (56, '8', 17, 1, 0), (42, 'asterisk', 17, 1, 1), (57, '9', 18, 0, 0), (40, 'parenleft', 18, 0, 1),
                                    (93, 'bracketright', 18, 0, 2), (177, 'plusminus', 18, 0, 3), (57, '9', 18, 1, 0), (40, 'parenleft', 18, 1, 1), (48, '0', 19, 0, 0), (41, 'parenright', 19, 0, 1), (125, 'braceright', 19, 0, 2), (176, 'degree', 19, 0, 3), (48, '0', 19, 1, 0), (41, 'parenright', 19, 1, 1), (45, 'minus', 20, 0, 0), (95, 'underscore', 20, 0, 1), (92, 'backslash', 20, 0, 2), (191, 'questiondown', 20, 0, 3), (45, 'minus', 20, 1, 0), (95, 'underscore', 20, 1, 1), (61, 'equal', 21, 0, 0), (43, 'plus', 21, 0, 1), (65115, 'dead_cedilla', 21, 0, 2), (65116, 'dead_ogonek', 21, 0, 3), (61, 'equal', 21, 1, 0), (43, 'plus', 21, 1, 1), (65288, 'BackSpace', 22, 0, 0), (65288, 'BackSpace', 22, 0, 1),
                                    (65289, 'Tab', 23, 0, 0), (65056, 'ISO_Left_Tab', 23, 0, 1), (113, 'q', 24, 0, 0), (81, 'Q', 24, 0, 1), (64, 'at', 24, 0, 2), (2009, 'Greek_OMEGA', 24, 0, 3), (113, 'q', 24, 1, 0), (81, 'Q', 24, 1, 1), (119, 'w', 25, 0, 0), (87, 'W', 25, 0, 1), (435, 'lstroke', 25, 0, 2), (419, 'Lstroke', 25, 0, 3), (119, 'w', 25, 1, 0), (87, 'W', 25, 1, 1), (101, 'e', 26, 0, 0), (69, 'E', 26, 0, 1), (101, 'e', 26, 0, 2), (69, 'E', 26, 0, 3), (101, 'e', 26, 1, 0), (69, 'E', 26, 1, 1), (114, 'r', 27, 0, 0), (82, 'R', 27, 0, 1), (182, 'paragraph', 27, 0, 2), (174, 'registered', 27, 0, 3), (114, 'r', 27, 1, 0), (82, 'R', 27, 1, 1), (116, 't', 28, 0, 0), (84, 'T', 28, 0, 1), (956, 'tslash', 28, 0, 2),
                                    (940, 'Tslash', 28, 0, 3), (116, 't', 28, 1, 0), (84, 'T', 28, 1, 1), (121, 'y', 29, 0, 0), (89, 'Y', 29, 0, 1), (2299, 'leftarrow', 29, 0, 2), (165, 'yen', 29, 0, 3), (121, 'y', 29, 1, 0), (89, 'Y', 29, 1, 1), (117, 'u', 30, 0, 0), (85, 'U', 30, 0, 1), (2302, 'downarrow', 30, 0, 2), (2300, 'uparrow', 30, 0, 3), (117, 'u', 30, 1, 0), (85, 'U', 30, 1, 1), (105, 'i', 31, 0, 0), (73, 'I', 31, 0, 1), (2301, 'rightarrow', 31, 0, 2), (697, 'idotless', 31, 0, 3), (105, 'i', 31, 1, 0), (73, 'I', 31, 1, 1), (111, 'o', 32, 0, 0), (79, 'O', 32, 0, 1), (248, 'oslash', 32, 0, 2), (216, 'Oslash', 32, 0, 3), (111, 'o', 32, 1, 0), (79, 'O', 32, 1, 1), (112, 'p', 33, 0, 0), (80, 'P', 33, 0, 1),
                                    (254, 'thorn', 33, 0, 2), (222, 'THORN', 33, 0, 3), (112, 'p', 33, 1, 0), (80, 'P', 33, 1, 1), (91, 'bracketleft', 34, 0, 0), (123, 'braceleft', 34, 0, 1), (65111, 'dead_diaeresis', 34, 0, 2), (65112, 'dead_abovering', 34, 0, 3), (91, 'bracketleft', 34, 1, 0), (123, 'braceleft', 34, 1, 1), (93, 'bracketright', 35, 0, 0), (125, 'braceright', 35, 0, 1), (65107, 'dead_tilde', 35, 0, 2), (65108, 'dead_macron', 35, 0, 3), (93, 'bracketright', 35, 1, 0), (125, 'braceright', 35, 1, 1), (65293, 'Return', 36, 0, 0), (65507, 'Control_L', 37, 0, 0), (97, 'a', 38, 0, 0), (65, 'A', 38, 0, 1), (230, 'ae', 38, 0, 2), (198, 'AE', 38, 0, 3), (97, 'a', 38, 1, 0), (65, 'A', 38, 1, 1),
                                    (115, 's', 39, 0, 0), (83, 'S', 39, 0, 1), (223, 'ssharp', 39, 0, 2), (167, 'section', 39, 0, 3), (115, 's', 39, 1, 0), (83, 'S', 39, 1, 1), (100, 'd', 40, 0, 0), (68, 'D', 40, 0, 1), (240, 'eth', 40, 0, 2), (208, 'ETH', 40, 0, 3), (100, 'd', 40, 1, 0), (68, 'D', 40, 1, 1), (102, 'f', 41, 0, 0), (70, 'F', 41, 0, 1), (496, 'dstroke', 41, 0, 2), (170, 'ordfeminine', 41, 0, 3), (102, 'f', 41, 1, 0), (70, 'F', 41, 1, 1), (103, 'g', 42, 0, 0), (71, 'G', 42, 0, 1), (959, 'eng', 42, 0, 2), (957, 'ENG', 42, 0, 3), (103, 'g', 42, 1, 0), (71, 'G', 42, 1, 1), (104, 'h', 43, 0, 0), (72, 'H', 43, 0, 1), (689, 'hstroke', 43, 0, 2), (673, 'Hstroke', 43, 0, 3), (104, 'h', 43, 1, 0),
                                    (72, 'H', 43, 1, 1), (106, 'j', 44, 0, 0), (74, 'J', 44, 0, 1), (65121, 'dead_hook', 44, 0, 2), (65122, 'dead_horn', 44, 0, 3), (106, 'j', 44, 1, 0), (74, 'J', 44, 1, 1), (107, 'k', 45, 0, 0), (75, 'K', 45, 0, 1), (930, 'kra', 45, 0, 2), (38, 'ampersand', 45, 0, 3), (107, 'k', 45, 1, 0), (75, 'K', 45, 1, 1), (108, 'l', 46, 0, 0), (76, 'L', 46, 0, 1), (435, 'lstroke', 46, 0, 2), (419, 'Lstroke', 46, 0, 3), (108, 'l', 46, 1, 0), (76, 'L', 46, 1, 1), (59, 'semicolon', 47, 0, 0), (58, 'colon', 47, 0, 1), (65105, 'dead_acute', 47, 0, 2), (65113, 'dead_doubleacute', 47, 0, 3), (59, 'semicolon', 47, 1, 0), (58, 'colon', 47, 1, 1), (39, 'apostrophe', 48, 0, 0),
                                    (64, 'at', 48, 0, 1), (65106, 'dead_circumflex', 48, 0, 2), (65114, 'dead_caron', 48, 0, 3), (39, 'apostrophe', 48, 1, 0), (34, 'quotedbl', 48, 1, 1), (96, 'grave', 49, 0, 0), (172, 'notsign', 49, 0, 1), (124, 'bar', 49, 0, 2), (124, 'bar', 49, 0, 3), (96, 'grave', 49, 1, 0), (126, 'asciitilde', 49, 1, 1), (65505, 'Shift_L', 50, 0, 0), (35, 'numbersign', 51, 0, 0), (126, 'asciitilde', 51, 0, 1), (65104, 'dead_grave', 51, 0, 2), (65109, 'dead_breve', 51, 0, 3), (92, 'backslash', 51, 1, 0), (124, 'bar', 51, 1, 1), (122, 'z', 52, 0, 0), (90, 'Z', 52, 0, 1), (171, 'guillemotleft', 52, 0, 2), (60, 'less', 52, 0, 3), (122, 'z', 52, 1, 0), (90, 'Z', 52, 1, 1),
                                    (120, 'x', 53, 0, 0), (88, 'X', 53, 0, 1), (187, 'guillemotright', 53, 0, 2), (62, 'greater', 53, 0, 3), (120, 'x', 53, 1, 0), (88, 'X', 53, 1, 1), (99, 'c', 54, 0, 0), (67, 'C', 54, 0, 1), (162, 'cent', 54, 0, 2), (169, 'copyright', 54, 0, 3), (99, 'c', 54, 1, 0), (67, 'C', 54, 1, 1), (118, 'v', 55, 0, 0), (86, 'V', 55, 0, 1), (2770, 'leftdoublequotemark', 55, 0, 2), (2768, 'leftsinglequotemark', 55, 0, 3), (118, 'v', 55, 1, 0), (86, 'V', 55, 1, 1), (98, 'b', 56, 0, 0), (66, 'B', 56, 0, 1), (2771, 'rightdoublequotemark', 56, 0, 2), (2769, 'rightsinglequotemark', 56, 0, 3), (98, 'b', 56, 1, 0), (66, 'B', 56, 1, 1), (110, 'n', 57, 0, 0), (78, 'N', 57, 0, 1),
                                    (110, 'n', 57, 0, 2), (78, 'N', 57, 0, 3), (110, 'n', 57, 1, 0), (78, 'N', 57, 1, 1), (109, 'm', 58, 0, 0), (77, 'M', 58, 0, 1), (181, 'mu', 58, 0, 2), (186, 'masculine', 58, 0, 3), (109, 'm', 58, 1, 0), (77, 'M', 58, 1, 1), (44, 'comma', 59, 0, 0), (60, 'less', 59, 0, 1), (2211, 'horizconnector', 59, 0, 2), (215, 'multiply', 59, 0, 3), (44, 'comma', 59, 1, 0), (60, 'less', 59, 1, 1), (46, 'period', 60, 0, 0), (62, 'greater', 60, 0, 1), (183, 'periodcentered', 60, 0, 2), (247, 'division', 60, 0, 3), (46, 'period', 60, 1, 0), (62, 'greater', 60, 1, 1), (47, 'slash', 61, 0, 0), (63, 'question', 61, 0, 1), (65120, 'dead_belowdot', 61, 0, 2), (65110, 'dead_abovedot', 61, 0, 3),
                                    (47, 'slash', 61, 1, 0), (63, 'question', 61, 1, 1), (65506, 'Shift_R', 62, 0, 0), (65450, 'KP_Multiply', 63, 0, 0), (65450, 'KP_Multiply', 63, 0, 1), (65450, 'KP_Multiply', 63, 0, 2), (65450, 'KP_Multiply', 63, 0, 3), (269024801, 'XF86ClearGrab', 63, 0, 4), (65513, 'Alt_L', 64, 0, 0), (65511, 'Meta_L', 64, 0, 1), (32, 'space', 65, 0, 0), (65509, 'Caps_Lock', 66, 0, 0), (65470, 'F1', 67, 0, 0), (65470, 'F1', 67, 0, 1), (65470, 'F1', 67, 0, 2), (65470, 'F1', 67, 0, 3), (269024769, 'XF86Switch_VT_1', 67, 0, 4), (65471, 'F2', 68, 0, 0), (65471, 'F2', 68, 0, 1), (65471, 'F2', 68, 0, 2), (65471, 'F2', 68, 0, 3), (269024770, 'XF86Switch_VT_2', 68, 0, 4), (65472, 'F3', 69, 0, 0),
                                    (65472, 'F3', 69, 0, 1), (65472, 'F3', 69, 0, 2), (65472, 'F3', 69, 0, 3), (269024771, 'XF86Switch_VT_3', 69, 0, 4), (65473, 'F4', 70, 0, 0), (65473, 'F4', 70, 0, 1), (65473, 'F4', 70, 0, 2), (65473, 'F4', 70, 0, 3), (269024772, 'XF86Switch_VT_4', 70, 0, 4), (65474, 'F5', 71, 0, 0), (65474, 'F5', 71, 0, 1), (65474, 'F5', 71, 0, 2), (65474, 'F5', 71, 0, 3), (269024773, 'XF86Switch_VT_5', 71, 0, 4), (65475, 'F6', 72, 0, 0), (65475, 'F6', 72, 0, 1), (65475, 'F6', 72, 0, 2), (65475, 'F6', 72, 0, 3), (269024774, 'XF86Switch_VT_6', 72, 0, 4), (65476, 'F7', 73, 0, 0), (65476, 'F7', 73, 0, 1), (65476, 'F7', 73, 0, 2), (65476, 'F7', 73, 0, 3), (269024775, 'XF86Switch_VT_7', 73, 0, 4),
                                    (65477, 'F8', 74, 0, 0), (65477, 'F8', 74, 0, 1), (65477, 'F8', 74, 0, 2), (65477, 'F8', 74, 0, 3), (269024776, 'XF86Switch_VT_8', 74, 0, 4), (65478, 'F9', 75, 0, 0), (65478, 'F9', 75, 0, 1), (65478, 'F9', 75, 0, 2), (65478, 'F9', 75, 0, 3), (269024777, 'XF86Switch_VT_9', 75, 0, 4), (65479, 'F10', 76, 0, 0), (65479, 'F10', 76, 0, 1), (65479, 'F10', 76, 0, 2), (65479, 'F10', 76, 0, 3), (269024778, 'XF86Switch_VT_10', 76, 0, 4), (65407, 'Num_Lock', 77, 0, 0), (65300, 'Scroll_Lock', 78, 0, 0), (65429, 'KP_Home', 79, 0, 0), (65463, 'KP_7', 79, 0, 1), (65431, 'KP_Up', 80, 0, 0), (65464, 'KP_8', 80, 0, 1), (65434, 'KP_Page_Up', 81, 0, 0), (65465, 'KP_9', 81, 0, 1),
                                    (65453, 'KP_Subtract', 82, 0, 0), (65453, 'KP_Subtract', 82, 0, 1), (65453, 'KP_Subtract', 82, 0, 2), (65453, 'KP_Subtract', 82, 0, 3), (269024803, 'XF86Prev_VMode', 82, 0, 4), (65430, 'KP_Left', 83, 0, 0), (65460, 'KP_4', 83, 0, 1), (65437, 'KP_Begin', 84, 0, 0), (65461, 'KP_5', 84, 0, 1), (65432, 'KP_Right', 85, 0, 0), (65462, 'KP_6', 85, 0, 1), (65451, 'KP_Add', 86, 0, 0), (65454, 'KP_Decimal', 129, 0, 0), (65454, 'KP_Decimal', 129, 0, 1), (65329, 'Hangul', 130, 0, 0), (65332, 'Hangul_Hanja', 131, 0, 0), (65515, 'Super_L', 133, 0, 0), (65516, 'Super_R', 134, 0, 0), (65383, 'Menu', 135, 0, 0), (65385, 'Cancel', 136, 0, 0), (65382, 'Redo', 137, 0, 0),
                                    (268828528, 'SunProps', 138, 0, 0), (65381, 'Undo', 139, 0, 0), (268828529, 'SunFront', 140, 0, 0), (269025111, 'XF86Copy', 141, 0, 0), (269025131, 'XF86Open', 142, 0, 0), (269025133, 'XF86Paste', 143, 0, 0), (65384, 'Find', 144, 0, 0), (269025112, 'XF86Cut', 145, 0, 0), (65386, 'Help', 146, 0, 0), (269025125, 'XF86MenuKB', 147, 0, 0), (269025053, 'XF86Calculator', 148, 0, 0), (269025071, 'XF86Sleep', 150, 0, 0), (269025067, 'XF86WakeUp', 151, 0, 0), (269025117, 'XF86Explorer', 152, 0, 0), (269025147, 'XF86Send', 153, 0, 0), (269025162, 'XF86Xfer', 155, 0, 0), (269025089, 'XF86Launch1', 156, 0, 0), (269025090, 'XF86Launch2', 157, 0, 0), (269025070, 'XF86WWW', 158, 0, 0),
                                    (269025114, 'XF86DOS', 159, 0, 0), (269025069, 'XF86ScreenSaver', 160, 0, 0), (269025140, 'XF86RotateWindows', 162, 0, 0), (269025049, 'XF86Mail', 163, 0, 0), (269025072, 'XF86Favorites', 164, 0, 0), (269025075, 'XF86MyComputer', 165, 0, 0), (269025062, 'XF86Back', 166, 0, 0), (269025063, 'XF86Forward', 167, 0, 0), (269025068, 'XF86Eject', 169, 0, 0), (269025068, 'XF86Eject', 170, 0, 0), (269025068, 'XF86Eject', 170, 0, 1), (269025047, 'XF86AudioNext', 171, 0, 0), (269025044, 'XF86AudioPlay', 172, 0, 0), (269025073, 'XF86AudioPause', 172, 0, 1), (269025046, 'XF86AudioPrev', 173, 0, 0), (269025045, 'XF86AudioStop', 174, 0, 0), (269025068, 'XF86Eject', 174, 0, 1),
                                    (269025052, 'XF86AudioRecord', 175, 0, 0), (269025086, 'XF86AudioRewind', 176, 0, 0), (269025134, 'XF86Phone', 177, 0, 0), (269025153, 'XF86Tools', 179, 0, 0), (269025048, 'XF86HomePage', 180, 0, 0), (269025139, 'XF86Reload', 181, 0, 0), (269025110, 'XF86Close', 182, 0, 0), (269025144, 'XF86ScrollUp', 185, 0, 0), (269025145, 'XF86ScrollDown', 186, 0, 0), (40, 'parenleft', 187, 0, 0), (41, 'parenright', 188, 0, 0), (269025128, 'XF86New', 189, 0, 0), (65382, 'Redo', 190, 0, 0), (269025153, 'XF86Tools', 191, 0, 0), (269025093, 'XF86Launch5', 192, 0, 0), (269025094, 'XF86Launch6', 193, 0, 0), (269025095, 'XF86Launch7', 194, 0, 0), (269025096, 'XF86Launch8', 195, 0, 0),
                                    (269025097, 'XF86Launch9', 196, 0, 0), (269025193, 'XF86TouchpadToggle', 199, 0, 0), (269025200, 'XF86TouchpadOn', 200, 0, 0), (269025201, 'XF86TouchpadOff', 201, 0, 0), (65406, 'Mode_switch', 203, 0, 0), (65513, 'Alt_L', 204, 0, 1), (65511, 'Meta_L', 205, 0, 1), (65515, 'Super_L', 206, 0, 1), (65517, 'Hyper_L', 207, 0, 1), (269025044, 'XF86AudioPlay', 208, 0, 0), (269025073, 'XF86AudioPause', 209, 0, 0), (269025091, 'XF86Launch3', 210, 0, 0), (269025092, 'XF86Launch4', 211, 0, 0), (269025099, 'XF86LaunchB', 212, 0, 0), (269025191, 'XF86Suspend', 213, 0, 0), (269025110, 'XF86Close', 214, 0, 0), (269025044, 'XF86AudioPlay', 215, 0, 0), (269025175, 'XF86AudioForward', 216, 0, 0),
                                    (65377, 'Print', 218, 0, 0), (269025167, 'XF86WebCam', 220, 0, 0), (269025049, 'XF86Mail', 223, 0, 0), (269025166, 'XF86Messenger', 224, 0, 0), (269025051, 'XF86Search', 225, 0, 0), (269025119, 'XF86Go', 226, 0, 0), (269025084, 'XF86Finance', 227, 0, 0), (269025118, 'XF86Game', 228, 0, 0), (269025078, 'XF86Shop', 229, 0, 0), (65385, 'Cancel', 231, 0, 0), (269025027, 'XF86MonBrightnessDown', 232, 0, 0), (269025026, 'XF86MonBrightnessUp', 233, 0, 0), (269025074, 'XF86AudioMedia', 234, 0, 0), (269025113, 'XF86Display', 235, 0, 0), (269025028, 'XF86KbdLightOnOff', 236, 0, 0), (269025030, 'XF86KbdBrightnessDown', 237, 0, 0), (269025029, 'XF86KbdBrightnessUp', 238, 0, 0),
                                    (269025147, 'XF86Send', 239, 0, 0), (269025138, 'XF86Reply', 240, 0, 0), (269025168, 'XF86MailForward', 241, 0, 0), (269025143, 'XF86Save', 242, 0, 0), (269025115, 'XF86Documents', 243, 0, 0), (269025171, 'XF86Battery', 244, 0, 0), (269025172, 'XF86Bluetooth', 245, 0, 0), (269025173, 'XF86WLAN', 246, 0, 0)],
                'rgb24zlib': True, 'raw_window_icons': True, 'clipboard.set_enabled': True, 'system_tray': True, 'hostname': 'desktop', 'namespace': True, 'key_repeat': (500, 30),
                'encoding.generic': True, 'version': '0.11.0', 'build.bit': '64bit', 'compressible_cursors': True, 'platform.linux_distribution': ('Fedora', '20', 'Spherical-Cow'),
                'encoding.rgb_lz4': True, 'clipboard.notifications': True, 'sound.encoders': ['mp3', 'wavpack', 'wav', 'flac', 'speex'], 'encoding.avcodec.version': (54, 92, 100), 'encoding.x264.I420.profile': 'high10', 'notify-startup-complete': True, 'bencode': True, 'xkbmap_mod_pointermissing': [], 'server-window-resize': True, 'xsettings-tuple': True, 'encoding.h264.I420.profile': 'high10',
                'clipboard.selections': ['CLIPBOARD', 'PRIMARY', 'SECONDARY'], 'pygtk.version': (2, 24, 0), 'encoding.video_reinit': True, 'build.date': '2014-01-01',
                'xkbmap_x11_keycodes': {9: ['Escape', '', 'Escape'], 10: ['1', 'exclam', '1', 'exclam', 'onesuperior', 'exclamdown'], 11: ['2', 'quotedbl', '2', 'at', 'twosuperior', 'oneeighth'], 12: ['3', 'sterling', '3', 'numbersign', 'threesuperior', 'sterling'], 13: ['4', 'dollar', '4', 'dollar', 'EuroSign', 'onequarter'], 14: ['5', 'percent', '5', 'percent', 'onehalf', 'threeeighths'], 15: ['6', 'asciicircum', '6', 'asciicircum', 'threequarters', 'fiveeighths'], 16: ['7', 'ampersand', '7', 'ampersand', 'braceleft', 'seveneighths'], 17: ['8', 'asterisk', '8', 'asterisk', 'bracketleft', 'trademark'],
                                        18: ['9', 'parenleft', '9', 'parenleft', 'bracketright', 'plusminus'], 19: ['0', 'parenright', '0', 'parenright', 'braceright', 'degree'], 20: ['minus', 'underscore', 'minus', 'underscore', 'backslash', 'questiondown'], 21: ['equal', 'plus', 'equal', 'plus', 'dead_cedilla', 'dead_ogonek'], 22: ['BackSpace', 'BackSpace', 'BackSpace', 'BackSpace'], 23: ['Tab', 'ISO_Left_Tab', 'Tab', 'ISO_Left_Tab'], 24: ['q', 'Q', 'q', 'Q', 'at', 'Greek_OMEGA'], 25: ['w', 'W', 'w', 'W', 'lstroke', 'Lstroke'], 26: ['e', 'E', 'e', 'E', 'e', 'E'], 27: ['r', 'R', 'r', 'R', 'paragraph', 'registered'],
                                        28: ['t', 'T', 't', 'T', 'tslash', 'Tslash'], 29: ['y', 'Y', 'y', 'Y', 'leftarrow', 'yen'], 30: ['u', 'U', 'u', 'U', 'downarrow', 'uparrow'], 31: ['i', 'I', 'i', 'I', 'rightarrow', 'idotless'],
                                        32: ['o', 'O', 'o', 'O', 'oslash', 'Oslash'], 33: ['p', 'P', 'p', 'P', 'thorn', 'THORN'], 34: ['bracketleft', 'braceleft', 'bracketleft', 'braceleft', 'dead_diaeresis', 'dead_abovering'], 35: ['bracketright', 'braceright', 'bracketright', 'braceright', 'dead_tilde', 'dead_macron'], 36: ['Return', '', 'Return'], 37: ['Control_L', '', 'Control_L'], 38: ['a', 'A', 'a', 'A', 'ae', 'AE'], 39: ['s', 'S', 's', 'S', 'ssharp', 'section'], 40: ['d', 'D', 'd', 'D', 'eth', 'ETH'], 41: ['f', 'F', 'f', 'F', 'dstroke', 'ordfeminine'], 42: ['g', 'G', 'g', 'G', 'eng', 'ENG'], 43: ['h', 'H', 'h', 'H', 'hstroke', 'Hstroke'], 44: ['j', 'J', 'j', 'J', 'dead_hook', 'dead_horn'], 45: ['k', 'K', 'k', 'K', 'kra', 'ampersand'], 46: ['l', 'L', 'l', 'L', 'lstroke', 'Lstroke'],
                                        47: ['semicolon', 'colon', 'semicolon', 'colon', 'dead_acute', 'dead_doubleacute'], 48: ['apostrophe', 'at', 'apostrophe', 'quotedbl', 'dead_circumflex', 'dead_caron'],
                                        49: ['grave', 'notsign', 'grave', 'asciitilde', 'bar', 'bar'], 50: ['Shift_L', '', 'Shift_L'], 51: ['numbersign', 'asciitilde', 'backslash', 'bar', 'dead_grave', 'dead_breve'], 52: ['z', 'Z', 'z', 'Z', 'guillemotleft', 'less'], 53: ['x', 'X', 'x', 'X', 'guillemotright', 'greater'], 54: ['c', 'C', 'c', 'C', 'cent', 'copyright'], 55: ['v', 'V', 'v', 'V', 'leftdoublequotemark', 'leftsinglequotemark'], 56: ['b', 'B', 'b', 'B', 'rightdoublequotemark', 'rightsinglequotemark'], 57: ['n', 'N', 'n', 'N', 'n', 'N'], 58: ['m', 'M', 'm', 'M', 'mu', 'masculine'], 59: ['comma', 'less', 'comma', 'less', 'horizconnector', 'multiply'], 60: ['period', 'greater', 'period', 'greater', 'periodcentered', 'division'], 61: ['slash', 'question', 'slash', 'question', 'dead_belowdot', 'dead_abovedot'],
                                        62: ['Shift_R', '', 'Shift_R'], 63: ['KP_Multiply', 'KP_Multiply', 'KP_Multiply', 'KP_Multiply', 'KP_Multiply', 'KP_Multiply', 'XF86ClearGrab', 'KP_Multiply', 'KP_Multiply', 'XF86ClearGrab'], 64: ['Alt_L', 'Meta_L', 'Alt_L', 'Meta_L'], 65: ['space', '', 'space'], 66: ['Caps_Lock', '', 'Caps_Lock'], 67: ['F1', 'F1', 'F1', 'F1', 'F1', 'F1', 'XF86Switch_VT_1', 'F1', 'F1', 'XF86Switch_VT_1'], 68: ['F2', 'F2', 'F2', 'F2', 'F2', 'F2', 'XF86Switch_VT_2', 'F2', 'F2', 'XF86Switch_VT_2'], 69: ['F3', 'F3', 'F3', 'F3', 'F3', 'F3', 'XF86Switch_VT_3', 'F3', 'F3', 'XF86Switch_VT_3'], 70: ['F4', 'F4', 'F4', 'F4', 'F4', 'F4', 'XF86Switch_VT_4', 'F4', 'F4', 'XF86Switch_VT_4'], 71: ['F5', 'F5', 'F5', 'F5', 'F5', 'F5', 'XF86Switch_VT_5', 'F5', 'F5', 'XF86Switch_VT_5'],
                                        72: ['F6', 'F6', 'F6', 'F6', 'F6', 'F6', 'XF86Switch_VT_6', 'F6', 'F6', 'XF86Switch_VT_6'], 73: ['F7', 'F7', 'F7', 'F7', 'F7', 'F7', 'XF86Switch_VT_7', 'F7', 'F7', 'XF86Switch_VT_7'], 74: ['F8', 'F8', 'F8', 'F8', 'F8', 'F8', 'XF86Switch_VT_8', 'F8', 'F8', 'XF86Switch_VT_8'], 75: ['F9', 'F9', 'F9', 'F9', 'F9', 'F9', 'XF86Switch_VT_9', 'F9', 'F9', 'XF86Switch_VT_9'], 76: ['F10', 'F10', 'F10', 'F10', 'F10', 'F10', 'XF86Switch_VT_10', 'F10', 'F10', 'XF86Switch_VT_10'], 77: ['Num_Lock', '', 'Num_Lock'], 78: ['Scroll_Lock', '', 'Scroll_Lock'], 79: ['KP_Home', 'KP_7', 'KP_Home', 'KP_7'], 80: ['KP_Up', 'KP_8', 'KP_Up', 'KP_8'], 81: ['KP_Prior', 'KP_9', 'KP_Prior', 'KP_9'],
                                        82: ['KP_Subtract', 'KP_Subtract', 'KP_Subtract', 'KP_Subtract', 'KP_Subtract', 'KP_Subtract', 'XF86Prev_VMode', 'KP_Subtract', 'KP_Subtract', 'XF86Prev_VMode'], 83: ['KP_Left', 'KP_4', 'KP_Left', 'KP_4'], 84: ['KP_Begin', 'KP_5', 'KP_Begin', 'KP_5'], 85: ['KP_Right', 'KP_6', 'KP_Right', 'KP_6'], 86: ['KP_Add', 'KP_Add', 'KP_Add', 'KP_Add', 'KP_Add', 'KP_Add', 'XF86Next_VMode', 'KP_Add', 'KP_Add', 'XF86Next_VMode'], 87: ['KP_End', 'KP_1', 'KP_End', 'KP_1'], 88: ['KP_Down', 'KP_2', 'KP_Down', 'KP_2'], 89: ['KP_Next', 'KP_3', 'KP_Next', 'KP_3'], 90: ['KP_Insert', 'KP_0', 'KP_Insert', 'KP_0'], 91: ['KP_Delete', 'KP_Decimal', 'KP_Delete', 'KP_Decimal'], 92: ['ISO_Level3_Shift', '', 'ISO_Level3_Shift'], 94: ['backslash', 'bar', 'backslash', 'bar', 'bar', 'brokenbar', 'bar', 'brokenbar'],
                                        95: ['F11', 'F11', 'F11', 'F11', 'F11', 'F11', 'XF86Switch_VT_11', 'F11', 'F11', 'XF86Switch_VT_11'], 96: ['F12', 'F12', 'F12', 'F12', 'F12', 'F12', 'XF86Switch_VT_12', 'F12', 'F12', 'XF86Switch_VT_12'], 98: ['Katakana', '', 'Katakana'], 99: ['Hiragana', '', 'Hiragana'], 100: ['Henkan_Mode', '', 'Henkan_Mode'], 101: ['Hiragana_Katakana', '', 'Hiragana_Katakana'], 102: ['Muhenkan', '', 'Muhenkan'], 104: ['KP_Enter', '', 'KP_Enter'], 105: ['Control_R', '', 'Control_R'], 106: ['KP_Divide', 'KP_Divide', 'KP_Divide', 'KP_Divide', 'KP_Divide', 'KP_Divide', 'XF86Ungrab', 'KP_Divide', 'KP_Divide', 'XF86Ungrab'], 107: ['Print', 'Sys_Req', 'Print', 'Sys_Req'], 108: ['ISO_Level3_Shift', 'Multi_key', 'ISO_Level3_Shift', 'Multi_key'], 109: ['Linefeed', '', 'Linefeed'], 110: ['Home', '', 'Home'],
                                        111: ['Up', '', 'Up'], 112: ['Prior', '', 'Prior'], 113: ['Left', '', 'Left'], 114: ['Right', '', 'Right'], 115: ['End', '', 'End'], 116: ['Down', '', 'Down'], 117: ['Next', '', 'Next'], 118: ['Insert', '', 'Insert'], 119: ['Delete', '', 'Delete'], 121: ['XF86AudioMute', '', 'XF86AudioMute'], 122: ['XF86AudioLowerVolume', '', 'XF86AudioLowerVolume'], 123: ['XF86AudioRaiseVolume', '', 'XF86AudioRaiseVolume'], 124: ['XF86PowerOff', '', 'XF86PowerOff'], 125: ['KP_Equal', '', 'KP_Equal'], 126: ['plusminus', '', 'plusminus'], 127: ['Pause', 'Break', 'Pause', 'Break'], 128: ['XF86LaunchA', '', 'XF86LaunchA'], 129: ['KP_Decimal', 'KP_Decimal', 'KP_Decimal', 'KP_Decimal'], 130: ['Hangul', '', 'Hangul'], 131: ['Hangul_Hanja', '', 'Hangul_Hanja'], 133: ['Super_L', '', 'Super_L'], 134: ['Super_R', '', 'Super_R'],
                                        135: ['Menu', '', 'Menu'], 136: ['Cancel', '', 'Cancel'], 137: ['Redo', '', 'Redo'], 138: ['SunProps', '', 'SunProps'], 139: ['Undo', '', 'Undo'], 140: ['SunFront', '', 'SunFront'], 141: ['XF86Copy', '', 'XF86Copy'], 142: ['XF86Open', '', 'XF86Open'], 143: ['XF86Paste', '', 'XF86Paste'], 144: ['Find', '', 'Find'], 145: ['XF86Cut', '', 'XF86Cut'], 146: ['Help', '', 'Help'], 147: ['XF86MenuKB', '', 'XF86MenuKB'], 148: ['XF86Calculator', '', 'XF86Calculator'], 150: ['XF86Sleep', '', 'XF86Sleep'], 151: ['XF86WakeUp', '', 'XF86WakeUp'], 152: ['XF86Explorer', '', 'XF86Explorer'], 153: ['XF86Send', '', 'XF86Send'], 155: ['XF86Xfer', '', 'XF86Xfer'], 156: ['XF86Launch1', '', 'XF86Launch1'],
                                        157: ['XF86Launch2', '', 'XF86Launch2'], 158: ['XF86WWW', '', 'XF86WWW'], 159: ['XF86DOS', '', 'XF86DOS'], 160: ['XF86ScreenSaver', '', 'XF86ScreenSaver'], 162: ['XF86RotateWindows', '', 'XF86RotateWindows'], 163: ['XF86Mail', '', 'XF86Mail'], 164: ['XF86Favorites', '', 'XF86Favorites'], 165: ['XF86MyComputer', '', 'XF86MyComputer'], 166: ['XF86Back', '', 'XF86Back'], 167: ['XF86Forward', '', 'XF86Forward'], 169: ['XF86Eject', '', 'XF86Eject'], 170: ['XF86Eject', 'XF86Eject', 'XF86Eject', 'XF86Eject'], 171: ['XF86AudioNext', '', 'XF86AudioNext'], 172: ['XF86AudioPlay', 'XF86AudioPause', 'XF86AudioPlay', 'XF86AudioPause'], 173: ['XF86AudioPrev', '', 'XF86AudioPrev'], 174: ['XF86AudioStop', 'XF86Eject', 'XF86AudioStop', 'XF86Eject'], 175: ['XF86AudioRecord', '', 'XF86AudioRecord'],
                                        176: ['XF86AudioRewind', '', 'XF86AudioRewind'], 177: ['XF86Phone', '', 'XF86Phone'], 179: ['XF86Tools', '', 'XF86Tools'], 180: ['XF86HomePage', '', 'XF86HomePage'], 181: ['XF86Reload', '', 'XF86Reload'], 182: ['XF86Close', '', 'XF86Close'], 185: ['XF86ScrollUp', '', 'XF86ScrollUp'], 186: ['XF86ScrollDown', '', 'XF86ScrollDown'], 187: ['parenleft', '', 'parenleft'], 188: ['parenright', '', 'parenright'], 189: ['XF86New', '', 'XF86New'], 190: ['Redo', '', 'Redo'], 191: ['XF86Tools', '', 'XF86Tools'], 192: ['XF86Launch5', '', 'XF86Launch5'], 193: ['XF86Launch6', '', 'XF86Launch6'], 194: ['XF86Launch7', '', 'XF86Launch7'], 195: ['XF86Launch8', '', 'XF86Launch8'], 196: ['XF86Launch9', '', 'XF86Launch9'], 199: ['XF86TouchpadToggle', '', 'XF86TouchpadToggle'], 200: ['XF86TouchpadOn', '', 'XF86TouchpadOn'],
                                        201: ['XF86TouchpadOff', '', 'XF86TouchpadOff'], 203: ['Mode_switch', '', 'Mode_switch'], 204: ['', 'Alt_L', '', 'Alt_L'], 205: ['', 'Meta_L', '', 'Meta_L'], 206: ['', 'Super_L', '', 'Super_L'], 207: ['', 'Hyper_L', '', 'Hyper_L'], 208: ['XF86AudioPlay', '', 'XF86AudioPlay'], 209: ['XF86AudioPause', '', 'XF86AudioPause'], 210: ['XF86Launch3', '', 'XF86Launch3'], 211: ['XF86Launch4', '', 'XF86Launch4'], 212: ['XF86LaunchB', '', 'XF86LaunchB'], 213: ['XF86Suspend', '', 'XF86Suspend'], 214: ['XF86Close', '', 'XF86Close'], 215: ['XF86AudioPlay', '', 'XF86AudioPlay'], 216: ['XF86AudioForward', '', 'XF86AudioForward'], 218: ['Print', '', 'Print'], 220: ['XF86WebCam', '', 'XF86WebCam'], 223: ['XF86Mail', '', 'XF86Mail'], 224: ['XF86Messenger', '', 'XF86Messenger'], 225: ['XF86Search', '', 'XF86Search'],
                                        226: ['XF86Go', '', 'XF86Go'], 227: ['XF86Finance', '', 'XF86Finance'], 228: ['XF86Game', '', 'XF86Game'], 229: ['XF86Shop', '', 'XF86Shop'], 231: ['Cancel', '', 'Cancel'], 232: ['XF86MonBrightnessDown', '', 'XF86MonBrightnessDown'], 233: ['XF86MonBrightnessUp', '', 'XF86MonBrightnessUp'], 234: ['XF86AudioMedia', '', 'XF86AudioMedia'], 235: ['XF86Display', '', 'XF86Display'], 236: ['XF86KbdLightOnOff', '', 'XF86KbdLightOnOff'], 237: ['XF86KbdBrightnessDown', '', 'XF86KbdBrightnessDown'], 238: ['XF86KbdBrightnessUp', '', 'XF86KbdBrightnessUp'], 239: ['XF86Send', '', 'XF86Send'], 240: ['XF86Reply', '', 'XF86Reply'], 241: ['XF86MailForward', '', 'XF86MailForward'], 242: ['XF86Save', '', 'XF86Save'], 243: ['XF86Documents', '', 'XF86Documents'], 244: ['XF86Battery', '', 'XF86Battery'], 245: ['XF86Bluetooth', '', 'XF86Bluetooth'], 246: ['XF86WLAN', '', 'XF86WLAN']
                                        },
                'encoding.initial_quality': 50, 'xkbmap_mod_managed': [], 'notifications': True, 'windows': True, 'encoding.min-quality': 50, 'clipboard.want_targets': False,
                'encodings.core': ['h264', 'vp8', 'png', 'png/P', 'png/L', 'rgb24', 'jpeg', 'rgb32'], 'raw_packets': True, 'compression_level': 1, 'dpi': 96, 'build.local_modifications': '0', 'platform.processor': 'x86_64', 'sound.gst.version': (0, 10, 36), 'encoding.swscale.version': (2, 2, 100), 'encoding.min-speed': 0
               }]

nested_dicts = ['some_new_feature_we_may_add', {"with_a_nested_dict" : {"containing_another_dict" : ["with", "nested", "arrays", ["in", ["it", "going", [["deep", 0, -1]]]]]}}]
nested_dicts_output = "l27:some_new_feature_we_may_addd18:with_a_nested_dictd23:containing_another_dictl4:with6:nested6:arraysl2:inl2:it5:goingll4:deepi0ei-1eeeeeeeee"


def _cmp(o, r):
    #our own deep compare function,
    #ignores tuple vs list differences,
    #and gives us a clue about where the problem is
    if type(o)==type(r) and o==r:
        return
    if isinstance(r, (tuple, list)) and isinstance(o, (tuple, list)):
        assert len(r)==len(o), "list/tuple differs in length: expected %s but got %s" % (o, r)
        for i, ri in enumerate(r):
            _cmp(o[i], ri)
        return
    if isinstance(r, dict) and isinstance(o, dict):
        for k,ov in o.items():
            #with py3k, the key can end up being bytes instead of string...
            rv = r.get(k, r.get(bytestostr(k), r.get(strtobytes(k))))
            assert rv is not None, "restored dict is missing %s: %s" % (k, r)
            _cmp(ov, rv)
        return
    if isinstance(o, bytes) and isinstance(r, str):
        o = o.decode("utf-8")
    elif isinstance(o, str) and isinstance(r, bytes):
        r = r.decode("utf-8")
    if o==r:
        return
    print("")
    print("original %s:" % type(o))
    print("returned %s:" % type(r))
    print("original: %s" % binascii.hexlify(str(o)))
    print("returned: %s" % binascii.hexlify(str(r)))
    assert False, "value does not match: expected %s (%s) but got %s (%s)" % (o, type(o), r, type(r))

def noop(_input):
    raise NotImplementedError()


class TestBencoderFunctions:

    def setUp(self):
        self.encode = noop
        self.decode = noop

    def test_decoding(self):

        def t(s, ev, remainder=""):
            try:
                rv, rr = self.decode(s)
                #print("decode(%s)=%s (%s)" % (s, rv, type(rv)))
                _cmp(rv, ev)
            except Exception as e:
                print("error on decoding of '%s'" % repr_ellipsized(s))
                raise e
            rrstr = s[rr:]
            assert rrstr == remainder, "expected remainder value '%s' but got %s" % (remainder, rrstr)
            # With gibberish added:
            g_str = s + "asdf"
            rv, rr = self.decode(g_str)
            _cmp(rv, ev)
            rrstr = g_str[rr:]
            assert rrstr.endswith("asdf")

        #t("l16:configure-windowi2ei555ei340ei649ei381ed9:maximizedi0e6:screeni0e9:maximizedi0eee", [], "")

        t("i12345e", 12345)
        t("i-12345e", -12345)
        t("i12345eQQQ", 12345, "QQQ")
        t("3:foo", "foo")
        t("3:gooQQQ", "goo", "QQQ")
        t("li12e4:asdfi34ee", [12, "asdf", 34])
        t("d4:asdf3:doo4:bsdfi1234ee", {"asdf": "doo", "bsdf": 1234})

        t("d4:asdfli1ei2ei3ei4ee5:otheri-55e2:qqd2:qql2:hieee",
          {"asdf": [1, 2, 3, 4], "qq": {"qq": ["hi"]}, "other": -55})

        t("l0:e", [""])

        # Keys do not have to be strings:
        t("di0ei0ee", {0 : 0})

        def te(s, exc):
            #log(" "+s)
            v = None
            try:
                v = self.decode(s)
            except exc:
                pass
            else:
                assert False, "didn't raise exception, returned: %s for %s" % (v, s)

        te("iie", ValueError)
        te("i0x0e", ValueError)
        t("i0e", 0)
        te("i00e", ValueError)

        te("0x2:aa", ValueError)
        te("-1:aa", ValueError)
        te("02:aa", ValueError)


    def t(self, v, encstr=None):
        be = self.encode(v)
        if encstr:
            _cmp(be, encstr)
        restored = self.decode(be)
        rlist = restored[0]
        _cmp(v[0], rlist[0])

        rd = rlist[1]
        od = v[1]
        _cmp(od, rd)

    def test_simple(self):
        v = ["a", []]
        estr = binascii.unhexlify("6c313a616c6565").decode()
        self.t(v, estr)

    def test_unicode(self):
        ustr = "Schr\xc3\xb6dinger\xe2\x80\x99s_Cat".encode("utf8")
        estr = binascii.unhexlify("6c32353a53636872c383c2b664696e676572c3a2c280c299735f436174646565")
        self.t([ustr, {}], estr)
        #from a real packet:
        packet = [
            'draw', 2, 0, 820, 1280, 1, 'rgb32',
            b'\x00\x14\x00\x00OXY[\xff\x04\x00\xff\xd2\x0f\x01\x00\xff\xff\xff\xff\xff\xff\xff'+
            b'\xff\xff\xff\xff\xff\xff\xff\xff\xcc\x0f\xb4\x11\xff\xd2\x0f\xe4\x01\x1d?\xd6\xd6'+
            b'\xd6\x04\x00\x19P\xff\xd6\xd6\xd6\xff',
            94, 5120, {'lz4': 1, 'rgb_format': 'RGBX'}
            ]
        self.t(packet)

    def test_encoding_hello(self):
        self.t(hello)

    def test_encoding_large_hello(self):
        self.t(large_hello)

    def test_nested_dicts(self):
        self.t(nested_dicts, nested_dicts_output)

    def test_invalid_bdecode(self):
        def f(v):
            try:
                self.decode(v)
            except ValueError:
                pass
            else:
                raise Exception("decode should have failed for '%s' (%s)" % (v, type(v)))
        f(b"")
        f(b"XX")        #invalid type code
        f(b"i-0e")      #invalid number
        f(b"li1ei2eXXe")#invalid element in list
        f(b"di1eXXe")   #invalid value in dict
        f(b"dXXi2ee")   #invalid key in dict
        f(b"s")         #input too short


class TestBencoder(unittest.TestCase, TestBencoderFunctions):

    def setUp(self):
        self.encode = bencode
        self.decode = bdecode
        unittest.TestCase.setUp(self)

class TestCythonBencoder(unittest.TestCase, TestBencoderFunctions):

    def setUp(self):
        self.encode = cython_bencode.bencode    #@UndefinedVariable
        self.decode = cython_bencode.bdecode    #@UndefinedVariable
        unittest.TestCase.setUp(self)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
