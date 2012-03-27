# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.gobject_compat import import_gobject
gobject = import_gobject()

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
        self._protocol = None
        self.init_packet_handlers()

    def ready(self, conn):
        log.debug("ready(%s)", conn)
        self._protocol = Protocol(conn, self.process_packet)
        ClientSource(self._protocol)

    def init_packet_handlers(self):
        self._packet_handlers = {
            "challenge": self._process_challenge,
            "disconnect": self._process_disconnect,
            "hello": self._process_hello,
            "set_deflate": self._process_set_deflate,
            Protocol.CONNECTION_LOST: self._process_connection_lost,
            Protocol.GIBBERISH: self._process_gibberish,
            }

    def send_hello(self, challenge_response=None):
        hello = self.make_hello(challenge_response)
        log.debug("send_hello(%s) packet=%s", challenge_response, hello)
        self.send(["hello", hello])

    def make_hello(self, challenge_response=None):
        capabilities = {"version": xpra.__version__}
        if challenge_response:
            capabilities["challenge_response"] = challenge_response
        if self.encoding:
            capabilities["encoding"] = self.encoding
        capabilities["encodings"] = ENCODINGS
        if self.jpegquality:
            capabilities["jpeg"] = self.jpegquality
        capabilities["packet_size"] = True
        #will be removed (only for compatibility with old versions):
        capabilities["dynamic_compression"] = True
        capabilities["__prerelease_version"] = xpra.__version__
        return capabilities

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
        log.error("server requested disconnect: %s", packet[1:])
        self.quit()
        return

    def _process_challenge(self, packet):
        if not self.password_file:
            log.error("password is required by the server")
            self.quit()
            return
        import hmac
        try:
            passwordFile = open(self.password_file, "rU")
            password = passwordFile.read()
        except IOError, e:
            log.error("failed to open password file %s: %s", self.password_file, e)
            self.quit()
            return
        salt = packet[1]
        challenge_response = hmac.HMAC(password, salt)
        self.send_hello(challenge_response.hexdigest())

    def _process_hello(self, packet):
        pass

    def _process_set_deflate(self, packet):
        #this tell us the server has set its compressor
        #(the decompressor has been enabled - see protocol)
        log.debug("set_deflate: %s", packet[1:])

    def _process_connection_lost(self, packet):
        log.error("Connection lost")
        self.quit()

    def _process_gibberish(self, packet):
        (_, data) = packet
        log.info("Received uninterpretable nonsense: %s", repr(data))
        self.emit("received-gibberish", data)

    def process_packet(self, proto, packet):
        packet_type = packet[0]
        handler = self._packet_handlers.get(packet_type)
        if not handler:
            log.error("unknown packet type: %s", packet_type)
            return
        handler(packet)

gobject.type_register(XpraClientBase)


class GLibXpraClient(XpraClientBase):
    """
        Utility superclass for glib clients
    """

    def __init__(self, conn, opts):
        XpraClientBase.__init__(self, opts)
        self.exit_code = 0
        self.ready(conn)
        self.send_hello()

    def run(self):
        import glib
        glib.threads_init()
        gobject.threads_init()
        self.glib_mainloop = glib.MainLoop()
        self.glib_mainloop.run()
        return  self.exit_code

    def make_hello(self, challenge_response=None):
        capabilities = XpraClientBase.make_hello(self, challenge_response)
        capabilities["keyboard"] = False
        return capabilities

    def quit(self, *args):
        self.glib_mainloop.quit()


class ScreenshotXpraClient(GLibXpraClient):
    """ This client does one thing only:
        it sends the hello packet with a screenshot request
        and exits when the resulting image is received (or timedout)
    """

    def __init__(self, conn, opts, screenshot_filename):
        self.screenshot_filename = screenshot_filename
        def screenshot_timeout(*args):
            self.exit_code = 1
            log.error("timeout: did not receive the screenshot")
            self.quit()
        gobject.timeout_add(10*1000, screenshot_timeout)
        GLibXpraClient.__init__(self, conn, opts)

    def _process_screenshot(self, packet):
        (w, h, encoding, _, img_data) = packet[1:6]
        assert encoding=="png"
        f = open(self.screenshot_filename, 'wb')
        f.write(img_data)
        f.close()
        log.info("screenshot %sx%s saved to: %s", w, h, self.screenshot_filename)
        self.quit()

    def init_packet_handlers(self):
        XpraClientBase.init_packet_handlers(self)
        self._packet_handlers["screenshot"] = self._process_screenshot

    def make_hello(self, challenge_response=None):
        capabilities = GLibXpraClient.make_hello(self, challenge_response)
        capabilities["screenshot_request"] = True
        return capabilities


class VersionXpraClient(GLibXpraClient):
    """ This client does one thing only:
        it queries the server for version information and prints it out
    """

    def __init__(self, conn, opts):
        def version_timeout(*args):
            self.exit_code = 1
            log.error("timeout: did not receive the version")
            self.quit()
        gobject.timeout_add(10*1000, version_timeout)
        GLibXpraClient.__init__(self, conn, opts)

    def _process_hello(self, packet):
        log.debug("process_hello: %s", packet)
        props = packet[1]
        log.info("%s" % props.get("version"))
        self.quit()

    def make_hello(self, challenge_response=None):
        capabilities = GLibXpraClient.make_hello(self, challenge_response)
        log.debug("make_hello(%s) adding version_request to %s", challenge_response, capabilities)
        capabilities["version_request"] = True
        return capabilities

class StopXpraClient(GLibXpraClient):
    """ stop a server """

    def __init__(self, conn, opts):
        def stop_timeout(*args):
            self.exit_code = 1
            log.error("timeout: server did not disconnect us")
            self.quit()
        gobject.timeout_add(5*1000, stop_timeout)
        GLibXpraClient.__init__(self, conn, opts)

    def _process_hello(self, packet):
        self.send(["shutdown-server"])
