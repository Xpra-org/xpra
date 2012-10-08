# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import hashlib
from wimpiggy.gobject_compat import import_gobject
gobject = import_gobject()

from wimpiggy.util import n_arg_signal
from wimpiggy.log import Logger
log = Logger()

from xpra.protocol import Protocol, has_rencode
from xpra.scripts.main import ENCODINGS
from xpra.version_util import is_compatible_with, add_version_info
from xpra.platform import get_machine_id

def nn(x):
    if x is None:
        return  ""
    return x

EXIT_OK = 0
EXIT_CONNECTION_LOST = 1
EXIT_TIMEOUT = 2
EXIT_PASSWORD_REQUIRED = 3
EXIT_PASSWORD_FILE_ERROR = 4
EXIT_INCOMPATIBLE_VERSION = 5

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
        return packet, None, None, has_more


class XpraClientBase(gobject.GObject):
    """Base class for Xpra clients.
        Provides the glue code for:
        * sending packets via Protocol
        * handling packets received via _process_packet
    """

    __gsignals__ = {
        "handshake-complete": n_arg_signal(0),
        "first-ui-received" : n_arg_signal(0),
        "received-gibberish": n_arg_signal(1),
        }

    def __init__(self, opts):
        gobject.GObject.__init__(self)
        self.exit_code = None
        self.compression_level = opts.compression_level
        self.password = None
        self.password_file = opts.password_file
        self.encoding = opts.encoding
        self.quality = opts.quality
        self._protocol = None
        self.server_capabilities = {}
        self._remote_version = None
        self._remote_revision = None
        self.init_packet_handlers()

    def ready(self, conn):
        log.debug("ready(%s)", conn)
        self._protocol = Protocol(conn, self.process_packet)
        self._protocol.set_compression_level(self.compression_level)
        ClientSource(self._protocol)
        self._protocol.start()

    def init_packet_handlers(self):
        self._packet_handlers = {}
        self._ui_packet_handlers = {
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
        capabilities = {}
        add_version_info(capabilities)
        if challenge_response:
            capabilities["challenge_response"] = challenge_response
        if self.encoding:
            capabilities["encoding"] = self.encoding
        capabilities["encodings"] = ENCODINGS
        if self.quality>=0:
            capabilities["jpeg"] = self.quality
            capabilities["quality"] = self.quality
        capabilities["platform"] = sys.platform
        capabilities["client_type"] = "Python/Gobject"
        capabilities["raw_packets"] = True
        capabilities["chunked_compression"] = True
        capabilities["rencode"] = has_rencode
        capabilities["server-window-resize"] = True
        u = hashlib.sha512()
        u.update(str(get_machine_id()))
        if os.name=="posix":
            u.update("/")
            u.update(str(os.getuid()))
            u.update("/")
            u.update(str(os.getgid()))
        capabilities["uuid"] = u.hexdigest()
        try:
            from wimpiggy.prop import set_xsettings_format
            assert set_xsettings_format
            capabilities["xsettings-tuple"] = True
        except:
            pass
        capabilities["randr_notify"] = False    #only client.py cares about this
        capabilities["windows"] = False         #only client.py cares about this
        return capabilities

    def send(self, packet):
        if self._protocol and self._protocol.source:
            self._protocol.source.queue_ordinary_packet(packet)

    def send_now(self, packet):
        if self._protocol and self._protocol.source:
            self._protocol.source.queue_priority_packet(packet)

    def cleanup(self):
        if self._protocol:
            self._protocol.close()
            self._protocol = None

    def run(self):
        raise Exception("override me!")

    def quit(self, exit_code=0):
        if self.exit_code is None:
            self.exit_code = exit_code
        raise Exception("override me!")

    def warn_and_quit(self, exit_code, warning):
        log.warn(warning)
        self.quit(exit_code)

    def _process_disconnect(self, packet):
        if len(packet)==2:
            info = packet[1]
        else:
            info = packet[1:]
        self.warn_and_quit(EXIT_OK, "server requested disconnect: %s" % info)

    def _process_connection_lost(self, packet):
        self.warn_and_quit(EXIT_CONNECTION_LOST, "Connection lost")

    def _process_challenge(self, packet):
        if not self.password_file and not self.password:
            self.warn_and_quit(EXIT_PASSWORD_REQUIRED, "password is required by the server")
            return
        if not self.password:
            self.load_password()
            log("password read from file %s is %s", self.password_file, self.password)
        if self.password:
            salt = packet[1]
            import hmac
            challenge_response = hmac.HMAC(self.password, salt)
            self.send_hello(challenge_response.hexdigest())

    def load_password(self):
        try:
            passwordFile = open(self.password_file, "rU")
            self.password = passwordFile.read()
            passwordFile.close()
            while self.password.endswith("\n") or self.password.endswith("\r"):
                self.password = self.password[:-1]
        except IOError, e:
            self.warn_and_quit(EXIT_PASSWORD_FILE_ERROR, "failed to open password file %s: %s" % (self.password_file, e))

    def _process_hello(self, packet):
        self.server_capabilities = packet[1]
        self.parse_server_capabilities(self.server_capabilities)

    def parse_server_capabilities(self, capabilities):
        self._remote_version = capabilities.get("version")
        self._remote_revision = capabilities.get("revision")
        try:
            from wimpiggy.prop import set_xsettings_format
            set_xsettings_format(use_tuple=capabilities.get("xsettings-tuple", False))
        except Exception, e:
            if os.name=="posix" and not sys.platform.startswith("darwin"):
                log.error("failed to set xsettings format: %s", e)
        if not is_compatible_with(self._remote_version):
            self.warn_and_quit(EXIT_INCOMPATIBLE_VERSION, "incompatible remote version: %s" % self._remote_version)
            return False
        if capabilities.get("rencode") and has_rencode:
            self._protocol.enable_rencode()
        self._protocol.chunked_compression = capabilities.get("chunked_compression", False)
        return True

    def _process_set_deflate(self, packet):
        #legacy, should not be used for anything
        pass

    def _process_gibberish(self, packet):
        (_, data) = packet
        log.info("Received uninterpretable nonsense: %s", repr(data))
        self.emit("received-gibberish", data)

    def process_packet(self, proto, packet):
        packet_type = packet[0]
        handler = self._packet_handlers.get(packet_type)
        if handler:
            handler(packet)
            return
        handler = self._ui_packet_handlers.get(packet_type)
        if not handler:
            log.error("unknown packet type: %s", packet_type)
            return
        gobject.idle_add(handler, packet)

gobject.type_register(XpraClientBase)


class GLibXpraClient(XpraClientBase):
    """
        Utility superclass for glib clients
    """

    def __init__(self, conn, opts):
        XpraClientBase.__init__(self, opts)
        self.ready(conn)
        self.send_hello()

    def init_packet_handlers(self):
        XpraClientBase.init_packet_handlers(self)
        def noop(*args):
            log("ignoring packet: %s", args)
        #ignore the following packet types without error:
        for t in ["new-window", "new-override-redirect",
                  "draw", "cursor", "bell",
                  "notify_show", "notify_close",
                  "ping", "ping_echo",
                  "window-metadata", "configure-override-redirect",
                  "lost-window"]:
            self._packet_handlers[t] = noop

    def run(self):
        import glib
        try:
            glib.threads_init()
        except AttributeError:
            #old versions of glib may not have this method
            pass
        try:
            gobject.threads_init()
        except AttributeError:
            #old versions of gobject may not have this method
            pass
        self.glib_mainloop = glib.MainLoop()
        self.glib_mainloop.run()
        return  self.exit_code

    def make_hello(self, challenge_response=None):
        capabilities = XpraClientBase.make_hello(self, challenge_response)
        capabilities["keyboard"] = False
        capabilities["client_type"] = "Python/Glib"
        return capabilities

    def quit(self, exit_code):
        if self.exit_code is None:
            self.exit_code = exit_code
        self.cleanup()
        gobject.timeout_add(50, self.glib_mainloop.quit)


class ScreenshotXpraClient(GLibXpraClient):
    """ This client does one thing only:
        it sends the hello packet with a screenshot request
        and exits when the resulting image is received (or timedout)
    """

    def __init__(self, conn, opts, screenshot_filename):
        self.screenshot_filename = screenshot_filename
        def screenshot_timeout(*args):
            self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the screenshot")
        gobject.timeout_add(10*1000, screenshot_timeout)
        GLibXpraClient.__init__(self, conn, opts)

    def _process_screenshot(self, packet):
        (w, h, encoding, _, img_data) = packet[1:6]
        assert encoding=="png"
        if len(img_data)==0:
            self.warn_and_quit(EXIT_OK, "screenshot is empty and has not been saved (maybe there are no windows or they are not currently shown)")
            return
        f = open(self.screenshot_filename, 'wb')
        f.write(img_data)
        f.close()
        self.warn_and_quit(EXIT_OK, "screenshot %sx%s saved to: %s" % (w, h, self.screenshot_filename))

    def init_packet_handlers(self):
        GLibXpraClient.init_packet_handlers(self)
        self._ui_packet_handlers["screenshot"] = self._process_screenshot

    def make_hello(self, challenge_response=None):
        capabilities = GLibXpraClient.make_hello(self, challenge_response)
        capabilities["screenshot_request"] = True
        return capabilities


class InfoXpraClient(GLibXpraClient):
    """ This client does one thing only:
        it queries the server with an 'info' request
    """

    def __init__(self, conn, opts):
        def info_timeout(*args):
            self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the info")
        gobject.timeout_add(10*1000, info_timeout)
        GLibXpraClient.__init__(self, conn, opts)

    def _process_hello(self, packet):
        log.debug("process_hello: %s", packet)
        props = packet[1]
        if props:
            for k in sorted(props.keys()):
                v = props.get(k)
                log.info("%s=%s", k, v)
        self.quit(0)

    def make_hello(self, challenge_response=None):
        capabilities = GLibXpraClient.make_hello(self, challenge_response)
        log.debug("make_hello(%s) adding info_request to %s", challenge_response, capabilities)
        capabilities["info_request"] = True
        return capabilities


class VersionXpraClient(GLibXpraClient):
    """ This client does one thing only:
        it queries the server for version information and prints it out
    """

    def __init__(self, conn, opts):
        def version_timeout(*args):
            log.error("timeout: did not receive the version")
            self.quit(5)
        gobject.timeout_add(10*1000, version_timeout)
        GLibXpraClient.__init__(self, conn, opts)

    def _process_hello(self, packet):
        log.debug("process_hello: %s", packet)
        props = packet[1]
        self.warn_and_quit(EXIT_OK, str(props.get("version")))

    def make_hello(self, challenge_response=None):
        capabilities = GLibXpraClient.make_hello(self, challenge_response)
        log.debug("make_hello(%s) adding version_request to %s", challenge_response, capabilities)
        capabilities["version_request"] = True
        return capabilities


class StopXpraClient(GLibXpraClient):
    """ stop a server """

    def __init__(self, conn, opts):
        def stop_timeout(*args):
            self.warn_and_quit(EXIT_TIMEOUT, "timeout: server did not disconnect us")
        gobject.timeout_add(5*1000, stop_timeout)
        GLibXpraClient.__init__(self, conn, opts)

    def _process_hello(self, packet):
        self.send(["shutdown-server"])
