# This file is part of Parti.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import socket
from wimpiggy.gobject_compat import import_gobject, import_glib
gobject = import_gobject()

from wimpiggy.util import n_arg_signal
from wimpiggy.log import Logger
log = Logger()

from xpra.protocol import Protocol, has_rencode, rencode_version, use_rencode
from xpra.scripts.config import ENCODINGS, ENCRYPTION_CIPHERS, python_platform
from xpra.version_util import is_compatible_with, add_version_info
from xpra.platform import get_machine_id
from xpra.platform.uuid_wrapper import get_hex_uuid

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
EXIT_ENCRYPTION = 6
EXIT_FAILURE = 7

DEFAULT_TIMEOUT = 20*1000


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
        self.password_sent = False
        self.encoding = opts.encoding
        self.encryption = opts.encryption
        self.quality = opts.quality
        self.min_quality = opts.min_quality
        self.speed = opts.speed
        self.min_speed = opts.min_speed
        #protocol stuff:
        self._protocol = None
        self._priority_packets = []
        self._ordinary_packets = []
        self._mouse_position = None
        self._aliases = {}
        self._reverse_aliases = {}
        #server state and caps:
        self.server_capabilities = {}
        self._remote_version = None
        self._remote_revision = None
        self.make_uuid()
        self.init_packet_handlers()
        self.init_aliases()

    def ready(self, conn):
        log.debug("ready(%s)", conn)
        self._protocol = Protocol(conn, self.process_packet, self.next_packet)
        self._protocol.large_packets.append("keymap-changed")
        self._protocol.large_packets.append("server-settings")
        self._protocol.set_compression_level(self.compression_level)
        self._protocol.start()
        self.have_more = self._protocol.source_has_more

    def init_packet_handlers(self):
        self._packet_handlers = {
            "hello": self._process_hello,
            }
        self._ui_packet_handlers = {
            "challenge": self._process_challenge,
            "disconnect": self._process_disconnect,
            "set_deflate": self._process_set_deflate,
            Protocol.CONNECTION_LOST: self._process_connection_lost,
            Protocol.GIBBERISH: self._process_gibberish,
            }

    def init_aliases(self):
        packet_types = list(self._packet_handlers.keys())
        packet_types += list(self._ui_packet_handlers.keys())
        i = 1
        for key in packet_types:
            self._aliases[i] = key
            self._reverse_aliases[key] = i
            i += 1

    def send_hello(self, challenge_response=None):
        hello = self.make_hello(challenge_response)
        log.debug("send_hello(%s) packet=%s", challenge_response, hello)
        self.send("hello", hello)

    def make_hello(self, challenge_response=None):
        capabilities = {}
        add_version_info(capabilities)
        if challenge_response:
            assert self.password
            capabilities["challenge_response"] = challenge_response
        if self.encryption:
            assert self.encryption in ENCRYPTION_CIPHERS
            capabilities["cipher"] = self.encryption
            iv = get_hex_uuid()[:16]
            capabilities["cipher.iv"] = iv
            key_salt = get_hex_uuid()
            capabilities["cipher.key_salt"] = key_salt
            iterations = 1000
            capabilities["cipher.key_stretch_iterations"] = iterations
            self._protocol.set_cipher_in(self.encryption, iv, self.get_password(), key_salt, iterations)
        if self.encoding:
            capabilities["encoding"] = self.encoding
        capabilities["encodings"] = ENCODINGS
        if self.quality>0:
            capabilities["jpeg"] = self.quality
            capabilities["quality"] = self.quality
            capabilities["encoding.quality"] = self.quality
        if self.min_quality>0:
            capabilities["encoding.min-quality"] = self.min_quality
        if self.speed>=0:
            capabilities["speed"] = self.speed
            capabilities["encoding.speed"] = self.speed
        if self.min_speed>=0:
            capabilities["encoding.min-speed"] = self.min_speed
        capabilities["platform"] = sys.platform
        capabilities["platform.release"] = python_platform.release()
        capabilities["platform.machine"] = python_platform.machine()
        capabilities["platform.processor"] = python_platform.processor()
        capabilities["client_type"] = "Python/Gobject"
        capabilities["raw_packets"] = True
        capabilities["chunked_compression"] = True
        capabilities["rencode"] = has_rencode
        if has_rencode:
            capabilities["rencode.version"] = rencode_version
        capabilities["server-window-resize"] = True
        capabilities["hostname"] = socket.gethostname()
        capabilities["uuid"] = self.uuid
        capabilities["randr_notify"] = False    #only client.py cares about this
        capabilities["windows"] = False         #only client.py cares about this
        if self._reverse_aliases:
            capabilities["aliases"] = self._reverse_aliases
        return capabilities

    def make_uuid(self):
        try:
            import hashlib
            u = hashlib.sha1()
        except:
            #try python2.4 variant:
            import sha
            u = sha.new()
        def uupdate(ustr):
            u.update(ustr.encode("utf-8"))
        uupdate(get_machine_id())
        if os.name=="posix":
            uupdate(u"/")
            uupdate(str(os.getuid()))
            uupdate(u"/")
            uupdate(str(os.getgid()))
        self.uuid = u.hexdigest()

    def send(self, *parts):
        self._ordinary_packets.append(parts)
        self.have_more()

    def send_now(self, *parts):
        self._priority_packets.append(parts)
        self.have_more()

    def send_positional(self, packet):
        self._ordinary_packets.append(packet)
        self._mouse_position = None
        self.have_more()

    def send_mouse_position(self, packet):
        self._mouse_position = packet
        self.have_more()

    def have_more(self):
        #this function is overridden in ready()
        p = self._protocol
        if p and p.source:
            p.source_has_more()

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
        e = EXIT_OK
        if self.server_capabilities is None or len(self.server_capabilities)==0:
            #server never sent hello to us - so disconnect is an error
            #(but we don't know which one - the info message may help)
            e = EXIT_FAILURE
        self.warn_and_quit(e, "server requested disconnect: %s" % info)

    def _process_connection_lost(self, packet):
        self.warn_and_quit(EXIT_CONNECTION_LOST, "Connection lost")

    def _process_challenge(self, packet):
        if not self.password_file and not self.password:
            self.warn_and_quit(EXIT_PASSWORD_REQUIRED, "password is required by the server")
            return
        if not self.password:
            if not self.load_password():
                return
            assert self.password
        salt = packet[1]
        if self.encryption:
            assert len(packet)>=3, "challenge does not contain encryption details to use for the response"
            server_cipher = packet[2]
            self.set_server_encryption(server_cipher)
        import hmac
        challenge_response = hmac.HMAC(self.password, salt)
        password_hash = challenge_response.hexdigest()
        self.password_sent = True
        self.send_hello(password_hash)

    def set_server_encryption(self, props):
        cipher = props.get("cipher")
        cipher_iv = props.get("cipher.iv")
        key_salt = props.get("cipher.key_salt")
        iterations = props.get("cipher.key_stretch_iterations")
        if not cipher or not cipher_iv:
            self.warn_and_quit(EXIT_ENCRYPTION, "the server does not use or support encryption/password, cannot continue with %s cipher" % self.encryption)
            return False
        if cipher not in ENCRYPTION_CIPHERS:
            self.warn_and_quit(EXIT_ENCRYPTION, "unsupported server cipher: %s, allowed ciphers: %s" % (cipher, ", ".join(ENCRYPTION_CIPHERS)))
            return False
        self._protocol.set_cipher_out(cipher, cipher_iv, self.get_password(), key_salt, iterations)


    def get_password(self):
        if self.password is None:
            self.load_password()
        return self.password

    def load_password(self):
        try:
            filename = os.path.expanduser(self.password_file)
            passwordFile = open(filename, "rU")
            self.password = passwordFile.read()
            passwordFile.close()
            while self.password.endswith("\n") or self.password.endswith("\r"):
                self.password = self.password[:-1]
        except IOError, e:
            self.warn_and_quit(EXIT_PASSWORD_FILE_ERROR, "failed to open password file %s: %s" % (self.password_file, e))
            return False
        log("password read from file %s is %s", self.password_file, self.password)
        return True

    def _process_hello(self, packet):
        if not self.password_sent and self.password_file:
            log.warn("Warning: the server did not request our password!")
        self.server_capabilities = packet[1]
        self.parse_server_capabilities(self.server_capabilities)

    def parse_server_capabilities(self, capabilities):
        self._remote_version = capabilities.get("version")
        self._remote_revision = capabilities.get("revision")
        if not is_compatible_with(self._remote_version):
            self.warn_and_quit(EXIT_INCOMPATIBLE_VERSION, "incompatible remote version: %s" % self._remote_version)
            return False
        if capabilities.get("rencode") and use_rencode:
            self._protocol.enable_rencode()
        if self.encryption:
            #server uses a new cipher after second hello:
            self.set_server_encryption(capabilities)
        self._protocol.chunked_compression = capabilities.get("chunked_compression", False)
        self._protocol.aliases = capabilities.get("aliases", {})
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
        if type(packet_type)==int:
            packet_type = self._aliases.get(packet_type)
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
        gobject.timeout_add(DEFAULT_TIMEOUT, self.timeout)
        self.send_hello()

    def timeout(self, *args):
        log.warn("timeout!")

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
        glib = import_glib()
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
        GLibXpraClient.__init__(self, conn, opts)

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the screenshot")

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

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the info")

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

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the version")

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

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: server did not disconnect us")

    def _process_hello(self, packet):
        gobject.idle_add(self.send, "shutdown-server")
