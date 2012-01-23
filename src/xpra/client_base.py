# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import glib
import gobject

from wimpiggy.util import n_arg_signal
from wimpiggy.log import Logger
log = Logger()

from xpra.protocol import Protocol
from xpra.scripts.main import ENCODINGS

import xpra

def nn(x):
    if x is None:
        return  ""
    return x

class ClientSource(object):
    def __init__(self, protocol):
        self._priority_packets = []
        self._ordinary_packets = []
        self._mouse_position = None
        self._protocol = protocol
        self._protocol.source = self

    def queue_priority_packet(self, packet):
        self._priority_packets.append(packet)
        self._protocol.source_has_more()

    def queue_ordinary_packet(self, packet):
        self._ordinary_packets.append(packet)
        self._protocol.source_has_more()

    def queue_positional_packet(self, packet):
        self.queue_ordinary_packet(packet)
        self._mouse_position = None

    def queue_mouse_position_packet(self, packet):
        self._mouse_position = packet
        self._protocol.source_has_more()

    def next_packet(self):
        if self._priority_packets:
            packet = self._priority_packets.pop(0)
        elif self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
        elif self._mouse_position is not None:
            packet = self._mouse_position
            self._mouse_position = None
        else:
            packet = None
        has_more = packet is not None and \
                (bool(self._priority_packets) or bool(self._ordinary_packets) \
                 or self._mouse_position is not None)
        return packet, has_more

class XpraClientBase(gobject.GObject):
    """Base class for Xpra clients.
        Provides the glue code for:
        * sending packets via Protocol
        * handling packets received via _process_packet
    """
    
    __gsignals__ = {
        "handshake-complete": n_arg_signal(0),
        "received-gibberish": n_arg_signal(1),
        }

    def __init__(self, opts):
        gobject.GObject.__init__(self)
        self.password_file = opts.password_file
        self.encoding = opts.encoding
        self.jpegquality = opts.jpegquality
        self.init_packet_handlers()
    
    def ready(self, conn):
        self.init_packet_handlers()
        self._protocol = Protocol(conn, self.process_packet)
        ClientSource(self._protocol)

    def init_packet_handlers(self):
        self._packet_handlers = {
            "challenge": self._process_challenge,
            "disconnect": self._process_disconnect,
            "hello": self._process_hello,
            "set_deflate": self._process_set_deflate,
            # "clipboard-*" packets are handled by a special case below.
            Protocol.CONNECTION_LOST: self._process_connection_lost,
            Protocol.GIBBERISH: self._process_gibberish,
            }

    def send_hello(self, hash=None):
        hello = self.make_hello(hash)
        self.send(["hello", hello])

    def make_hello(self, hash=None):
        capabilities_request = {"__prerelease_version": xpra.__version__}
        capabilities_request["version"] = xpra.__version__
        if hash:
            capabilities_request["challenge_response"] = hash
        capabilities_request["dynamic_compression"] = True
        capabilities_request["packet_size"] = True
        if self.encoding:
            capabilities_request["encoding"] = self.encoding
        capabilities_request["encodings"] = ENCODINGS
        if self.jpegquality:
            capabilities_request["jpeg"] = self.jpegquality
        return capabilities_request

    def send(self, packet):
        self._protocol.source.queue_ordinary_packet(packet)

    def send_now(self, packet):
        self._protocol.source.queue_priority_packet(packet)

    def cleanup(self):
        if self._protocol:
            self._protocol.close()
            self._protocol = None

    def run(self):
        raise Exception("override me!")

    def quit(self, *args):
        raise Exception("override me!")

    def _process_disconnect(self, packet):
        log.error("server requested disconnect: %s" % str(packet))
        self.quit()
        return

    def _process_challenge(self, packet):
        if not self.password_file:
            log.error("password is required by the server")
            self.quit()
            return
        import hmac
        passwordFile = open(self.password_file, "rU")
        password = passwordFile.read()
        (_, salt) = packet
        hash = hmac.HMAC(password, salt)
        self.send_hello(hash.hexdigest())

    def _process_hello(self, packet):
        pass

    def _process_set_deflate(self, packet):
        #this tell us the server has set its compressor
        #(the decompressor has been enabled - see protocol)
        pass

    def _process_connection_lost(self, packet):
        log.error("Connection lost")
        self.quit()

    def _process_gibberish(self, packet):
        (_, data) = packet
        log.info("Received uninterpretable nonsense: %s", repr(data))
        self.emit("received-gibberish", data)

    def process_packet(self, proto, packet):
        packet_type = packet[0]
        self._packet_handlers[packet_type](packet)

gobject.type_register(XpraClientBase)


class ScreenshotXpraClient(XpraClientBase):
    """ This client does one thing only:
        it sends the hello packet with a screenshot request
        and exits when the resulting image is received (or timedout)
    """

    def __init__(self, conn, opts, screenshot_filename):
        XpraClientBase.__init__(self, opts)
        self.screenshot_filename = screenshot_filename
        self.ready(conn)
        self.send_hello()
        def screenshot_timeout(*args):
            log.error("timeout: did not receive the screenshot")
            self.quit()
        gobject.timeout_add(10*1000, screenshot_timeout)

    def run(self):
        glib.threads_init()
        gobject.threads_init()
        self.glib_mainloop = glib.MainLoop()
        self.glib_mainloop.run()

    def quit(self, *args):
        self.glib_mainloop.quit()

    def _process_screenshot(self, packet):
        (_, w, h, encoding, rowstride, img_data) = packet
        assert encoding=="png"
        f = open(self.screenshot_filename, 'wb')
        f.write(img_data)
        f.close()
        log.info("screenshot %sx%s saved to: %s", w, h, self.screenshot_filename)
        self.quit()

    def init_packet_handlers(self):
        XpraClientBase.init_packet_handlers(self)
        self._packet_handlers["screenshot"] = self._process_screenshot

    def make_hello(self, hash=None):
        capabilities_request = XpraClientBase.make_hello(self, hash)
        capabilities_request["screenshot_request"] = True
        return capabilities_request
