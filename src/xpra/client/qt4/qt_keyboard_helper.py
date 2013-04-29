# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()

from xpra.client.keyboard_helper import KeyboardHelper


class QtKeyboardHelper(KeyboardHelper):

    def __init__(self, net_send, keyboard_sync, key_shortcuts, send_layout, send_keymap):
        self.send_layout = send_layout
        self.send_keymap = send_keymap
        KeyboardHelper.__init__(self, net_send, keyboard_sync, key_shortcuts)

    def get_full_keymap(self):
        return  []
